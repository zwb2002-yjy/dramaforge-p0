"""Authenticated research result reads and typed user decisions (I4-02)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.research import (
    CitationInput,
    ResearchMutationReceipt,
    ResearchService,
)
from app.assets.research_analysis import (
    AnalysisPreview,
    ResearchAnalysisService,
    TargetResult,
)
from app.assets.research_analysis_models import ResearchAnalysis, ResearchAnalysisResult
from app.assets.research_bodies import content_hash, summary_text
from app.assets.research_models import (
    ResearchResult,
    ResearchResultRevision,
)
from app.director.research_import import ResearchAcceptance
from app.director.text_transport import research_model_identity, resolve_agent_text_model
from app.shared.errors import AppError

router = APIRouter(tags=["research"], dependencies=[Depends(require_selected_workspace)])


class CitationRead(BaseModel):
    id: UUID
    source_fragment_id: UUID
    file_revision_id: UUID
    claim_key: str
    locator_override: dict[str, object] | None
    quoted_text: str
    source_available: bool
    extraction_method: str
    limitations: list[str] = Field(default_factory=list)


class CitationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_fragment_id: UUID
    file_revision_id: UUID
    claim_key: str = Field(default="root", max_length=120)
    locator_override: dict[str, object] | None = None
    quoted_text: str = Field(default="", max_length=20_000)


class RevisionSummary(BaseModel):
    id: UUID
    number: int
    origin: str
    verification: str
    content_hash: str
    summary: str
    created_at: datetime


class ResearchResultRead(BaseModel):
    id: UUID
    project_id: UUID
    kind: str
    version: int
    archived_at: datetime | None
    current_revision_id: UUID | None
    current: RevisionSummary | None


class ResearchRevisionRead(RevisionSummary):
    result_id: UUID
    body: dict[str, object]
    base_revision_id: UUID | None
    restores_revision_id: UUID | None
    accepts_revision_id: UUID | None
    applied_result_version: int | None
    citations: list[CitationRead]


class ResearchResultPage(BaseModel):
    items: list[ResearchResultRead]
    total: int
    next_offset: int | None


class RevisionPage(BaseModel):
    items: list[RevisionSummary]
    total: int
    next_offset: int | None


class ResearchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    kind: str
    body: dict[str, object]
    verification: str = "unverified"
    citations: list[CitationWrite] = Field(default_factory=list)


class ResearchVersioned(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)
    base_revision_id: UUID | None = None
    body: dict[str, object]
    verification: str = "unverified"
    citations: list[CitationWrite] = Field(default_factory=list)


class ResearchAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)
    base_revision_id: UUID | None = None
    candidate_revision_id: UUID


class ResearchRestore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)
    base_revision_id: UUID | None = None
    restore_revision_id: UUID


class ResearchArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    archived: bool


class ResearchReceiptRead(BaseModel):
    result_id: UUID
    revision_id: UUID
    result_version: int
    revision_number: int
    origin: str
    content_hash: str


def _service(session: AsyncSession, user: CurrentUser, project_id: UUID) -> ResearchService:
    return ResearchService(session, actor=user, project_id=project_id)


def _summary(revision: ResearchResultRevision, kind: str) -> RevisionSummary:
    return RevisionSummary(
        id=revision.id,
        number=revision.number,
        origin=revision.origin,
        verification=revision.verification,
        content_hash=revision.content_hash,
        summary=summary_text(kind, revision.body),
        created_at=revision.created_at,
    )


def _result_read(
    result: ResearchResult, current: ResearchResultRevision | None
) -> ResearchResultRead:
    return ResearchResultRead(
        id=result.id,
        project_id=result.project_id,
        kind=result.kind,
        version=result.version,
        archived_at=result.archived_at,
        current_revision_id=result.current_revision_id,
        current=_summary(current, result.kind) if current is not None else None,
    )


def _receipt(receipt: ResearchMutationReceipt) -> ResearchReceiptRead:
    return ResearchReceiptRead(
        result_id=receipt.result_id,
        revision_id=receipt.revision_id,
        result_version=receipt.result_version,
        revision_number=receipt.revision_number,
        origin=receipt.origin,
        content_hash=receipt.content_hash,
    )


def _citations(items: list[CitationWrite]) -> list[CitationInput]:
    return [
        CitationInput(
            source_fragment_id=item.source_fragment_id,
            file_revision_id=item.file_revision_id,
            claim_key=item.claim_key,
            locator_override=item.locator_override,
            quoted_text=item.quoted_text,
        )
        for item in items
    ]


@router.get("/projects/{project_id}/research-results", response_model=ResearchResultPage)
async def list_research_results(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    kind: str | None = Query(default=None, max_length=24),
    q: str | None = Query(default=None, max_length=200),
    archived: bool = False,
    view: str = Query(default="current", max_length=16),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ResearchResultPage:
    service = _service(session, user, project_id)
    rows, total = await service.list_results(
        kind=kind, query=q, archived=archived, view=view, limit=limit, offset=offset
    )
    currents = await service.current_revisions(
        {row.current_revision_id for row in rows if row.current_revision_id is not None}
    )
    return ResearchResultPage(
        items=[
            _result_read(
                row, currents.get(row.current_revision_id) if row.current_revision_id else None
            )
            for row in rows
        ],
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.post(
    "/projects/{project_id}/research-results",
    response_model=ResearchReceiptRead,
    status_code=201,
)
async def create_research_result(
    project_id: UUID,
    body: ResearchCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ResearchReceiptRead:
    service = _service(session, user, project_id)
    receipt = await service.create_result(
        kind=body.kind,
        body=body.body,
        verification=body.verification,
        citations=_citations(body.citations),
        request_key=body.request_key,
    )
    await session.commit()
    return _receipt(receipt)


@router.get(
    "/projects/{project_id}/research-results/{result_id}", response_model=ResearchResultRead
)
async def read_research_result(
    project_id: UUID, result_id: UUID, user: CurrentUser, session: SessionDep
) -> ResearchResultRead:
    service = _service(session, user, project_id)
    result = await service.read_result(result_id)
    current = (
        await service.read_revision(result.current_revision_id)
        if result.current_revision_id is not None
        else None
    )
    return _result_read(result, current)


@router.get(
    "/projects/{project_id}/research-results/{result_id}/revisions",
    response_model=RevisionPage,
)
async def list_research_revisions(
    project_id: UUID,
    result_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> RevisionPage:
    service = _service(session, user, project_id)
    result = await service.read_result(result_id)
    revisions, total = await service.list_revisions(result_id, limit=limit, offset=offset)
    return RevisionPage(
        items=[_summary(item, result.kind) for item in revisions],
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.get(
    "/projects/{project_id}/research-revisions/{revision_id}",
    response_model=ResearchRevisionRead,
)
async def read_research_revision(
    project_id: UUID, revision_id: UUID, user: CurrentUser, session: SessionDep
) -> ResearchRevisionRead:
    service = _service(session, user, project_id)
    revision = await service.read_revision(revision_id)
    result = await service.read_result(revision.result_id)
    views = await service.citation_views(revision_id)
    return ResearchRevisionRead(
        **_summary(revision, result.kind).model_dump(),
        result_id=revision.result_id,
        body=revision.body,
        base_revision_id=revision.base_revision_id,
        restores_revision_id=revision.restores_revision_id,
        accepts_revision_id=revision.accepts_revision_id,
        applied_result_version=revision.applied_result_version,
        citations=[
            CitationRead(
                id=citation.id,
                source_fragment_id=citation.source_fragment_id,
                file_revision_id=citation.file_revision_id,
                claim_key=citation.claim_key,
                locator_override=citation.locator_override,
                quoted_text=citation.quoted_text,
                source_available=available,
                extraction_method=fragment.extraction_method,
                limitations=[],
            )
            for citation, fragment, available in views
        ],
    )


@router.post(
    "/projects/{project_id}/research-results/{result_id}/revisions",
    response_model=ResearchReceiptRead,
    status_code=201,
)
async def append_research_revision(
    project_id: UUID,
    result_id: UUID,
    body: ResearchVersioned,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ResearchReceiptRead:
    service = _service(session, user, project_id)
    receipt = await service.append_revision(
        result_id,
        expected_version=body.expected_version,
        base_revision_id=body.base_revision_id,
        body=body.body,
        verification=body.verification,
        citations=_citations(body.citations),
        request_key=body.request_key,
    )
    await session.commit()
    return _receipt(receipt)


@router.post(
    "/projects/{project_id}/research-results/{result_id}/accept",
    response_model=ResearchReceiptRead,
    status_code=201,
)
async def accept_research_candidate(
    project_id: UUID,
    result_id: UUID,
    body: ResearchAccept,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ResearchReceiptRead:
    service = _service(session, user, project_id)
    receipt = await service.accept_candidate(
        result_id,
        expected_version=body.expected_version,
        candidate_revision_id=body.candidate_revision_id,
        base_revision_id=body.base_revision_id,
        request_key=body.request_key,
    )
    await session.commit()
    return _receipt(receipt)


@router.post(
    "/projects/{project_id}/research-results/{result_id}/restore",
    response_model=ResearchReceiptRead,
    status_code=201,
)
async def restore_research_revision(
    project_id: UUID,
    result_id: UUID,
    body: ResearchRestore,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ResearchReceiptRead:
    service = _service(session, user, project_id)
    receipt = await service.restore(
        result_id,
        expected_version=body.expected_version,
        restore_revision_id=body.restore_revision_id,
        base_revision_id=body.base_revision_id,
        request_key=body.request_key,
    )
    await session.commit()
    return _receipt(receipt)


@router.patch(
    "/projects/{project_id}/research-results/{result_id}",
    response_model=ResearchResultRead,
)
async def archive_research_result(
    project_id: UUID,
    result_id: UUID,
    body: ResearchArchive,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ResearchResultRead:
    service = _service(session, user, project_id)
    result = await service.archive(
        result_id, expected_version=body.expected_version, archived=body.archived
    )
    current = (
        await service.read_revision(result.current_revision_id)
        if result.current_revision_id is not None
        else None
    )
    await session.commit()
    return _result_read(result, current)


class TargetResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: UUID
    base_revision_id: UUID | None = None


class AnalysisPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_extraction_id: UUID
    expected_file_version: int = Field(ge=1)
    category_set: list[str] = Field(default_factory=list, max_length=6)
    target_results: list[TargetResultInput] = Field(default_factory=list, max_length=100)
    requested_text_model_id: str | None = Field(default=None, max_length=200)


class AnalysisPreviewRead(BaseModel):
    preview_fingerprint: str
    source_revision_id: UUID
    source_extraction_id: UUID
    input_versions: dict[str, object]
    model_identity: dict[str, object] | None
    source_use_summary: dict[str, object]
    max_model_calls: int
    missing_categories: list[str]
    blockers: list[str]
    expires_at: datetime


async def _model_identity(
    session: AsyncSession, project: Project
) -> tuple[dict[str, object] | None, str | None]:
    """Read-only model identity for the preview; never a model call."""
    try:
        resolved = await resolve_agent_text_model(session, project=project)
        return await research_model_identity(
            session, project.workspace_id, resolved.resolution
        ), None
    except AppError:
        return None, "text_model_unavailable"


@router.post(
    "/projects/{project_id}/file-revisions/{revision_id}/analysis-preview",
    response_model=AnalysisPreviewRead,
)
async def preview_research_analysis(
    project_id: UUID,
    revision_id: UUID,
    body: AnalysisPreviewInput,
    user: CurrentUser,
    session: SessionDep,
) -> AnalysisPreviewRead:
    """Zero model calls, zero writes: freeze what an accepted analysis would read."""
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    identity, blocker = await _model_identity(session, project)
    service = ResearchAnalysisService(session, actor=user, project_id=project_id)
    preview = await service.preview(
        revision_id,
        source_extraction_id=body.source_extraction_id,
        expected_file_version=body.expected_file_version,
        category_set=body.category_set,
        target_results=[
            TargetResult(result_id=item.result_id, base_revision_id=item.base_revision_id)
            for item in body.target_results
        ],
        model_identity=identity,
        model_blocker=blocker,
        requested_text_model_id=body.requested_text_model_id,
    )
    return AnalysisPreviewRead(
        preview_fingerprint=preview.preview_fingerprint,
        source_revision_id=preview.source_revision_id,
        source_extraction_id=preview.source_extraction_id,
        input_versions=preview.input_versions,
        model_identity=preview.model_identity,
        source_use_summary=preview.source_use_summary,
        max_model_calls=preview.max_model_calls,
        missing_categories=preview.missing_categories,
        blockers=preview.blockers,
        expires_at=preview.expires_at,
    )


class AnalysisSummary(BaseModel):
    id: UUID
    file_revision_id: UUID
    source_extraction_id: UUID
    coverage: dict[str, object]
    category_outcomes: dict[str, object]
    manifest_hash: str
    completed_at: datetime


class AnalysisResultRead(BaseModel):
    result_id: UUID
    revision_id: UUID
    category: str
    disposition: str


class AnalysisDetail(AnalysisSummary):
    results: list[AnalysisResultRead]


class AnalysisPage(BaseModel):
    items: list[AnalysisSummary]
    total: int
    next_offset: int | None


class AnalysisResultPage(BaseModel):
    items: list[AnalysisResultRead]
    total: int
    next_offset: int | None


def _analysis_summary(analysis: ResearchAnalysis) -> AnalysisSummary:
    return AnalysisSummary(
        id=analysis.id,
        file_revision_id=analysis.file_revision_id,
        source_extraction_id=analysis.source_extraction_id,
        coverage=analysis.coverage,
        category_outcomes=analysis.category_outcomes,
        manifest_hash=analysis.manifest_hash,
        completed_at=analysis.completed_at,
    )


def _analysis_result(
    link: ResearchAnalysisResult,
    revision: ResearchResultRevision,
    is_current: bool,
) -> AnalysisResultRead:
    return AnalysisResultRead(
        result_id=revision.result_id,
        revision_id=revision.id,
        category=link.category,
        disposition="current" if is_current else "candidate",
    )


@router.get(
    "/projects/{project_id}/file-revisions/{revision_id}/analyses",
    response_model=AnalysisPage,
)
async def list_research_analyses(
    project_id: UUID,
    revision_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AnalysisPage:
    service = ResearchAnalysisService(session, actor=user, project_id=project_id)
    rows, total = await service.list_analyses(revision_id, limit=limit, offset=offset)
    return AnalysisPage(
        items=[_analysis_summary(row) for row in rows],
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.get(
    "/projects/{project_id}/analyses/{analysis_id}",
    response_model=AnalysisDetail,
)
async def read_research_analysis(
    project_id: UUID,
    analysis_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> AnalysisDetail:
    service = ResearchAnalysisService(session, actor=user, project_id=project_id)
    analysis = await service.read_analysis(analysis_id)
    rows, _total = await service.list_analysis_results(analysis_id, limit=100)
    summary = _analysis_summary(analysis)
    return AnalysisDetail(
        **summary.model_dump(),
        results=[_analysis_result(*row) for row in rows],
    )


@router.get(
    "/projects/{project_id}/analyses/{analysis_id}/results",
    response_model=AnalysisResultPage,
)
async def list_research_analysis_results(
    project_id: UUID,
    analysis_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AnalysisResultPage:
    service = ResearchAnalysisService(session, actor=user, project_id=project_id)
    rows, total = await service.list_analysis_results(analysis_id, limit=limit, offset=offset)
    return AnalysisResultPage(
        items=[_analysis_result(*row) for row in rows],
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


class AnalysisAcceptanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    preview: AnalysisPreviewInput
    preview_fingerprint: str = Field(min_length=64, max_length=64)


class ResearchAcceptanceRead(BaseModel):
    master_run_id: UUID | None
    flow_instance_id: UUID | None
    turn_id: UUID
    accepted_revision: str
    read_url: str


def _frozen_list(preview: AnalysisPreview, key: str) -> list[object]:
    value = preview.input_versions.get(key)
    return list(value) if isinstance(value, list) else []


@router.post(
    "/projects/{project_id}/file-revisions/{revision_id}/analyses",
    response_model=ResearchAcceptanceRead,
    status_code=202,
)
async def accept_research_analysis(
    project_id: UUID,
    revision_id: UUID,
    body: AnalysisAcceptanceInput,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ResearchAcceptanceRead:
    """Accept one frozen analysis request as a queued Director Turn (no model call)."""
    from app.director.research_import import ResearchImportService, ResearchRequest

    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    await session.scalar(select(Project.id).where(Project.id == project.id).with_for_update())
    request_key = body.request_key.strip()
    if not request_key:
        raise AppError(
            code="DIRECTOR_REQUEST_KEY_INVALID", message="研究请求键不能为空", status_code=422
        )
    decision_hash = content_hash(
        {
            "revision_id": str(revision_id),
            **body.model_dump(mode="json", exclude={"request_key"}),
        }
    )
    importer = ResearchImportService(session)
    existing = await importer.receipt_for_decision(
        project_id=project_id,
        revision_id=revision_id,
        request_key=request_key,
        decision_hash=decision_hash,
    )
    if existing is not None:
        return _acceptance_read(project_id, revision_id, existing)
    identity, blocker = await _model_identity(session, project)
    service = ResearchAnalysisService(session, actor=user, project_id=project_id)
    preview = await service.preview(
        revision_id,
        source_extraction_id=body.preview.source_extraction_id,
        expected_file_version=body.preview.expected_file_version,
        category_set=body.preview.category_set,
        target_results=[
            TargetResult(result_id=item.result_id, base_revision_id=item.base_revision_id)
            for item in body.preview.target_results
        ],
        model_identity=identity,
        model_blocker=blocker,
        requested_text_model_id=body.preview.requested_text_model_id,
    )
    if preview.preview_fingerprint != body.preview_fingerprint:
        raise AppError(
            code="RESEARCH_PREVIEW_DRIFT",
            message="The preview input changed; refresh the preview before accepting",
            status_code=409,
        )
    if preview.blockers:
        raise AppError(
            code="RESEARCH_BLOCKED",
            message="The analysis request is blocked",
            status_code=409,
            details={"blockers": preview.blockers},
        )
    categories = [str(value) for value in _frozen_list(preview, "category_set")]
    targets = [
        dict(value) for value in _frozen_list(preview, "target_results") if isinstance(value, dict)
    ]
    acceptance = await importer.accept(
        project=project,
        actor=user,
        request=ResearchRequest(
            file_revision_id=revision_id,
            source_extraction_id=preview.source_extraction_id,
            categories=categories,
            targets=targets,
            model_identity=preview.model_identity or {},
            preview_fingerprint=preview.preview_fingerprint,
            decision_hash=decision_hash,
            request_key=request_key,
        ),
    )
    await session.commit()
    return _acceptance_read(project_id, revision_id, acceptance)


def _acceptance_read(
    project_id: UUID, revision_id: UUID, acceptance: ResearchAcceptance
) -> ResearchAcceptanceRead:
    return ResearchAcceptanceRead(
        master_run_id=None,
        flow_instance_id=None,
        turn_id=acceptance.turn_id,
        accepted_revision=acceptance.accepted_revision,
        read_url=(
            f"/api/v1/projects/{project_id}/file-revisions/{revision_id}/analyses"
        ),
    )
