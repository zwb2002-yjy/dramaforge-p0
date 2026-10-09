"""Professional project asset-card and version API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.asset_card_service import AssetCardReadService
from app.assets.from_artifact_service import (
    AssetFromArtifactRequest,
    AssetFromArtifactService,
)
from app.assets.models import (
    Asset,
    AssetTag,
    AssetTagLink,
    AssetVersion,
)
from app.assets.tag_service import AssetTagService
from app.assets.version_service import AssetVersionService
from app.shared.errors import ConflictError, NotFoundError

router = APIRouter(tags=["assets"], dependencies=[Depends(require_selected_workspace)])


class AssetCreateBody(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=12000)
    metadata: dict[str, object] = Field(default_factory=dict)
    status: Literal["draft", "active", "recycled"] = "active"
    tags: list[str] = Field(default_factory=list, max_length=40)


class AssetUpdateBody(AssetCreateBody):
    expected_version: int = Field(ge=1)


class AssetRead(BaseModel):
    id: UUID
    project_id: UUID
    kind: str
    name: str
    description: str
    metadata: dict[str, object]
    status: str
    tags: list[str]
    version: int
    created_at: datetime
    updated_at: datetime


class AssetVersionRead(BaseModel):
    id: UUID
    asset_id: UUID
    version_number: int
    kind: str
    name: str
    description: str
    metadata: dict[str, object]
    status: str
    created_by: UUID
    created_at: datetime


def _asset_read(asset: Asset, *, tags: list[str] | None = None) -> AssetRead:
    return AssetRead(
        id=asset.id,
        project_id=asset.project_id,
        kind=asset.kind,
        name=asset.name,
        description=asset.description,
        metadata=dict(asset.metadata_json),
        status=asset.status,
        tags=list(tags or []),
        version=asset.version,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


async def _asset_tag_names(session: SessionDep, asset_id: UUID) -> list[str]:
    rows = (
        await session.execute(
            select(AssetTag.name)
            .join(AssetTagLink, AssetTagLink.tag_id == AssetTag.id)
            .where(AssetTagLink.asset_id == asset_id)
            .order_by(AssetTag.normalized_name)
        )
    ).scalars()
    return list(rows)


def _version_read(version: AssetVersion) -> AssetVersionRead:
    return AssetVersionRead(
        id=version.id,
        asset_id=version.asset_id,
        version_number=version.version_number,
        kind=version.kind,
        name=version.name,
        description=version.description,
        metadata=dict(version.metadata_json),
        status=version.status,
        created_by=version.created_by,
        created_at=version.created_at,
    )


@router.get("/projects/{project_id}/assets", response_model=list[AssetRead])
async def list_project_assets(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    kind: str | None = None,
    status: str | None = None,
    name: str | None = None,
    tags: str | None = None,
) -> list[AssetRead]:
    tag_list = [item.strip() for item in tags.split(",") if item.strip()] if tags else None
    rows = await AssetTagService(session).list_assets(
        project_id=project_id,
        actor=user,
        kind=kind,
        status=status,
        name=name,
        tags=tag_list,
    )
    asset_ids = [row.id for row in rows]
    tag_rows = (
        await session.execute(
            select(AssetTagLink.asset_id, AssetTag.name)
            .join(AssetTag, AssetTag.id == AssetTagLink.tag_id)
            .where(AssetTagLink.asset_id.in_(asset_ids))
            .order_by(AssetTag.normalized_name)
        )
    ).all() if asset_ids else []
    tags_by_asset: dict[UUID, list[str]] = {asset_id: [] for asset_id in asset_ids}
    for asset_id, tag_name in tag_rows:
        tags_by_asset[asset_id].append(tag_name)
    return [_asset_read(row, tags=tags_by_asset[row.id]) for row in rows]


@router.post("/projects/{project_id}/assets", response_model=AssetRead, status_code=201)
async def create_project_asset(
    project_id: UUID,
    body: AssetCreateBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AssetRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    asset = Asset(
        project_id=project_id,
        kind=body.kind,
        name=body.name,
        description=body.description,
        metadata_json=dict(body.metadata),
        status=body.status,
        version=1,
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project_id,
        asset_id=asset.id,
        version_number=1,
        kind=body.kind,
        name=body.name,
        description=body.description,
        metadata_json=dict(body.metadata),
        status="formal",
        created_by=user.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    tags = await AssetTagService(session).set_asset_tags(
        project_id=project_id,
        asset_id=asset.id,
        actor=user,
        names=list(body.tags),
    )
    await session.commit()
    return _asset_read(asset, tags=[tag.name for tag in tags])


@router.patch("/projects/{project_id}/assets/{asset_id}", response_model=AssetRead)
async def update_project_asset(
    project_id: UUID,
    asset_id: UUID,
    body: AssetUpdateBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AssetRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    asset = (
        await session.execute(
            select(Asset)
            .where(Asset.id == asset_id, Asset.project_id == project_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if asset is None:
        raise NotFoundError("asset not found")
    if asset.version != body.expected_version:
        raise ConflictError(
            "asset version conflict",
            details={"expected_version": body.expected_version, "actual_version": asset.version},
        )
    next_version = asset.version + 1
    asset.kind = body.kind
    asset.name = body.name
    asset.description = body.description
    asset.metadata_json = dict(body.metadata)
    asset.status = body.status
    asset.version = next_version
    current_formals = (
        await session.execute(
            select(AssetVersion)
            .where(
                AssetVersion.project_id == project_id,
                AssetVersion.asset_id == asset.id,
                AssetVersion.status == "formal",
            )
            .with_for_update()
        )
    ).scalars().all()
    for current in current_formals:
        current.status = "historical"
    version = AssetVersion(
        project_id=project_id,
        asset_id=asset.id,
        version_number=next_version,
        kind=body.kind,
        name=body.name,
        description=body.description,
        metadata_json=dict(body.metadata),
        status="formal",
        created_by=user.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    tags = await AssetTagService(session).set_asset_tags(
        project_id=project_id,
        asset_id=asset.id,
        actor=user,
        names=list(body.tags),
    )
    await session.commit()
    return _asset_read(asset, tags=[tag.name for tag in tags])


@router.get(
    "/projects/{project_id}/assets/{asset_id}/versions",
    response_model=list[AssetVersionRead],
)
async def list_asset_versions(
    project_id: UUID,
    asset_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[AssetVersionRead]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    asset_exists = (
        await session.execute(
            select(Asset.id).where(Asset.id == asset_id, Asset.project_id == project_id)
        )
    ).scalar_one_or_none()
    if asset_exists is None:
        raise NotFoundError("asset not found")
    rows = (
        (
            await session.execute(
                select(AssetVersion)
                .where(AssetVersion.project_id == project_id, AssetVersion.asset_id == asset_id)
                .order_by(AssetVersion.version_number.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_version_read(row) for row in rows]


class AssetTagRead(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    normalized_name: str


class AssetTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class AssetTagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=40)


class AssetCardRead(BaseModel):
    asset_id: UUID
    project_id: UUID
    kind: str
    name: str
    description: str
    status: str
    version: int
    metadata: dict[str, object]
    current_version_id: UUID | None
    current_version_number: int | None
    current_version_status: str | None
    references: list[dict[str, object]]
    missing_reference_roles: list[str]


class AssetCandidateBody(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=12000)
    metadata: dict[str, object] = Field(default_factory=dict)


class AssetFromArtifactBody(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    artifact_id: UUID
    description: str = Field(default="", max_length=12000)
    metadata: dict[str, object] = Field(default_factory=dict)
    reference_role: str = Field(default="primary", min_length=1, max_length=40)


@router.get("/projects/{project_id}/asset-tags", response_model=list[AssetTagRead])
async def list_asset_tags(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[AssetTagRead]:
    tags = await AssetTagService(session).list_tags(project_id=project_id, actor=user)
    return [
        AssetTagRead(
            id=tag.id,
            project_id=tag.project_id,
            name=tag.name,
            normalized_name=tag.normalized_name,
        )
        for tag in tags
    ]


@router.post("/projects/{project_id}/asset-tags", response_model=AssetTagRead, status_code=201)
async def create_asset_tag(
    project_id: UUID,
    body: AssetTagCreate,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AssetTagRead:
    tag = await AssetTagService(session).create_tag(
        project_id=project_id, actor=user, name=body.name
    )
    await session.commit()
    return AssetTagRead(
        id=tag.id,
        project_id=tag.project_id,
        name=tag.name,
        normalized_name=tag.normalized_name,
    )


@router.put("/projects/{project_id}/assets/{asset_id}/tags", response_model=list[AssetTagRead])
async def set_asset_tags(
    project_id: UUID,
    asset_id: UUID,
    body: AssetTagsUpdate,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> list[AssetTagRead]:
    tags = await AssetTagService(session).set_asset_tags(
        project_id=project_id, asset_id=asset_id, actor=user, names=list(body.tags)
    )
    await session.commit()
    return [
        AssetTagRead(
            id=tag.id,
            project_id=tag.project_id,
            name=tag.name,
            normalized_name=tag.normalized_name,
        )
        for tag in tags
    ]


@router.post(
    "/projects/{project_id}/assets/{asset_id}/recycle",
    response_model=AssetRead,
)
async def recycle_asset(
    project_id: UUID,
    asset_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AssetRead:
    asset = await AssetTagService(session).recycle_asset(
        project_id=project_id, asset_id=asset_id, actor=user
    )
    await session.commit()
    return _asset_read(asset, tags=await _asset_tag_names(session, asset.id))


@router.post(
    "/projects/{project_id}/assets/{asset_id}/restore",
    response_model=AssetRead,
)
async def restore_asset(
    project_id: UUID,
    asset_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AssetRead:
    asset = await AssetTagService(session).restore_asset(
        project_id=project_id, asset_id=asset_id, actor=user
    )
    await session.commit()
    return _asset_read(asset, tags=await _asset_tag_names(session, asset.id))


@router.post(
    "/projects/{project_id}/assets/from-artifact",
    response_model=AssetRead,
    status_code=201,
)
async def create_asset_from_artifact(
    project_id: UUID,
    body: AssetFromArtifactBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=160
    ),
) -> AssetRead:
    """Explicitly add a generated artifact as an asset card. Nothing is automatic.

    Retrying the same submission with the same ``Idempotency-Key`` returns the
    original card instead of creating a second one.
    """
    asset = await AssetFromArtifactService(session).create(
        project_id=project_id,
        actor=user,
        request=AssetFromArtifactRequest(
            kind=body.kind,
            name=body.name,
            artifact_id=body.artifact_id,
            description=body.description,
            metadata=body.metadata,
            reference_role=body.reference_role,
        ),
        request_key=idempotency_key,
    )
    await session.commit()
    return _asset_read(asset, tags=await _asset_tag_names(session, asset.id))


@router.get("/projects/{project_id}/assets/{asset_id}/card", response_model=AssetCardRead)
async def read_asset_card(
    project_id: UUID,
    asset_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> AssetCardRead:
    card = await AssetCardReadService(session).read_card(
        project_id=project_id, asset_id=asset_id, actor=user
    )
    return AssetCardRead.model_validate(card)


@router.post(
    "/projects/{project_id}/assets/{asset_id}/versions",
    response_model=AssetVersionRead,
    status_code=201,
)
async def create_asset_candidate(
    project_id: UUID,
    asset_id: UUID,
    body: AssetCandidateBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AssetVersionRead:
    version = await AssetVersionService(session).create_candidate(
        project_id=project_id,
        asset_id=asset_id,
        actor=user,
        name=body.name,
        description=body.description,
        metadata_json=dict(body.metadata),
    )
    await session.commit()
    return _version_read(version)


@router.post(
    "/projects/{project_id}/assets/{asset_id}/versions/{version_id}/promote",
    response_model=AssetVersionRead,
)
async def promote_asset_version(
    project_id: UUID,
    asset_id: UUID,
    version_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AssetVersionRead:
    version = await AssetVersionService(session).promote(
        project_id=project_id, asset_id=asset_id, version_id=version_id, actor=user
    )
    await session.commit()
    return _version_read(version)


@router.post(
    "/projects/{project_id}/assets/{asset_id}/versions/{version_id}/reject",
    response_model=AssetVersionRead,
)
async def reject_asset_version(
    project_id: UUID,
    asset_id: UUID,
    version_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AssetVersionRead:
    version = await AssetVersionService(session).reject(
        project_id=project_id, asset_id=asset_id, version_id=version_id, actor=user
    )
    await session.commit()
    return _version_read(version)
