"""Professional project asset-card and version API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Asset, AssetVersion
from app.shared.errors import ConflictError, NotFoundError

router = APIRouter(tags=["assets"], dependencies=[Depends(require_selected_workspace)])


class AssetCreateBody(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=12000)
    metadata: dict[str, object] = Field(default_factory=dict)
    status: str = Field(default="draft", pattern="^(draft|active|archived)$")


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


def _asset_read(asset: Asset) -> AssetRead:
    return AssetRead(
        id=asset.id,
        project_id=asset.project_id,
        kind=asset.kind,
        name=asset.name,
        description=asset.description,
        metadata=dict(asset.metadata_json),
        status=asset.status,
        version=asset.version,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


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
) -> list[AssetRead]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    rows = (
        (
            await session.execute(
                select(Asset).where(Asset.project_id == project_id).order_by(Asset.kind, Asset.name)
            )
        )
        .scalars()
        .all()
    )
    return [_asset_read(row) for row in rows]


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
    session.add(
        AssetVersion(
            project_id=project_id,
            asset_id=asset.id,
            version_number=1,
            kind=body.kind,
            name=body.name,
            description=body.description,
            metadata_json=dict(body.metadata),
            status=body.status,
            created_by=user.id,
        )
    )
    await session.commit()
    return _asset_read(asset)


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
    session.add(
        AssetVersion(
            project_id=project_id,
            asset_id=asset.id,
            version_number=next_version,
            kind=body.kind,
            name=body.name,
            description=body.description,
            metadata_json=dict(body.metadata),
            status=body.status,
            created_by=user.id,
        )
    )
    await session.commit()
    return _asset_read(asset)


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
