"""Private research provenance and current permissions for shared knowledge."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.access.models import Project, User, Workspace
from app.assets.knowledge_models import KnowledgeRevision, KnowledgeSourceLink
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.research_analysis_models import ResearchAnalysis, ResearchAnalysisResult
from app.assets.research_models import ResearchCitation, ResearchResultRevision
from app.assets.source_use_models import SourceUseRevision, SourceUseSubject
from app.shared.db import set_rls_context
from app.shared.errors import ValidationAppError


@dataclass(frozen=True, order=True)
class SourceLinkInput:
    project_id: UUID
    research_revision_id: UUID


class KnowledgeSources:
    def __init__(self, session: AsyncSession, actor: User, *, consumer: UUID | None = None):
        self.session = session
        self.actor = actor
        self.consumer = consumer

    @asynccontextmanager
    async def _scope(self, workspace: UUID, project: UUID | None = None) -> AsyncIterator[None]:
        await set_rls_context(
            self.session, user_id=self.actor.id, workspace_id=workspace, project_id=project
        )
        failed_transaction = False
        try:
            yield
        except DBAPIError:
            failed_transaction = True
            raise
        finally:
            # On a database error the transaction is aborted; rollback discards SET LOCAL.
            if self.session.is_active and not failed_transaction:
                await set_rls_context(
                    self.session,
                    user_id=self.actor.id,
                    workspace_id=self.session.info.get("selected_workspace_id"),
                    project_id=self.consumer,
                )

    async def _projects(self, ids: set[UUID] | None) -> dict[UUID, UUID]:
        """Discover only verified Owner projects, including archived origins of frozen links."""
        scopes: dict[UUID, UUID] = {}
        workspaces = await self.session.scalars(
            select(Workspace.id).where(Workspace.owner_user_id == self.actor.id)
        )
        for workspace in workspaces:
            async with self._scope(workspace):
                q = select(Project.id).where(Project.workspace_id == workspace)
                if ids is not None:
                    q = q.where(Project.id.in_(ids))
                for project in await self.session.scalars(q):
                    scopes[project] = workspace
        return scopes

    async def stored(self, revisions: set[UUID]) -> dict[UUID, set[SourceLinkInput]]:
        """One discovery pass per page. An empty result in consumer RLS alone proves nothing."""
        result: dict[UUID, set[SourceLinkInput]] = {revision: set() for revision in revisions}
        if revisions:
            # Older writers did not carry provenance into every superseding revision.
            # Recover recorded sources up to each immutable snapshot, never from later ones.
            previous = aliased(KnowledgeRevision)
            q = (
                select(KnowledgeRevision.id, KnowledgeSourceLink.research_revision_id)
                .join(
                    previous,
                    (previous.entry_id == KnowledgeRevision.entry_id)
                    & (previous.number <= KnowledgeRevision.number),
                )
                .join(KnowledgeSourceLink, KnowledgeSourceLink.knowledge_revision_id == previous.id)
                .where(
                    KnowledgeRevision.id.in_(revisions),
                    KnowledgeRevision.owner_user_id == self.actor.id,
                    KnowledgeSourceLink.owner_user_id == self.actor.id,
                )
                .distinct()
            )
            for project, workspace in (await self._projects(None)).items():
                async with self._scope(workspace, project):
                    rows = await self.session.execute(
                        q.where(KnowledgeSourceLink.project_id == project)
                    )
                    for knowledge, research in rows:
                        result[knowledge].add(SourceLinkInput(project, research))
        return result

    async def _permitted(
        self, project: UUID, research: set[UUID], uses: set[str], *, lock: bool
    ) -> bool:
        revision = ResearchResultRevision
        # A restore/accept copies a specific snapshot. A user correction descends from
        # its base, including any machine-source provenance that has no verbatim quote.
        origins = (
            select(revision.id.label("id"))
            .where(revision.project_id == project, revision.id.in_(research))
            .cte(recursive=True)
        )
        parent = func.coalesce(
            revision.restores_revision_id, revision.accepts_revision_id, revision.base_revision_id
        )
        origins = origins.union(
            select(parent)
            .join(origins, revision.id == origins.c.id)
            .where(revision.project_id == project, parent.is_not(None))
        )
        files = (
            select(ResearchCitation.file_revision_id)
            .where(
                ResearchCitation.project_id == project,
                ResearchCitation.research_revision_id.in_(select(origins.c.id)),
            )
            .union(
                select(ResearchAnalysis.file_revision_id)
                .join(
                    ResearchAnalysisResult,
                    ResearchAnalysis.id == ResearchAnalysisResult.analysis_id,
                )
                .where(
                    ResearchAnalysis.project_id == project,
                    ResearchAnalysisResult.project_id == project,
                    ResearchAnalysisResult.research_revision_id.in_(select(origins.c.id)),
                )
            )
        )
        ids = set(await self.session.scalars(files))
        if not ids:
            return True
        q = (
            select(
                ProjectFileRevision.id,
                ProjectFile.detached_at,
                SourceUseRevision.state,
                SourceUseRevision.allowed_uses,
            )
            .join(ProjectFile, ProjectFile.id == ProjectFileRevision.file_id)
            .join(SourceUseSubject, SourceUseSubject.file_revision_id == ProjectFileRevision.id)
            .join(SourceUseRevision, SourceUseRevision.id == SourceUseSubject.current_revision_id)
            .where(
                ProjectFileRevision.project_id == project,
                ProjectFile.project_id == project,
                SourceUseSubject.project_id == project,
                SourceUseRevision.project_id == project,
                SourceUseRevision.subject_id == SourceUseSubject.id,
                ProjectFileRevision.id.in_(ids),
            )
            .order_by(ProjectFile.id)
        )
        if lock:
            q = q.with_for_update(read=True, of=ProjectFile)
        rows = (await self.session.execute(q)).all()
        return {r[0] for r in rows} == ids and all(
            detached is None and state == "declared" and uses.issubset(allowed)
            for _, detached, state, allowed in rows
        )

    async def resolve(
        self,
        links: Iterable[SourceLinkInput],
        *,
        uses: set[str] | None,
        lock: bool,
        explicit: Iterable[SourceLinkInput] = (),
    ) -> dict[UUID, UUID]:
        grouped: dict[UUID, set[UUID]] = defaultdict(set)
        for link in links:
            grouped[link.project_id].add(link.research_revision_id)
        if not grouped:
            return {}
        scopes = await self._projects(set(grouped))
        if scopes.keys() != grouped.keys():
            raise ValidationAppError(
                "来源项目不可用", details={"code": "KNOWLEDGE_SOURCE_FORBIDDEN"}
            )
        explicit_projects = {link.project_id for link in explicit}
        for project, ids in sorted(grouped.items()):
            async with self._scope(scopes[project], project):
                q = select(Project.id).where(
                    Project.id == project, Project.workspace_id == scopes[project]
                )
                if project in explicit_projects:
                    q = q.where(Project.deleted_at.is_(None))
                if lock:
                    q = q.with_for_update(read=True)
                if (
                    await self.session.scalar(q) is None
                    or set(
                        await self.session.scalars(
                            select(ResearchResultRevision.id).where(
                                ResearchResultRevision.id.in_(ids),
                                ResearchResultRevision.project_id == project,
                            )
                        )
                    )
                    != ids
                ):
                    raise ValidationAppError(
                        "研究来源不可用", details={"code": "KNOWLEDGE_SOURCE_UNKNOWN"}
                    )
                if uses is not None and not await self._permitted(project, ids, uses, lock=lock):
                    raise ValidationAppError(
                        "研究来源未允许本次用途",
                        details={"code": "KNOWLEDGE_SOURCE_USE_RESTRICTED"},
                    )
        return scopes

    async def persist(
        self, revision_id: UUID, links: set[SourceLinkInput], scopes: dict[UUID, UUID]
    ) -> None:
        for project, workspace in scopes.items():
            async with self._scope(workspace, project):
                self.session.add_all(
                    [
                        KnowledgeSourceLink(
                            project_id=project,
                            workspace_id=workspace,
                            owner_user_id=self.actor.id,
                            knowledge_revision_id=revision_id,
                            research_revision_id=link.research_revision_id,
                        )
                        for link in links
                        if link.project_id == project
                    ]
                )
                await self.session.flush()
