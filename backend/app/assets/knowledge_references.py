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

    async def availability(self, reference: ProjectKnowledgeReference) -> str:
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
        current = await self._current(entry)
        if current is None:
            return "unavailable"
        if reference.allowed_use not in {str(value) for value in current.allowed_uses}:
            return "restricted"
        return "published"

    async def _read(self, reference: ProjectKnowledgeReference) -> ReferenceRead:
        return ReferenceRead(
            id=reference.id,
            project_id=reference.project_id,
            knowledge_entry_id=reference.knowledge_entry_id,
            knowledge_revision_id=reference.knowledge_revision_id,
            allowed_use=reference.allowed_use,
            version=reference.version,
            detached_at=reference.detached_at,
            availability=await self.availability(reference),
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
        if entry.publication_status != "published":
            raise KnowledgeReferenceConflictError(
                "KNOWLEDGE_NOT_PUBLISHED", "Only published knowledge can be referenced"
            )
        if allowed_use not in {str(value) for value in revision.allowed_uses}:
            raise KnowledgeReferenceConflictError(
                "KNOWLEDGE_USE_NOT_ALLOWED", "This revision does not allow that use"
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
                .order_by(
                    ProjectKnowledgeReference.created_at, ProjectKnowledgeReference.id
                )
                .offset(offset)
                .limit(limit)
            )
        )
        return [await self._read(row) for row in rows], total

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
            current = await self._current(entry)
            if entry.publication_status != "published" or current is None:
                raise KnowledgeReferenceConflictError(
                    "KNOWLEDGE_NOT_PUBLISHED", "Only published knowledge can be referenced"
                )
            if reference.allowed_use not in {str(value) for value in current.allowed_uses}:
                raise KnowledgeReferenceConflictError(
                    "KNOWLEDGE_USE_NOT_ALLOWED", "This knowledge no longer allows that use"
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
