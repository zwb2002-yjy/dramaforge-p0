"""Public asset library reads and project fixed links (I5-01)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.public_assets import (
    ProjectPublicAssetLinkService,
    ProjectPublicLinkRead,
    PublicAssetRead,
    PublicAssetService,
    PublicContent,
    PublicItemSummary,
)

router = APIRouter(tags=["public-assets"], dependencies=[Depends(require_selected_workspace)])


class PublicItemRead(BaseModel):
    id: UUID
    media_kind: str
    role: str
    mime_type: str | None
    width: int | None
    height: int | None
    duration_ms: int | None
    preview_available: bool


class PublicAssetReadModel(BaseModel):
    id: UUID
    kind: str
    safe_name: str
    safe_description: str
    style_labels: list[str]
    publication_hash: str
    revision: int
    status: str
    usable: bool
    reason_codes: list[str]
    items: list[PublicItemRead]
    created_at: datetime


class PublicAssetPage(BaseModel):
    items: list[PublicAssetReadModel]
    total: int
    next_offset: int | None


class PublicItemPage(BaseModel):
    items: list[PublicItemRead]
    total: int
    next_offset: int | None


class PublicAssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    withdrawn: bool


class PublicLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    publication_id: UUID
    local_label: str = Field(default="", max_length=160)


class PublicLinkPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    local_label: str | None = Field(default=None, max_length=160)
    attached: bool | None = None


class PublicLinkReadModel(BaseModel):
    id: UUID
    project_id: UUID
    publication_id: UUID
    local_label: str
    version: int
    detached_at: datetime | None
    availability: str


class PublicLinkPage(BaseModel):
    items: list[PublicLinkReadModel]
    total: int
    next_offset: int | None


def _item_read(item: PublicItemSummary) -> PublicItemRead:
    return PublicItemRead(
        id=item.id,
        media_kind=item.media_kind,
        role=item.role,
        mime_type=item.mime_type,
        width=item.width,
        height=item.height,
        duration_ms=item.duration_ms,
        preview_available=item.preview_available,
    )


def _asset_read(value: PublicAssetRead) -> PublicAssetReadModel:
    return PublicAssetReadModel(
        id=value.id,
        kind=value.kind,
        safe_name=value.safe_name,
        safe_description=value.safe_description,
        style_labels=value.style_labels,
        publication_hash=value.publication_hash,
        revision=value.revision,
        status=value.status,
        usable=value.usable,
        reason_codes=value.reason_codes,
        items=[_item_read(item) for item in value.items],
        created_at=value.created_at,
    )


def _link_read(value: ProjectPublicLinkRead) -> PublicLinkReadModel:
    return PublicLinkReadModel(
        id=value.id,
        project_id=value.project_id,
        publication_id=value.publication_id,
        local_label=value.local_label,
        version=value.version,
        detached_at=value.detached_at,
        availability=value.availability,
    )


@router.get("/public-assets", response_model=PublicAssetPage)
async def list_public_assets(
    user: CurrentUser,
    session: SessionDep,
    q: str | None = Query(default=None, max_length=200),
    kind: str | None = Query(default=None, max_length=40),
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PublicAssetPage:
    rows, total = await PublicAssetService(session, actor=user).list(
        query=q, kind=kind, status=status, limit=limit, offset=offset
    )
    return PublicAssetPage(
        items=[_asset_read(row) for row in rows],
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.get("/public-assets/{publication_id}", response_model=PublicAssetReadModel)
async def read_public_asset(
    publication_id: UUID, user: CurrentUser, session: SessionDep
) -> PublicAssetReadModel:
    return _asset_read(await PublicAssetService(session, actor=user).read(publication_id))


@router.get("/public-assets/{publication_id}/items", response_model=PublicItemPage)
async def list_public_asset_items(
    publication_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PublicItemPage:
    service = PublicAssetService(session, actor=user)
    value = await service.read(publication_id)
    items = value.items[offset : offset + limit]
    return PublicItemPage(
        items=[_item_read(item) for item in items],
        total=len(value.items),
        next_offset=offset + limit if offset + limit < len(value.items) else None,
    )


@router.patch("/public-assets/{publication_id}", response_model=PublicAssetReadModel)
async def patch_public_asset(
    publication_id: UUID,
    body: PublicAssetPatch,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> PublicAssetReadModel:
    value = await PublicAssetService(session, actor=user).set_withdrawn(
        publication_id, expected_revision=body.expected_revision, withdrawn=body.withdrawn
    )
    await session.commit()
    return _asset_read(value)


@router.get("/projects/{project_id}/public-asset-links", response_model=PublicLinkPage)
async def list_public_links(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    active: bool = True,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PublicLinkPage:
    rows, total = await ProjectPublicAssetLinkService(
        session, actor=user, project_id=project_id
    ).list(active=active, limit=limit, offset=offset)
    return PublicLinkPage(
        items=[_link_read(row) for row in rows],
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.post(
    "/projects/{project_id}/public-asset-links",
    response_model=PublicLinkReadModel,
    status_code=201,
)
async def create_public_link(
    project_id: UUID,
    body: PublicLinkCreate,
    user: CurrentUser,
    session: SessionDep,
    response: Response,
    _: CsrfDep,
) -> PublicLinkReadModel:
    link, created = await ProjectPublicAssetLinkService(
        session, actor=user, project_id=project_id
    ).create(
        publication_id=body.publication_id,
        local_label=body.local_label,
        request_key=body.request_key,
    )
    await session.commit()
    if not created:
        response.status_code = 200
    return _link_read(link)


@router.patch(
    "/projects/{project_id}/public-asset-links/{link_id}",
    response_model=PublicLinkReadModel,
)
async def patch_public_link(
    project_id: UUID,
    link_id: UUID,
    body: PublicLinkPatch,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> PublicLinkReadModel:
    value = await ProjectPublicAssetLinkService(session, actor=user, project_id=project_id).patch(
        link_id,
        expected_version=body.expected_version,
        local_label=body.local_label,
        attached=body.attached,
    )
    await session.commit()
    return _link_read(value)


async def _content_response(request: Request, content: PublicContent) -> Response:
    from app.api.content_streaming import content_response

    return await content_response(
        request,
        object_key=content.object_key,
        mime_type=content.mime_type,
        byte_size=content.byte_size,
    )


def _content_headers(content: PublicContent) -> dict[str, str]:
    return {
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Content-Length": str(content.byte_size),
        "Content-Type": content.mime_type,
    }


@router.get("/public-assets/{publication_id}/items/{item_id}/content")
async def read_public_content(
    publication_id: UUID,
    item_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    content = await PublicAssetService(session, actor=user).read_content(publication_id, item_id)
    return await _content_response(request, content)


@router.head("/public-assets/{publication_id}/items/{item_id}/content")
async def head_public_content(
    publication_id: UUID,
    item_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    content = await PublicAssetService(session, actor=user).read_content(publication_id, item_id)
    return Response(status_code=200, headers=_content_headers(content))


@router.get("/projects/{project_id}/public-asset-links/{link_id}/items/{item_id}/content")
async def read_project_public_content(
    project_id: UUID,
    link_id: UUID,
    item_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    content = await ProjectPublicAssetLinkService(
        session, actor=user, project_id=project_id
    ).read_content(link_id, item_id)
    return await _content_response(request, content)


@router.head("/projects/{project_id}/public-asset-links/{link_id}/items/{item_id}/content")
async def head_project_public_content(
    project_id: UUID,
    link_id: UUID,
    item_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    content = await ProjectPublicAssetLinkService(
        session, actor=user, project_id=project_id
    ).read_content(link_id, item_id)
    headers = _content_headers(content)
    headers["ETag"] = f'"{content.content_hash}"'
    return Response(status_code=200, headers=headers)
