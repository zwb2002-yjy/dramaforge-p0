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
from app.assets.project_files import ProjectFileService
from app.assets.source_parser import MAX_SOURCE_BYTES
from app.shared.errors import AppError
from app.storage.minio_store import get_object_store

router = APIRouter(tags=["project-files"], dependencies=[Depends(require_selected_workspace)])


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
    source_available: bool
    created_at: datetime


class SourceExcerptsRead(BaseModel):
    source: ProjectFileRead
    parser_version: str | None
    excerpts: list[dict[str, object]]
    total: int
    next_offset: int | None


class SourceRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)


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
        source_available=item.detached_at is None,
        created_at=revision.created_at,
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
    "/projects/{project_id}/file-revisions/{revision_id}", response_model=SourceExcerptsRead
)
async def read_source_revision(
    project_id: UUID,
    revision_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> SourceExcerptsRead:
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    item, revision = await service.read_revision(revision_id)
    total = len(revision.excerpts)
    return SourceExcerptsRead(
        source=_read(item, revision),
        parser_version=revision.parser_version,
        excerpts=revision.excerpts[offset : offset + limit],
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
    "/projects/{project_id}/file-revisions/{revision_id}/retry", response_model=ProjectFileRead
)
async def retry_source(
    project_id: UUID,
    revision_id: UUID,
    body: SourceRetry,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProjectFileRead:
    service = ProjectFileService(
        session, store=get_object_store(), actor=user, project_id=project_id
    )
    revision = await service.retry_extraction(revision_id, request_key=body.request_key)
    item, _revision = await service.read_revision(revision_id)
    await session.commit()
    return _read(item, revision)


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
