"""Project fixed references to published knowledge revisions (I4-03).

A reference pins one published revision and one allowed use; later knowledge revisions
never move an existing reference. Detach/reattach is an explicit CAS decision, and
reattach re-checks the current publication status and allowed uses. Availability is a
read projection of the entry's current facts, never a stored second state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.assets.domain_events import emit
from app.assets.knowledge_models import (
    KnowledgeEntry,
    KnowledgeRevision,
    ProjectKnowledgeReference,
)
from app.assets.knowledge_public import shared_revisions
from app.assets.knowledge_sources import KnowledgeSources, SourceLinkInput
from app.assets.source_use_models import USE_PURPOSES
from app.shared.errors import AppError, NotFoundError, ValidationAppError


class KnowledgeReferenceConflictError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=409)


@dataclass(frozen=True)
class ReferenceRead:
    id: UUID
    project_id: UUID
    knowledge_entry_id: UUID
    knowledge_revision_id: UUID
    allowed_use: str
    version: int
    detached_at: datetime | None
    availability: str


class KnowledgeReferenceService:
    """Caller owns commit; every operation re-checks project ownership and RLS scope."""

    def __init__(self, session: AsyncSession, *, actor: User, project_id: UUID) -> None:
        self.session = session
        self.actor = actor
        self.project_id = project_id
        self.sources = KnowledgeSources(session, actor, consumer=project_id)

    async def _project(self) -> Project:
        return await ProjectService(self.session).get_project_for_owner(
            project_id=self.project_id, actor=self.actor
        )

    async def _entry(self, entry_id: UUID) -> KnowledgeEntry:
        entry = await self.session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.id == entry_id,
                KnowledgeEntry.owner_user_id == self.actor.id,
            )
        )
        if entry is None:
            raise NotFoundError("knowledge entry not found")
        return entry

    async def _revision(self, entry_id: UUID, revision_id: UUID) -> KnowledgeRevision:
        revision = await self.session.scalar(
            select(KnowledgeRevision).where(
                KnowledgeRevision.id == revision_id,
                KnowledgeRevision.entry_id == entry_id,
                KnowledgeRevision.owner_user_id == self.actor.id,
            )
        )
        if revision is None:
            raise NotFoundError("knowledge revision not found")
        return revision

    async def _current(self, entry: KnowledgeEntry) -> KnowledgeRevision | None:
        if entry.current_revision_id is None:
            return None
        return await self.session.get(KnowledgeRevision, entry.current_revision_id)

    async def _usable(
        self,
        entry: KnowledgeEntry,
        pinned: KnowledgeRevision,
        allowed_use: str,
        *,
        lock: bool = False,
        known: dict[UUID, set[SourceLinkInput]] | None = None,
        grant_revisions: dict[str, str] | None = None,
        additional_uses: tuple[str, ...] = (),
    ) -> bool:
        current = await self._current(entry)
        if current is None or entry.publication_status != "published":
            return False
        rows = [pinned] if pinned.id == current.id else [pinned, current]
        required_uses = {allowed_use, *additional_uses}
        if any(
            row.publication_status != "published" or not required_uses.issubset(row.allowed_uses)
            for row in rows
        ):
            return False
        views = await shared_revisions(self.session, self.actor.id, entry.kind, rows)
        if any(view.shared_content_state != "complete" for view in views):
            return False
        revision_ids = {row.id for row in rows}
        if known is None or not revision_ids <= known.keys():
            known = await self.sources.stored(revision_ids)
        links = {link for row in rows for link in known.get(row.id, set())}
        try:
            await self.sources.resolve(
                links, uses=required_uses, lock=lock, grant_revisions=grant_revisions
            )
        except ValidationAppError:
            return False
        if lock:
            # Take the entry lock after source locks, matching publication order.
            head = await self.session.execute(
                select(KnowledgeEntry.current_revision_id, KnowledgeEntry.publication_status)
                .where(KnowledgeEntry.id == entry.id, KnowledgeEntry.owner_user_id == self.actor.id)
                .with_for_update(read=True)
            )
            return head.one_or_none() == (current.id, "published")
        return True

    async def discussion_snapshot(
        self, reference_id: UUID, revision_id: UUID, content_hash: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        ref = await self.session.scalar(
            select(ProjectKnowledgeReference)
            .where(
                ProjectKnowledgeReference.id == reference_id,
                ProjectKnowledgeReference.project_id == self.project_id,
                ProjectKnowledgeReference.owner_user_id == self.actor.id,
                ProjectKnowledgeReference.detached_at.is_(None),
                ProjectKnowledgeReference.allowed_use == "external_processing",
                ProjectKnowledgeReference.knowledge_revision_id == revision_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if ref is None:
            raise ValidationAppError(
                "请先在当前项目固定可用于外部模型处理的知识引用",
                details={"code": "KNOWLEDGE_CONTEXT_UNAVAILABLE"},
            )
        entry = await self._entry(ref.knowledge_entry_id)
        pinned = await self._revision(entry.id, revision_id)
        grants: dict[str, str] = {}
        if pinned.content_hash != content_hash or not await self._usable(
            entry,
            pinned,
            ref.allowed_use,
            lock=True,
            grant_revisions=grants,
            additional_uses=("research",),
        ):
            raise ValidationAppError(
                "知识版本、使用许可或来源已改变", details={"code": "KNOWLEDGE_CONTEXT_STALE"}
            )
        public = (await shared_revisions(self.session, self.actor.id, entry.kind, [pinned]))[0]
        if public.shared_content_state != "complete":
            raise ValidationAppError(
                "该知识的公开内容需要核对", details={"code": "KNOWLEDGE_CONTEXT_STALE"}
            )
        return (
            {
                "link_version": ref.version,
                "entry_version": entry.version,
                "head": str(entry.current_revision_id),
                "source_grants": grants,
            },
            public.body,
        )

    async def availability(
        self,
        reference: ProjectKnowledgeReference,
        *,
        known: dict[UUID, set[SourceLinkInput]] | None = None,
    ) -> str:
        entry = await self.session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.id == reference.knowledge_entry_id,
                KnowledgeEntry.owner_user_id == self.actor.id,
            )
        )
        if entry is None:
            return "unavailable"
        if entry.publication_status == "withdrawn":
            return "withdrawn"
        if entry.current_revision_id is None:
            return "unavailable"
        pinned = await self._revision(entry.id, reference.knowledge_revision_id)
        return (
            "published"
            if await self._usable(entry, pinned, reference.allowed_use, known=known)
            else "restricted"
        )

    async def _read(
        self,
        reference: ProjectKnowledgeReference,
        *,
        known: dict[UUID, set[SourceLinkInput]] | None = None,
    ) -> ReferenceRead:
        return ReferenceRead(
            id=reference.id,
            project_id=reference.project_id,
            knowledge_entry_id=reference.knowledge_entry_id,
            knowledge_revision_id=reference.knowledge_revision_id,
            allowed_use=reference.allowed_use,
            version=reference.version,
            detached_at=reference.detached_at,
            availability=await self.availability(reference, known=known),
        )

    async def create(
        self,
        *,
        knowledge_entry_id: UUID,
        knowledge_revision_id: UUID,
        allowed_use: str,
    ) -> tuple[ReferenceRead, bool]:
        if allowed_use not in USE_PURPOSES:
            raise ValidationAppError(
                "Unsupported knowledge use", details={"code": "KNOWLEDGE_USE_INVALID"}
            )
        project = await self._project()
        entry = await self._entry(knowledge_entry_id)
        revision = await self._revision(entry.id, knowledge_revision_id)
        existing = await self.session.scalar(
            select(ProjectKnowledgeReference).where(
                ProjectKnowledgeReference.project_id == project.id,
                ProjectKnowledgeReference.knowledge_revision_id == revision.id,
                ProjectKnowledgeReference.allowed_use == allowed_use,
            )
        )
        if existing is not None:
            # A detached natural key stays detached; reattaching is an explicit PATCH.
            return await self._read(existing), False
        if entry.publication_status != "published" or revision.publication_status != "published":
            raise KnowledgeReferenceConflictError(
                "KNOWLEDGE_NOT_PUBLISHED", "Only published knowledge can be referenced"
            )
        if not await self._usable(entry, revision, allowed_use, lock=True):
            raise KnowledgeReferenceConflictError(
                "KNOWLEDGE_USE_NOT_ALLOWED", "This knowledge revision is restricted for that use"
            )
        row = ProjectKnowledgeReference(
            project_id=project.id,
            workspace_id=project.workspace_id,
            owner_user_id=self.actor.id,
            knowledge_entry_id=entry.id,
            knowledge_revision_id=revision.id,
            allowed_use=allowed_use,
            version=1,
        )
        self.session.add(row)
        await self.session.flush()
        await self._emit(project, row, "knowledge.reference.attached")
        return await self._read(row), True

    async def list(
        self, *, active: bool = True, limit: int = 50, offset: int = 0
    ) -> tuple[list[ReferenceRead], int]:
        project = await self._project()
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid reference page")
        condition = [ProjectKnowledgeReference.project_id == project.id]
        if active:
            condition.append(ProjectKnowledgeReference.detached_at.is_(None))
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ProjectKnowledgeReference).where(*condition)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(ProjectKnowledgeReference)
                .where(*condition)
                .order_by(ProjectKnowledgeReference.created_at, ProjectKnowledgeReference.id)
                .offset(offset)
                .limit(limit)
            )
        )
        revisions = {row.knowledge_revision_id for row in rows}
        heads = await self.session.scalars(
            select(KnowledgeEntry.current_revision_id).where(
                KnowledgeEntry.id.in_({row.knowledge_entry_id for row in rows}),
                KnowledgeEntry.owner_user_id == self.actor.id,
            )
        )
        revisions.update(head for head in heads if head is not None)
        known = await self.sources.stored(revisions)
        return [await self._read(row, known=known) for row in rows], total

    async def _emit(
        self,
        project: Project,
        reference: ProjectKnowledgeReference,
        event_type: str,
    ) -> None:
        await emit(
            self.session,
            project_id=project.id,
            aggregate_type="ProjectKnowledgeReference",
            aggregate_id=reference.id,
            event_type=event_type,
            payload={
                "reference_id": str(reference.id),
                "knowledge_entry_id": str(reference.knowledge_entry_id),
                "knowledge_revision_id": str(reference.knowledge_revision_id),
                "allowed_use": reference.allowed_use,
                "version": reference.version,
                "detached": reference.detached_at is not None,
            },
            actor_id=self.actor.id,
        )

    async def patch(
        self, reference_id: UUID, *, expected_version: int, attached: bool
    ) -> ReferenceRead:
        project = await self._project()
        reference = await self.session.scalar(
            select(ProjectKnowledgeReference)
            .where(
                ProjectKnowledgeReference.id == reference_id,
                ProjectKnowledgeReference.project_id == project.id,
            )
            .with_for_update()
        )
        if reference is None:
            raise NotFoundError("knowledge reference not found")
        if reference.version != expected_version:
            raise KnowledgeReferenceConflictError(
                "KNOWLEDGE_REFERENCE_STALE_VERSION",
                "Reference version changed; reload before deciding",
            )
        if attached:
            entry = await self._entry(reference.knowledge_entry_id)
            if entry.publication_status != "published" or entry.current_revision_id is None:
                raise KnowledgeReferenceConflictError(
                    "KNOWLEDGE_NOT_PUBLISHED", "Only published knowledge can be referenced"
                )
            pinned = await self._revision(entry.id, reference.knowledge_revision_id)
            if not await self._usable(entry, pinned, reference.allowed_use, lock=True):
                raise KnowledgeReferenceConflictError(
                    "KNOWLEDGE_USE_NOT_ALLOWED",
                    "This knowledge revision is restricted for that use",
                )
            reference.detached_at = None
        else:
            reference.detached_at = datetime.now(UTC)
        reference.version += 1
        await self.session.flush()
        await self._emit(
            project,
            reference,
            "knowledge.reference.attached" if attached else "knowledge.reference.detached",
        )
        return await self._read(reference)


__all__ = [
    "KnowledgeReferenceConflictError",
    "KnowledgeReferenceService",
    "ReferenceRead",
]
