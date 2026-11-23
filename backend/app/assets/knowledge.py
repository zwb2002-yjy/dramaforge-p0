"""Owner-scoped cultural knowledge: explicit drafts, published snapshots and withdrawal.

Knowledge belongs to the user across Workspaces (N05). Every decision appends one
immutable revision and moves the entry pointer/version/status in the same transaction;
a replay returns the original receipt, a stale expected version is refused, and
published content is never silently replaced by a draft. Private source links are only
read through the originating project, never through cross-project read models.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User, Workspace
from app.assets.domain_events import emit
from app.assets.knowledge_models import (
    KNOWLEDGE_KINDS,
    KnowledgeEntry,
    KnowledgeRevision,
    KnowledgeSourceLink,
)
from app.assets.knowledge_public import (
    KnowledgeRevisionRead,
    canonical_body,
    canonical_note,
    lock_write_scope,
    public_text,
    shared_revisions,
)
from app.assets.research_bodies import content_hash, summary_text
from app.assets.source_use_models import USE_PURPOSES
from app.shared.errors import AppError, NotFoundError, ValidationAppError

MAX_SOURCE_LINKS = 20


class KnowledgeConflictError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=409)


@dataclass(frozen=True)
class SourceLinkInput:
    project_id: UUID
    research_revision_id: UUID


@dataclass(frozen=True)
class PublicSourceNote:
    label: str
    public_url: str | None = None
    locator_note: str | None = None


@dataclass(frozen=True)
class KnowledgeMutationReceipt:
    entry_id: UUID
    revision_id: UUID
    result_entry_version: int
    publication_status: str
    content_hash: str


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _request_body(kind: str, canonical: dict[str, object]) -> dict[str, object]:
    # Existing event receipts hashed the empty research relationship defaults.
    # Preserve replay identity; these fields never enter a knowledge revision.
    if kind == "event":
        return {**canonical, "related_person_ids": [], "related_place_ids": []}
    return canonical


def _validate_uses(values: list[str]) -> list[str]:
    uses = sorted({str(value) for value in values})
    if any(value not in USE_PURPOSES for value in uses):
        raise ValidationAppError(
            "Unsupported knowledge use", details={"code": "KNOWLEDGE_USE_INVALID"}
        )
    return uses


def _validate_notes(values: list[PublicSourceNote]) -> list[dict[str, object]]:
    if len(values) > 20:
        raise ValidationAppError("Too many public source notes")
    return [canonical_note(asdict(note)) for note in values]


class KnowledgeService:
    """Caller owns commit; every operation is owner-scoped, never project-scoped."""

    def __init__(self, session: AsyncSession, *, actor: User) -> None:
        self.session = session
        self.actor = actor

    async def _entry(self, entry_id: UUID, *, lock: bool = False) -> KnowledgeEntry:
        query = select(KnowledgeEntry).where(
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.owner_user_id == self.actor.id,
        )
        if lock:
            query = query.with_for_update()
        entry = await self.session.scalar(query.execution_options(populate_existing=True))
        if entry is None:
            raise NotFoundError("knowledge entry not found")
        return entry

    async def _replay(self, request_key: str, request_hash: str) -> KnowledgeRevision | None:
        existing = await self.session.scalar(
            select(KnowledgeRevision).where(
                KnowledgeRevision.owner_user_id == self.actor.id,
                KnowledgeRevision.request_key == request_key,
            )
        )
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise KnowledgeConflictError(
                "KNOWLEDGE_REQUEST_KEY_REUSED",
                "Knowledge request key already used for a different decision",
            )
        return existing

    async def _next_number(self, entry_id: UUID) -> int:
        current = await self.session.scalar(
            select(func.max(KnowledgeRevision.number)).where(
                KnowledgeRevision.owner_user_id == self.actor.id,
                KnowledgeRevision.entry_id == entry_id,
            )
        )
        return int(current or 0) + 1

    async def _workspace(self, workspace_id: UUID) -> Workspace:
        workspace = await self.session.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id, Workspace.owner_user_id == self.actor.id
            )
        )
        if workspace is None:
            raise NotFoundError("workspace not found")
        return workspace

    async def _source_links(
        self,
        links: list[SourceLinkInput],
        *,
        knowledge_revision: KnowledgeRevision | None = None,
    ) -> list[dict[str, object]]:
        if len(links) > MAX_SOURCE_LINKS:
            raise ValidationAppError("Too many source links")
        seen: set[tuple[UUID, UUID]] = set()
        payload: list[dict[str, object]] = []
        for link in links:
            key = (link.project_id, link.research_revision_id)
            if key in seen:
                raise ValidationAppError(
                    "Duplicate source link", details={"code": "KNOWLEDGE_SOURCE_DUPLICATE"}
                )
            seen.add(key)
            project = await self.session.scalar(
                select(Project).where(
                    Project.id == link.project_id,
                    Project.deleted_at.is_(None),
                )
            )
            if project is None:
                raise ValidationAppError(
                    "Source project not found", details={"code": "KNOWLEDGE_SOURCE_UNKNOWN"}
                )
            workspace = await self.session.scalar(
                select(Workspace).where(
                    Workspace.id == project.workspace_id,
                    Workspace.owner_user_id == self.actor.id,
                )
            )
            if workspace is None:
                raise ValidationAppError(
                    "Source project belongs to another owner",
                    details={"code": "KNOWLEDGE_SOURCE_FORBIDDEN"},
                )
            from app.assets.research_models import ResearchResultRevision

            revision = await self.session.scalar(
                select(ResearchResultRevision).where(
                    ResearchResultRevision.id == link.research_revision_id,
                    ResearchResultRevision.project_id == project.id,
                )
            )
            if revision is None:
                raise ValidationAppError(
                    "Source research revision not found in its project",
                    details={"code": "KNOWLEDGE_SOURCE_UNKNOWN"},
                )
            payload.append(
                {
                    "project_id": project.id,
                    "workspace_id": workspace.id,
                    "research_revision_id": revision.id,
                }
            )
        return payload

    def _persist_source_links(
        self, revision: KnowledgeRevision, links: list[dict[str, object]]
    ) -> None:
        for link in links:
            self.session.add(
                KnowledgeSourceLink(
                    project_id=link["project_id"],
                    workspace_id=link["workspace_id"],
                    owner_user_id=self.actor.id,
                    research_revision_id=link["research_revision_id"],
                    knowledge_revision_id=revision.id,
                )
            )

    async def create_entry(
        self,
        *,
        workspace_id: UUID,
        kind: str,
        title: str,
        body: object,
        allowed_uses: list[str],
        public_source_notes: list[PublicSourceNote],
        source_links: list[SourceLinkInput],
        operation: str,
        request_key: str,
    ) -> KnowledgeMutationReceipt:
        if kind not in KNOWLEDGE_KINDS:
            raise ValidationAppError("Unknown knowledge kind")
        if operation not in {"save_draft", "publish"}:
            raise ValidationAppError("Invalid knowledge operation")
        if not 1 <= len(title) <= 240 or not public_text(title):
            raise ValidationAppError("Knowledge title is invalid")
        if not 1 <= len(request_key) <= 160:
            raise ValidationAppError("Invalid knowledge request key")
        await self._workspace(workspace_id)
        canonical = canonical_body(kind, body)
        uses = _validate_uses(allowed_uses)
        notes = _validate_notes(public_source_notes)
        request_hash = _hash(
            [
                "create",
                kind,
                title,
                _request_body(kind, canonical),
                uses,
                notes,
                operation,
                [(str(link.project_id), str(link.research_revision_id)) for link in source_links],
            ]
        )
        replay = await self._replay(request_key, request_hash)
        if replay is not None:
            entry = await self._entry(replay.entry_id)
            return self._receipt(entry, replay)
        await lock_write_scope(self.session, self.actor.id, canonical)
        links = await self._source_links(source_links)
        entry = KnowledgeEntry(
            owner_user_id=self.actor.id,
            workspace_id=workspace_id,
            kind=kind,
            version=1,
            publication_status="draft",
        )
        self.session.add(entry)
        await self.session.flush()
        status = "published" if operation == "publish" else "draft"
        revision = KnowledgeRevision(
            owner_user_id=self.actor.id,
            entry_id=entry.id,
            number=1,
            title=title,
            body=canonical,
            content_hash=content_hash(canonical),
            allowed_uses=uses,
            public_source_notes=notes,
            operation=operation,
            publication_status=status,
            expected_entry_version=1,
            result_entry_version=2,
            request_key=request_key,
            request_hash=request_hash,
        )
        self.session.add(revision)
        await self.session.flush()
        self._persist_source_links(revision, links)
        entry.current_revision_id = revision.id
        entry.version = 2
        entry.publication_status = status
        await self.session.flush()
        await self.session.refresh(entry)
        await self._emit_decision(entry, revision, operation)
        return self._receipt(entry, revision)

    async def append_revision(
        self,
        entry_id: UUID,
        *,
        expected_version: int,
        title: str,
        body: object,
        allowed_uses: list[str],
        public_source_notes: list[PublicSourceNote],
        source_links: list[SourceLinkInput],
        operation: str,
        request_key: str,
    ) -> KnowledgeMutationReceipt:
        if operation not in {"save_draft", "publish"}:
            raise ValidationAppError("Invalid knowledge operation")
        if not 1 <= len(title) <= 240 or not 1 <= len(request_key) <= 160 or not public_text(title):
            raise ValidationAppError("Knowledge title or request key is invalid")
        entry = await self._entry(entry_id)
        canonical = canonical_body(entry.kind, body)
        uses = _validate_uses(allowed_uses)
        notes = _validate_notes(public_source_notes)
        request_hash = _hash(
            [
                "append",
                str(entry_id),
                expected_version,
                title,
                _request_body(entry.kind, canonical),
                uses,
                notes,
                operation,
                [(str(link.project_id), str(link.research_revision_id)) for link in source_links],
            ]
        )
        replay = await self._replay(request_key, request_hash)
        if replay is not None:
            return self._receipt(entry, replay)
        await lock_write_scope(self.session, self.actor.id, canonical, entry_id)
        replay = await self._replay(request_key, request_hash)
        if replay is not None:
            return self._receipt(entry, replay)
        self._require_decision(entry, expected_version=expected_version)
        if entry.publication_status == "published" and operation == "save_draft":
            raise KnowledgeConflictError(
                "KNOWLEDGE_PUBLISHED_REQUIRES_PUBLISH",
                "A published entry only changes through an explicit publish decision",
            )
        links = await self._source_links(source_links)
        status = "published" if operation == "publish" else "draft"
        revision = KnowledgeRevision(
            owner_user_id=self.actor.id,
            entry_id=entry.id,
            number=await self._next_number(entry.id),
            title=title,
            body=canonical,
            content_hash=content_hash(canonical),
            allowed_uses=uses,
            public_source_notes=notes,
            operation=operation,
            publication_status=status,
            expected_entry_version=entry.version,
            result_entry_version=entry.version + 1,
            request_key=request_key,
            request_hash=request_hash,
        )
        self.session.add(revision)
        await self.session.flush()
        self._persist_source_links(revision, links)
        entry.current_revision_id = revision.id
        entry.version = revision.result_entry_version
        entry.publication_status = status
        entry.withdrawn_at = None
        await self.session.flush()
        await self.session.refresh(entry)
        await self._emit_decision(entry, revision, operation)
        return self._receipt(entry, revision)

    async def withdraw(
        self, entry_id: UUID, *, expected_version: int, request_key: str
    ) -> KnowledgeMutationReceipt:
        if not 1 <= len(request_key) <= 160:
            raise ValidationAppError("Invalid knowledge request key")
        entry = await self._entry(entry_id, lock=True)
        current = (
            await self.session.get(KnowledgeRevision, entry.current_revision_id)
            if entry.current_revision_id is not None
            else None
        )
        if current is None:
            raise KnowledgeConflictError(
                "KNOWLEDGE_WITHDRAW_WITHOUT_CONTENT", "Nothing to withdraw"
            )
        request_hash = _hash(["withdraw", str(entry_id), expected_version])
        replay = await self._replay(request_key, request_hash)
        if replay is not None:
            return self._receipt(entry, replay)
        self._require_decision(entry, expected_version=expected_version)
        if entry.publication_status == "withdrawn":
            raise KnowledgeConflictError(
                "KNOWLEDGE_ALREADY_WITHDRAWN", "The entry is already withdrawn"
            )
        shared = (await shared_revisions(self.session, self.actor.id, entry.kind, [current]))[0]
        revision = KnowledgeRevision(
            owner_user_id=self.actor.id,
            entry_id=entry.id,
            number=await self._next_number(entry.id),
            title=shared.title,
            body=shared.body,
            content_hash=content_hash(shared.body),
            allowed_uses=shared.allowed_uses,
            public_source_notes=shared.public_source_notes,
            operation="withdraw",
            publication_status="withdrawn",
            expected_entry_version=entry.version,
            result_entry_version=entry.version + 1,
            request_key=request_key,
            request_hash=request_hash,
        )
        self.session.add(revision)
        await self.session.flush()
        # The withdrawn snapshot keeps the private provenance of the content it copies.
        links = list(
            await self.session.scalars(
                select(KnowledgeSourceLink).where(
                    KnowledgeSourceLink.owner_user_id == self.actor.id,
                    KnowledgeSourceLink.knowledge_revision_id == current.id,
                )
            )
        )
        for link in links:
            self.session.add(
                KnowledgeSourceLink(
                    project_id=link.project_id,
                    workspace_id=link.workspace_id,
                    owner_user_id=self.actor.id,
                    research_revision_id=link.research_revision_id,
                    knowledge_revision_id=revision.id,
                )
            )
        entry.current_revision_id = revision.id
        entry.version = revision.result_entry_version
        entry.publication_status = "withdrawn"
        entry.withdrawn_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(entry)
        await self._emit_decision(entry, revision, "withdraw")
        return self._receipt(entry, revision)

    async def _emit_decision(
        self, entry: KnowledgeEntry, revision: KnowledgeRevision, operation: str
    ) -> None:
        event_type = {
            "save_draft": "knowledge.entry.drafted",
            "publish": "knowledge.entry.published",
            "withdraw": "knowledge.entry.withdrawn",
        }[operation]
        await emit(
            self.session,
            project_id=None,
            aggregate_type="KnowledgeEntry",
            aggregate_id=entry.id,
            event_type=event_type,
            payload={
                "entry_id": str(entry.id),
                "revision_id": str(revision.id),
                "kind": entry.kind,
                "operation": operation,
                "publication_status": entry.publication_status,
                "version": entry.version,
                "content_hash": revision.content_hash,
            },
            actor_id=self.actor.id,
        )

    def _require_decision(self, entry: KnowledgeEntry, *, expected_version: int) -> None:
        if entry.version != expected_version:
            raise KnowledgeConflictError(
                "KNOWLEDGE_STALE_VERSION", "Knowledge entry version changed; reload first"
            )

    def _receipt(
        self, entry: KnowledgeEntry, revision: KnowledgeRevision
    ) -> KnowledgeMutationReceipt:
        return KnowledgeMutationReceipt(
            entry_id=entry.id,
            revision_id=revision.id,
            result_entry_version=revision.result_entry_version,
            publication_status=revision.publication_status,
            content_hash=revision.content_hash,
        )

    async def read_entry(self, entry_id: UUID) -> KnowledgeEntry:
        return await self._entry(entry_id)

    async def read_revision(self, revision_id: UUID) -> KnowledgeRevisionRead:
        revision = await self.session.scalar(
            select(KnowledgeRevision).where(
                KnowledgeRevision.id == revision_id,
                KnowledgeRevision.owner_user_id == self.actor.id,
            )
        )
        if revision is None:
            raise NotFoundError("knowledge revision not found")
        entry = await self._entry(revision.entry_id)
        return (await shared_revisions(self.session, self.actor.id, entry.kind, [revision]))[0]

    async def list_revisions(
        self, entry_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[KnowledgeRevisionRead], int]:
        entry = await self._entry(entry_id)
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid knowledge revision page")
        condition = [
            KnowledgeRevision.owner_user_id == self.actor.id,
            KnowledgeRevision.entry_id == entry_id,
        ]
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(KnowledgeRevision).where(*condition)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(KnowledgeRevision)
                .where(*condition)
                .order_by(KnowledgeRevision.number.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        return await shared_revisions(self.session, self.actor.id, entry.kind, rows), total

    async def list_entries(
        self,
        *,
        kind: str | None = None,
        status: str = "published",
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeEntry], int]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid knowledge page")
        if kind is not None and kind not in KNOWLEDGE_KINDS:
            raise ValidationAppError("Unknown knowledge kind")
        if status not in {"published", "draft", "withdrawn"}:
            raise ValidationAppError("Unknown knowledge status")
        condition = [
            KnowledgeEntry.owner_user_id == self.actor.id,
            KnowledgeEntry.publication_status == status,
        ]
        if kind is not None:
            condition.append(KnowledgeEntry.kind == kind)
        if query:
            if len(query) > 200:
                raise ValidationAppError("Knowledge query is too long")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            candidates = (
                select(KnowledgeEntry, KnowledgeRevision)
                .join(KnowledgeRevision, KnowledgeRevision.id == KnowledgeEntry.current_revision_id)
                .where(*condition, KnowledgeRevision.owner_user_id == self.actor.id)
                .order_by(KnowledgeEntry.created_at.desc(), KnowledgeEntry.id)
            )
            if self.session.get_bind().dialect.name == "postgresql":
                candidates = candidates.where(
                    cast(KnowledgeRevision.search_text, Text).ilike(pattern, escape="\\"),
                )
            # Legacy indexes may contain private text. Only visible projected
            # matches count, including those before or after the requested page.
            rows: list[KnowledgeEntry] = []
            count = 0
            stream = await self.session.stream(candidates.execution_options(yield_per=64))
            async for batch in stream.partitions(64):
                grouped: dict[str, list[KnowledgeRevision]] = defaultdict(list)
                for entry, revision in batch:
                    grouped[entry.kind].append(revision)
                matched: set[UUID] = set()
                for entry_kind, revisions in grouped.items():
                    for shared in await shared_revisions(
                        self.session, self.actor.id, entry_kind, revisions
                    ):
                        if shared.matches(query):
                            matched.add(shared.entry_id)
                for entry, _ in batch:
                    if entry.id in matched:
                        if offset <= count < offset + limit:
                            rows.append(entry)
                        count += 1
            return rows, count
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(KnowledgeEntry).where(*condition)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(KnowledgeEntry)
                .where(*condition)
                .order_by(KnowledgeEntry.created_at, KnowledgeEntry.id)
                .offset(offset)
                .limit(limit)
            )
        )
        return rows, total

    async def source_links(
        self, revision_id: UUID, *, project_id: UUID
    ) -> list[KnowledgeSourceLink]:
        """Private provenance is only readable through the originating project."""
        await self.read_revision(revision_id)
        project = await self.session.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.deleted_at.is_(None),
            )
        )
        if project is None:
            raise NotFoundError("source project not found")
        workspace = await self.session.scalar(
            select(Workspace).where(
                Workspace.id == project.workspace_id,
                Workspace.owner_user_id == self.actor.id,
            )
        )
        if workspace is None:
            raise NotFoundError("source project not found")
        return list(
            await self.session.scalars(
                select(KnowledgeSourceLink).where(
                    KnowledgeSourceLink.owner_user_id == self.actor.id,
                    KnowledgeSourceLink.knowledge_revision_id == revision_id,
                    KnowledgeSourceLink.project_id == project.id,
                )
            )
        )


__all__ = [
    "KnowledgeConflictError",
    "KnowledgeMutationReceipt",
    "KnowledgeService",
    "PublicSourceNote",
    "SourceLinkInput",
    "summary_text",
]
