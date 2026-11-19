"""Research result reads and typed user decisions (I4-02).

Every write is a new immutable revision plus a pointer move; the request key and hash
make retries return the original receipt, and expected version/base checks reject a
stale editor instead of silently overwriting a newer decision. Citations are verified
against real fragments of the same project before they are stored.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Text, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.assets.domain_events import emit
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.research_bodies import claim_keys, content_hash, validate_body
from app.assets.research_models import (
    RESEARCH_KINDS,
    RESEARCH_VERIFICATIONS,
    ResearchCitation,
    ResearchResult,
    ResearchResultRevision,
)
from app.assets.source_models import SourceFragment
from app.shared.errors import AppError, NotFoundError, ValidationAppError


class ResearchConflictError(AppError):
    """Stable 409 for stale/concurrent research decisions."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=409)


@dataclass(frozen=True)
class CitationInput:
    source_fragment_id: UUID
    file_revision_id: UUID
    claim_key: str = "root"
    locator_override: dict[str, object] | None = None
    quoted_text: str = ""


@dataclass(frozen=True)
class ResearchMutationReceipt:
    result_id: UUID
    revision_id: UUID
    result_version: int
    revision_number: int
    origin: str
    content_hash: str


def _request_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _citation_payload(citations: list[CitationInput]) -> list[object]:
    return [
        [
            str(item.source_fragment_id),
            str(item.file_revision_id),
            item.claim_key,
            item.locator_override,
            item.quoted_text,
        ]
        for item in citations
    ]


