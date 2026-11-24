"""Authenticated project source upload, version reads and per-file recovery."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.project_files import ExtractionAcceptance, ProjectFileService
from app.assets.source_models import SourceExtraction
from app.assets.source_parser import MAX_SOURCE_BYTES, source_capabilities
from app.shared.errors import AppError
from app.storage.minio_store import get_object_store

router = APIRouter(tags=["project-files"], dependencies=[Depends(require_selected_workspace)])


class SourceCapabilityFormat(BaseModel):
    format: str
    extensions: list[str]
    available: bool
    max_bytes: int
    max_duration_ms: int | None
    max_pixels: int | None
    supported_processing: list[str]
    limitations: list[str]


class SourceCapabilitiesRead(BaseModel):
    profile_revision: str
    formats: list[SourceCapabilityFormat]
    components: dict[str, bool]
    auto_analysis: dict[str, object]


class ExtractionSummary(BaseModel):
    id: UUID
    file_revision_id: UUID
    attempt: int
    parser_key: str
    parser_version: str
    extraction_schema_version: int
    content_hash: str
    coverage: dict[str, object]
    completed_at: datetime


class ExtractionRead(ExtractionSummary):
    processor_evidence: dict[str, object]


class SourceFragmentRead(BaseModel):
    id: UUID
    extraction_id: UUID
    file_revision_id: UUID
    ordinal: int
    locator_kind: str
    locator: dict[str, object]
    extraction_schema_version: int
    text_content: str
    content_hash: str
    extraction_method: str
    processor_ref: str
    evidence_meta: dict[str, object]
    source_available: bool
    limitations: list[str] = Field(default_factory=list)


class SourceFragmentPage(BaseModel):
    items: list[SourceFragmentRead]
    total: int
    next_offset: int | None


class ProjectFileRead(BaseModel):
    id: UUID
    project_id: UUID
    filename: str
    version: int
    content_version: int
    revision_id: UUID
    revision_number: int
    content_hash: str
    byte_size: int
    status: str
    attempt: int
    error_code: str | None
    current_extraction_id: UUID | None
    source_available: bool
    created_at: datetime


class SourceRevisionRead(BaseModel):
    source: ProjectFileRead
    extraction: ExtractionSummary | None
    source_available: bool


class SourceRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    expected_file_version: int = Field(ge=1)
    expected_attempt: int = Field(ge=1)
    expected_extraction_id: UUID | None = None
    processor_profile_revision: str = Field(min_length=64, max_length=64)


class ExtractionAcceptanceRead(BaseModel):
    file_revision_id: UUID
    accepted_attempt: int
    event_id: UUID
    processor_profile_revision: str
    action: str


def _acceptance(acceptance: ExtractionAcceptance) -> ExtractionAcceptanceRead:
    return ExtractionAcceptanceRead(
        file_revision_id=acceptance.file_revision_id,
        accepted_attempt=acceptance.accepted_attempt,
        event_id=acceptance.event_id,
        processor_profile_revision=acceptance.processor_profile_revision,
        action=acceptance.action,
    )


def _summary(extraction: SourceExtraction) -> ExtractionSummary:
    return ExtractionSummary(
        id=extraction.id,
        file_revision_id=extraction.file_revision_id,
        attempt=extraction.attempt,
        parser_key=extraction.parser_key,
        parser_version=extraction.parser_version,
        extraction_schema_version=extraction.extraction_schema_version,
        content_hash=extraction.content_hash,
        coverage=extraction.coverage,
        completed_at=extraction.completed_at,
    )


def _read(item: ProjectFile, revision: ProjectFileRevision) -> ProjectFileRead:
    return ProjectFileRead(
        id=item.id,
        project_id=item.project_id,
        filename=revision.filename,
        version=item.version,
        content_version=item.content_version,
        revision_id=revision.id,
        revision_number=revision.number,
        content_hash=revision.content_hash,
        byte_size=revision.byte_size,
        status=revision.status,
        attempt=revision.attempt,
        error_code=revision.error_code,
        current_extraction_id=revision.current_extraction_id,
        source_available=item.detached_at is None,
        created_at=revision.created_at,
    )



@router.get(
    "/projects/{project_id}/source-capabilities", response_model=SourceCapabilitiesRead
)
async def read_source_capabilities(
    project_id: UUID, user: CurrentUser, session: SessionDep
) -> SourceCapabilitiesRead:
    """Read-only capability answer; zero parsing and zero model calls."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    payload = source_capabilities()
    return SourceCapabilitiesRead(
        profile_revision=payload["profile_revision"],
        formats=[SourceCapabilityFormat.model_validate(item) for item in payload["formats"]],
        components=payload["components"],
        auto_analysis=payload["auto_analysis"],
    )


