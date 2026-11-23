"""Current source permission revisions for an authorized project research snapshot."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.research_analysis_models import ResearchAnalysis, ResearchAnalysisResult
from app.assets.research_models import ResearchCitation, ResearchResultRevision
from app.assets.source_use_models import SourceUseRevision, SourceUseSubject


async def research_source_permissions(
    session: AsyncSession, project: UUID, research: set[UUID], uses: set[str], *, lock: bool
) -> dict[str, str] | None:
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
    ids = set(await session.scalars(files))
    if not ids:
        return {}
    q = (
        select(
            ProjectFileRevision.id,
            ProjectFile.detached_at,
            SourceUseRevision.id,
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
    rows = (await session.execute(q)).all()
    if {r[0] for r in rows} != ids or any(
        detached is not None or state != "declared" or not uses.issubset(allowed)
        for _, detached, _, state, allowed in rows
    ):
        return None
    return {str(file_id): str(declaration) for file_id, _, declaration, _, _ in rows}