class ResearchService:
    """Caller owns commit; every public operation rechecks authenticated ownership."""

    def __init__(self, session: AsyncSession, *, actor: User, project_id: UUID) -> None:
        self.session = session
        self.actor = actor
        self.project_id = project_id

    async def _authorize(self) -> None:
        await ProjectService(self.session).get_project_for_owner(
            project_id=self.project_id, actor=self.actor
        )

    async def _lock_project(self) -> None:
        await self.session.scalar(
            select(Project).where(Project.id == self.project_id).with_for_update()
        )

    async def _result(self, result_id: UUID, *, lock: bool = False) -> ResearchResult:
        query = select(ResearchResult).where(
            ResearchResult.id == result_id, ResearchResult.project_id == self.project_id,
        )
        if lock:
            query = query.with_for_update()
        result = await self.session.scalar(query.execution_options(populate_existing=True))
        if result is None:
            raise NotFoundError("research result not found")
        return result

    async def _revision(self, revision_id: UUID) -> ResearchResultRevision:
        revision = await self.session.scalar(
            select(ResearchResultRevision).where(
                ResearchResultRevision.id == revision_id,
                ResearchResultRevision.project_id == self.project_id,
            )
        )
        if revision is None:
            raise NotFoundError("research revision not found")
        return revision

    async def _replay(
        self, request_key: str, request_hash: str
    ) -> ResearchResultRevision | None:
        existing = await self.session.scalar(
            select(ResearchResultRevision).where(
                ResearchResultRevision.project_id == self.project_id,
                ResearchResultRevision.request_key == request_key,
            )
        )
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise ResearchConflictError(
                "RESEARCH_REQUEST_KEY_REUSED",
                "Research request key already used for a different request",
            )
        return existing

    async def _next_number(self, result_id: UUID) -> int:
        current = await self.session.scalar(
            select(func.max(ResearchResultRevision.number)).where(
                ResearchResultRevision.project_id == self.project_id,
                ResearchResultRevision.result_id == result_id,
            )
        )
        return int(current or 0) + 1

    async def _add_citations(
        self,
        revision: ResearchResultRevision,
        citations: list[CitationInput],
        *,
        kind: str,
        body: dict[str, object],
    ) -> None:
        allowed = claim_keys(kind, body)
        seen: set[tuple[str, UUID]] = set()
        for citation in citations:
            key = (citation.claim_key, citation.source_fragment_id)
            if key in seen:
                raise ValidationAppError(
                    "Duplicate citation for the same claim",
                    details={"code": "RESEARCH_CITATION_DUPLICATE"},
                )
            seen.add(key)
            if citation.claim_key not in allowed:
                raise ValidationAppError(
                    "Citation claim does not exist in this body",
                    details={"code": "RESEARCH_CLAIM_UNKNOWN"},
                )
            fragment = await self.session.scalar(
                select(SourceFragment).where(
                    SourceFragment.id == citation.source_fragment_id,
                    SourceFragment.project_id == self.project_id,
                )
            )
            if fragment is None:
                raise ValidationAppError(
                    "Citation source fragment not found",
                    details={"code": "RESEARCH_FRAGMENT_UNKNOWN"},
                )
            if fragment.file_revision_id != citation.file_revision_id:
                raise ValidationAppError(
                    "Citation revision does not match its fragment",
                    details={"code": "RESEARCH_FRAGMENT_REVISION_MISMATCH"},
                )
            if citation.quoted_text and citation.quoted_text not in fragment.text_content:
                raise ValidationAppError(
                    "Quoted text is not verbatim from the source fragment",
                    details={"code": "RESEARCH_QUOTE_NOT_VERBATIM"},
                )
            if citation.locator_override is not None:
                self._validate_locator(fragment, citation.locator_override)
            self.session.add(
                ResearchCitation(
                    project_id=self.project_id,
                    research_revision_id=revision.id,
                    source_fragment_id=citation.source_fragment_id,
                    file_revision_id=citation.file_revision_id,
                    claim_key=citation.claim_key,
                    locator_override=citation.locator_override,
                    quoted_text=citation.quoted_text,
                )
            )

    @staticmethod
    def _validate_locator(fragment: SourceFragment, locator: dict[str, object]) -> None:
        """The override must stay inside the fragment it claims to locate."""
        kind = locator.get("kind")
        if kind != fragment.locator_kind:
            raise ValidationAppError(
                "Locator kind does not match the fragment",
                details={"code": "RESEARCH_LOCATOR_KIND_MISMATCH"},
            )
        length = len(fragment.text_content)
        if kind in {"paragraph", "page_region", "image_region"}:
            start = locator.get("char_start")
            end = locator.get("char_end")
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValidationAppError(
                    "Character range is required", details={"code": "RESEARCH_LOCATOR_INVALID"}
                )
            if start < 0 or end <= start or end > length:
                raise ValidationAppError(
                    "Character range is outside the fragment",
                    details={"code": "RESEARCH_LOCATOR_OUT_OF_RANGE"},
                )
        elif kind == "time_range":
            start_ms = locator.get("start_ms")
            end_ms = locator.get("end_ms")
            if (
                not isinstance(start_ms, int)
                or not isinstance(end_ms, int)
                or start_ms < 0
                or end_ms <= start_ms
            ):
                raise ValidationAppError(
                    "Time range is invalid", details={"code": "RESEARCH_LOCATOR_INVALID"}
                )

    async def _copy_citations(
        self, source_revision: ResearchResultRevision, target: ResearchResultRevision
    ) -> None:
        citations = list(
            await self.session.scalars(
                select(ResearchCitation).where(
                    ResearchCitation.project_id == self.project_id,
                    ResearchCitation.research_revision_id == source_revision.id,
                )
            )
        )
        for citation in citations:
            self.session.add(
                ResearchCitation(
                    project_id=self.project_id,
                    research_revision_id=target.id,
                    source_fragment_id=citation.source_fragment_id,
                    file_revision_id=citation.file_revision_id,
                    claim_key=citation.claim_key,
                    locator_override=citation.locator_override,
                    quoted_text=citation.quoted_text,
                )
            )

    async def create_result(
        self,
        *,
        kind: str,
        body: object,
        verification: str,
        citations: list[CitationInput],
        request_key: str,
    ) -> ResearchMutationReceipt:
        if kind not in RESEARCH_KINDS:
            raise ValidationAppError("Unknown research kind")
        if verification not in RESEARCH_VERIFICATIONS:
            raise ValidationAppError("Unknown verification")
        if len(request_key) < 1 or len(request_key) > 160:
            raise ValidationAppError("Invalid research request key")
        canonical = validate_body(kind, body)
        request_hash = _request_hash(
            ["create", kind, canonical, verification, _citation_payload(citations)]
        )
        await self._authorize()
        await self._lock_project()
        replay = await self._replay(request_key, request_hash)
        if replay is not None:
            result = await self._result(replay.result_id)
            return self._receipt(result, replay)
        result = ResearchResult(
            project_id=self.project_id,
            kind=kind,
            version=1,
            current_revision_id=None,
        )
        self.session.add(result)
        await self.session.flush()
        revision = ResearchResultRevision(
            project_id=self.project_id,
            result_id=result.id,
            number=1,
            origin="user",
            body=canonical,
            content_hash=content_hash(canonical),
            verification=verification,
            base_revision_id=None,
            applied_result_version=2,
            request_key=request_key,
            request_hash=request_hash,
        )
        self.session.add(revision)
        await self.session.flush()
        await self._add_citations(revision, citations, kind=kind, body=canonical)
        result.current_revision_id = revision.id
        result.version += 1
        await self.session.flush()
        await self.session.refresh(result)
        await emit(
            self.session,
            project_id=self.project_id,
            aggregate_type="ResearchResult",
            aggregate_id=result.id,
            event_type="research.result.created",
            payload={
                "result_id": str(result.id),
                "revision_id": str(revision.id),
                "kind": result.kind,
                "version": result.version,
            },
            actor_id=self.actor.id,
        )
        return self._receipt(result, revision)

    async def append_revision(
        self,
        result_id: UUID,
        *,
        expected_version: int,
        base_revision_id: UUID | None,
        body: object,
        verification: str,
        citations: list[CitationInput],
        request_key: str,
    ) -> ResearchMutationReceipt:
        if verification not in RESEARCH_VERIFICATIONS:
            raise ValidationAppError("Unknown verification")
        if len(request_key) < 1 or len(request_key) > 160:
            raise ValidationAppError("Invalid research request key")
        await self._authorize()
        await self._lock_project()
        result = await self._result(result_id, lock=True)
        canonical = validate_body(result.kind, body)
        request_hash = _request_hash(
            ["append", str(result_id), expected_version, str(base_revision_id),
             canonical, verification, _citation_payload(citations)]
        )
        replay = await self._replay(request_key, request_hash)
        if replay is not None:
            return self._receipt(result, replay)
        self._require_editable(result, expected_version=expected_version)
        if result.current_revision_id != base_revision_id:
            raise ResearchConflictError(
                "RESEARCH_STALE_BASE", "The base revision is no longer current"
            )
        revision = ResearchResultRevision(
            project_id=self.project_id,
            result_id=result.id,
            number=await self._next_number(result.id),
            origin="user",
            body=canonical,
            content_hash=content_hash(canonical),
            verification=verification,
            base_revision_id=result.current_revision_id,
            applied_result_version=result.version + 1,
            request_key=request_key,
            request_hash=request_hash,
        )
        self.session.add(revision)
        await self.session.flush()
        await self._add_citations(revision, citations, kind=result.kind, body=canonical)
        result.current_revision_id = revision.id
        result.version += 1
        await self.session.flush()
        await self.session.refresh(result)
        await emit(
            self.session,
            project_id=self.project_id,
            aggregate_type="ResearchResult",
            aggregate_id=result.id,
            event_type="research.result.revised",
            payload={
                "result_id": str(result.id),
                "revision_id": str(revision.id),
                "number": revision.number,
                "origin": revision.origin,
                "version": result.version,
            },
            actor_id=self.actor.id,
        )
        return self._receipt(result, revision)

    async def accept_candidate(
        self,
        result_id: UUID,
        *,
        expected_version: int,
        candidate_revision_id: UUID,
        base_revision_id: UUID | None,
        request_key: str,
    ) -> ResearchMutationReceipt:
        await self._authorize()
        await self._lock_project()
        result = await self._result(result_id, lock=True)
        candidate = await self._revision(candidate_revision_id)
        if candidate.result_id != result.id:
            raise NotFoundError("research revision not found")
        request_hash = _request_hash(
            ["accept", str(result_id), expected_version, str(candidate_revision_id),
             str(base_revision_id)]
        )
        replay = await self._replay(request_key, request_hash)
        if replay is not None:
            return self._receipt(result, replay)
        self._require_editable(result, expected_version=expected_version)
        if result.current_revision_id != base_revision_id:
            raise ResearchConflictError(
                "RESEARCH_STALE_BASE", "The base revision is no longer current"
            )
        if candidate.applied_result_version is not None:
            raise ResearchConflictError(
                "RESEARCH_CANDIDATE_ALREADY_APPLIED",
                "This candidate is already part of an applied decision",
            )
        revision = ResearchResultRevision(
            project_id=self.project_id,
            result_id=result.id,
            number=await self._next_number(result.id),
            origin="accept",
            body=candidate.body,
            content_hash=candidate.content_hash,
            verification=candidate.verification,
            base_revision_id=result.current_revision_id,
            accepts_revision_id=candidate.id,
            applied_result_version=result.version + 1,
            request_key=request_key,
            request_hash=request_hash,
        )
        self.session.add(revision)
        await self.session.flush()
        await self._copy_citations(candidate, revision)
        result.current_revision_id = revision.id
        result.version += 1
        await self.session.flush()
        await self.session.refresh(result)
        await emit(
            self.session,
            project_id=self.project_id,
            aggregate_type="ResearchResult",
            aggregate_id=result.id,
            event_type="research.result.accepted",
            payload={
                "result_id": str(result.id),
                "revision_id": str(revision.id),
                "accepts_revision_id": str(candidate.id),
                "number": revision.number,
                "version": result.version,
            },
            actor_id=self.actor.id,
        )
        return self._receipt(result, revision)

    async def restore(
        self,
        result_id: UUID,
        *,
        expected_version: int,
        restore_revision_id: UUID,
        base_revision_id: UUID | None,
        request_key: str,
    ) -> ResearchMutationReceipt:
        await self._authorize()
        await self._lock_project()
        result = await self._result(result_id, lock=True)
        target = await self._revision(restore_revision_id)
        if target.result_id != result.id:
            raise NotFoundError("research revision not found")
        request_hash = _request_hash(
            ["restore", str(result_id), expected_version, str(restore_revision_id),
             str(base_revision_id)]
        )
        replay = await self._replay(request_key, request_hash)
        if replay is not None:
            return self._receipt(result, replay)
        self._require_editable(result, expected_version=expected_version)
        if result.current_revision_id != base_revision_id:
            raise ResearchConflictError(
                "RESEARCH_STALE_BASE", "The base revision is no longer current"
            )
        revision = ResearchResultRevision(
            project_id=self.project_id,
            result_id=result.id,
            number=await self._next_number(result.id),
            origin="restore",
            body=target.body,
            content_hash=target.content_hash,
            verification=target.verification,
            base_revision_id=result.current_revision_id,
            restores_revision_id=target.id,
            applied_result_version=result.version + 1,
            request_key=request_key,
            request_hash=request_hash,
        )
        self.session.add(revision)
        await self.session.flush()
        await self._copy_citations(target, revision)
        result.current_revision_id = revision.id
        result.version += 1
        await self.session.flush()
        await self.session.refresh(result)
        await emit(
            self.session,
            project_id=self.project_id,
            aggregate_type="ResearchResult",
            aggregate_id=result.id,
            event_type="research.result.restored",
            payload={
                "result_id": str(result.id),
                "revision_id": str(revision.id),
                "restores_revision_id": str(target.id),
                "number": revision.number,
                "version": result.version,
            },
            actor_id=self.actor.id,
        )
        return self._receipt(result, revision)

    async def archive(
        self, result_id: UUID, *, expected_version: int, archived: bool
    ) -> ResearchResult:
        await self._authorize()
        await self._lock_project()
        result = await self._result(result_id, lock=True)
        if result.version != expected_version:
            raise ResearchConflictError(
                "RESEARCH_STALE_VERSION",
                "Research result version changed; reload before deciding",
            )
        if (result.archived_at is not None) == archived:
            return result
        result.archived_at = datetime.now(UTC) if archived else None
        result.version += 1
        await self.session.flush()
        await self.session.refresh(result)
        await emit(
            self.session,
            project_id=self.project_id,
            aggregate_type="ResearchResult",
            aggregate_id=result.id,
            event_type="research.result.archived",
            payload={
                "result_id": str(result.id),
                "archived": archived,
                "version": result.version,
            },
            actor_id=self.actor.id,
        )
        return result

    def _require_editable(self, result: ResearchResult, *, expected_version: int) -> None:
        if result.archived_at is not None:
            raise ResearchConflictError(
                "RESEARCH_RESULT_ARCHIVED", "Archived results do not accept new revisions"
            )
        if result.version != expected_version:
            raise ResearchConflictError(
                "RESEARCH_STALE_VERSION",
                "Research result version changed; reload before deciding",
            )

    def _receipt(
        self, result: ResearchResult, revision: ResearchResultRevision
    ) -> ResearchMutationReceipt:
        return ResearchMutationReceipt(
            result_id=result.id,
            revision_id=revision.id,
            result_version=result.version,
            revision_number=revision.number,
            origin=revision.origin,
            content_hash=revision.content_hash,
        )

    async def list_results(
        self,
        *,
        kind: str | None = None,
        query: str | None = None,
        archived: bool = False,
        view: str = "current",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ResearchResult], int]:
        await self._authorize()
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid research page")
        if view not in {"current", "suggestions"}:
            raise ValidationAppError("Invalid research view")
        if kind is not None and kind not in RESEARCH_KINDS:
            raise ValidationAppError("Unknown research kind")
        condition = [ResearchResult.project_id == self.project_id]
        if kind is not None:
            condition.append(ResearchResult.kind == kind)
        if not archived:
            condition.append(ResearchResult.archived_at.is_(None))
        if view == "current":
            condition.append(ResearchResult.current_revision_id.is_not(None))
        else:
            condition.append(
                exists().where(
                    ResearchResultRevision.project_id == self.project_id,
                    ResearchResultRevision.result_id == ResearchResult.id,
                    ResearchResultRevision.applied_result_version.is_(None),
                )
            )
        if query:
            if len(query) > 200:
                raise ValidationAppError("Research query is too long")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            condition.append(
                exists().where(
                    ResearchResultRevision.project_id == self.project_id,
                    ResearchResultRevision.result_id == ResearchResult.id,
                    ResearchResultRevision.id == ResearchResult.current_revision_id,
                    cast(ResearchResultRevision.body, Text).ilike(pattern, escape="\\"),
                )
            )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ResearchResult).where(*condition)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(ResearchResult)
                .where(*condition)
                .order_by(ResearchResult.created_at, ResearchResult.id)
                .offset(offset)
                .limit(limit)
            )
        )
        return rows, total

    async def list_revisions(
        self, result_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[ResearchResultRevision], int]:
        await self._authorize()
        await self._result(result_id)
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid research revision page")
        condition = [
            ResearchResultRevision.project_id == self.project_id,
            ResearchResultRevision.result_id == result_id,
        ]
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ResearchResultRevision).where(*condition)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(ResearchResultRevision)
                .where(*condition)
                .order_by(ResearchResultRevision.number.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        return rows, total

    async def read_result(self, result_id: UUID) -> ResearchResult:
        await self._authorize()
        return await self._result(result_id)

    async def current_revisions(
        self, ids: set[UUID]
    ) -> dict[UUID, ResearchResultRevision]:
        if not ids:
            return {}
        rows = await self.session.scalars(
            select(ResearchResultRevision).where(
                ResearchResultRevision.project_id == self.project_id,
                ResearchResultRevision.id.in_(ids),
            )
        )
        return {row.id: row for row in rows}

    async def read_revision(self, revision_id: UUID) -> ResearchResultRevision:
        await self._authorize()
        return await self._revision(revision_id)

    async def list_citations(self, revision_id: UUID) -> list[ResearchCitation]:
        await self._authorize()
        await self._revision(revision_id)
        return list(
            await self.session.scalars(
                select(ResearchCitation)
                .where(
                    ResearchCitation.project_id == self.project_id,
                    ResearchCitation.research_revision_id == revision_id,
                )
                .order_by(ResearchCitation.created_at, ResearchCitation.id)
            )
        )

    async def citation_views(
        self, revision_id: UUID
    ) -> list[tuple[ResearchCitation, SourceFragment, bool]]:
        """Citations with their fragment and whether the original is still available."""
        citations = await self.list_citations(revision_id)
        if not citations:
            return []
        fragment_ids = {citation.source_fragment_id for citation in citations}
        fragments = {
            fragment.id: fragment
            for fragment in await self.session.scalars(
                select(SourceFragment).where(
                    SourceFragment.id.in_(fragment_ids),
                    SourceFragment.project_id == self.project_id,
                )
            )
        }
        revision_ids = {fragment.file_revision_id for fragment in fragments.values()}
        availability: dict[UUID, bool] = {}
        if revision_ids:
            rows = await self.session.execute(
                select(ProjectFileRevision.id, ProjectFile.detached_at)
                .join(ProjectFile, ProjectFile.id == ProjectFileRevision.file_id)
                .where(ProjectFileRevision.id.in_(revision_ids))
            )
            availability = {row[0]: row[1] is None for row in rows}
        views: list[tuple[ResearchCitation, SourceFragment, bool]] = []
        for citation in citations:
            fragment = fragments.get(citation.source_fragment_id)
            if fragment is None:
                continue
            views.append(
                (citation, fragment, availability.get(fragment.file_revision_id, False))
            )
        return views


__all__ = [
    "CitationInput",
    "ResearchConflictError",
    "ResearchMutationReceipt",
    "ResearchService",
]