@router.post(
    "/projects/{project_id}/files",
    response_model=ProjectFileRead,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def upload_source(
    project_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
    filename: str = Query(min_length=1, max_length=260),
    request_key: str = Query(min_length=1, max_length=160),
    file_id: UUID | None = None,
    expected_version: int | None = Query(default=None, ge=1),
) -> ProjectFileRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_SOURCE_BYTES:
            raise AppError(
                code="SOURCE_TOO_LARGE", message="Source exceeds upload limit", status_code=413
            )
        data.extend(chunk)
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    revision = await service.upload(
        filename=filename,
        data=bytes(data),
        mime_type=request.headers.get("content-type", "application/octet-stream"),
        request_key=request_key,
        file_id=file_id,
        expected_version=expected_version,
    )
    item, _revision = await service.read_revision(revision.id)
    await session.commit()
    return _read(item, revision)


@router.get("/projects/{project_id}/files", response_model=list[ProjectFileRead])
async def list_sources(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectFileRead]:
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    items = await service.list_files(limit=limit, offset=offset)
    return [_read(*await service.read_current(item.id)) for item in items]


@router.get("/projects/{project_id}/files/{file_id}", response_model=ProjectFileRead)
async def read_source(
    project_id: UUID, file_id: UUID, user: CurrentUser, session: SessionDep
) -> ProjectFileRead:
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    return _read(*await service.read_current(file_id))


@router.get(
    "/projects/{project_id}/file-revisions/{revision_id}", response_model=SourceRevisionRead
)
async def read_source_revision(
    project_id: UUID,
    revision_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> SourceRevisionRead:
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    item, revision = await service.read_revision(revision_id)
    extraction = (
        await service.read_extraction(revision.current_extraction_id)
        if revision.current_extraction_id is not None
        else None
    )
    return SourceRevisionRead(
        source=_read(item, revision),
        extraction=_summary(extraction) if extraction is not None else None,
        source_available=item.detached_at is None,
    )


@router.get(
    "/projects/{project_id}/extractions/{extraction_id}", response_model=ExtractionRead
)
async def read_extraction(
    project_id: UUID, extraction_id: UUID, user: CurrentUser, session: SessionDep
) -> ExtractionRead:
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    extraction = await service.read_extraction(extraction_id)
    return ExtractionRead(
        **_summary(extraction).model_dump(),
        processor_evidence=extraction.processor_evidence,
    )


@router.get(
    "/projects/{project_id}/extractions/{extraction_id}/fragments",
    response_model=SourceFragmentPage,
)
async def list_fragments(
    project_id: UUID,
    extraction_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    locator_kind: str | None = Query(default=None, max_length=24),
) -> SourceFragmentPage:
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    # Authorizes the project and rejects extractions of another project.
    extraction = await service.read_extraction(extraction_id)
    fragments, total = await service.list_fragments(
        extraction_id, limit=limit, offset=offset, locator_kind=locator_kind
    )
    return SourceFragmentPage(
        items=[
            SourceFragmentRead(
                id=fragment.id,
                extraction_id=fragment.extraction_id,
                file_revision_id=fragment.file_revision_id,
                ordinal=fragment.ordinal,
                locator_kind=fragment.locator_kind,
                locator=fragment.locator,
                extraction_schema_version=extraction.extraction_schema_version,
                text_content=fragment.text_content,
                content_hash=fragment.content_hash,
                extraction_method=fragment.extraction_method,
                processor_ref=fragment.processor_ref,
                evidence_meta=fragment.evidence_meta,
                source_available=True,
                limitations=fragment.limitations,
            )
            for fragment in fragments
        ],
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )



@router.get("/projects/{project_id}/file-revisions/{revision_id}/original")
async def download_source(
    project_id: UUID, revision_id: UUID, user: CurrentUser, session: SessionDep
) -> Response:
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    revision, data = await service.original(revision_id)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(revision.filename, safe='')}"
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/projects/{project_id}/file-revisions/{revision_id}/retry",
    response_model=ExtractionAcceptanceRead,
    status_code=202,
)
async def retry_source(
    project_id: UUID,
    revision_id: UUID,
    body: SourceRetry,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ExtractionAcceptanceRead:
    """Accept one retry of a failed local extraction under a frozen profile."""
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    acceptance = await service.accept_extraction(
        revision_id,
        action="retry",
        request_key=body.request_key,
        expected_file_version=body.expected_file_version,
        expected_attempt=body.expected_attempt,
        expected_extraction_id=body.expected_extraction_id,
        processor_profile_revision=body.processor_profile_revision,
    )
    await session.commit()
    return _acceptance(acceptance)


@router.post(
    "/projects/{project_id}/file-revisions/{revision_id}/reparse",
    response_model=ExtractionAcceptanceRead,
    status_code=202,
)
async def reparse_source(
    project_id: UUID,
    revision_id: UUID,
    body: SourceRetry,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ExtractionAcceptanceRead:
    """Accept one explicit re-identification of an already parsed source."""
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    acceptance = await service.accept_extraction(
        revision_id,
        action="reparse",
        request_key=body.request_key,
        expected_file_version=body.expected_file_version,
        expected_attempt=body.expected_attempt,
        expected_extraction_id=body.expected_extraction_id,
        processor_profile_revision=body.processor_profile_revision,
    )
    await session.commit()
    return _acceptance(acceptance)


@router.delete("/projects/{project_id}/files/{file_id}", response_model=ProjectFileRead)
async def unlink_source(
    project_id: UUID,
    file_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
    expected_version: int = Query(ge=1),
) -> ProjectFileRead:
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    item = await service.unlink(file_id, expected_version=expected_version)
    _item, revision = await service.read_current(file_id)
    await session.commit()
    return _read(item, revision)
