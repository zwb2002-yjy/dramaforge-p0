"""P2-03 AssetTag vocabulary, asset filtering, and recycle/restore."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Asset, AssetTag, AssetTagLink
from app.shared.errors import NotFoundError, ValidationAppError

ASSET_STATUSES = ("draft", "active", "recycled")


def normalize_tag_name(name: str) -> str:
    normalized = name.strip().casefold()
    if not normalized:
        raise ValidationAppError("tag name must not be empty")
    return normalized


class AssetTagService:
    """Project-scoped tag vocabulary plus V1 asset filters (kind/tags/status/name)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _require_project(self, *, project_id: UUID, actor: User) -> None:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )

    async def _get_asset(
        self, *, project_id: UUID, asset_id: UUID, actor: User
    ) -> Asset:
        await self._require_project(project_id=project_id, actor=actor)
        asset = (
            await self._session.execute(
                select(Asset).where(
                    Asset.id == asset_id, Asset.project_id == project_id
                )
            )
        ).scalar_one_or_none()
        if asset is None:
            raise NotFoundError("asset not found")
        return asset

    async def create_tag(self, *, project_id: UUID, actor: User, name: str) -> AssetTag:
        await self._require_project(project_id=project_id, actor=actor)
        normalized = normalize_tag_name(name)
        tag = (
            await self._session.execute(
                select(AssetTag).where(
                    AssetTag.project_id == project_id,
                    AssetTag.normalized_name == normalized,
                )
            )
        ).scalar_one_or_none()
        if tag is None:
            tag = AssetTag(
                project_id=project_id,
                name=name.strip(),
                normalized_name=normalized,
            )
            self._session.add(tag)
            await self._session.flush()
        return tag

    async def list_tags(self, *, project_id: UUID, actor: User) -> list[AssetTag]:
        await self._require_project(project_id=project_id, actor=actor)
        rows = (
            await self._session.execute(
                select(AssetTag)
                .where(AssetTag.project_id == project_id)
                .order_by(AssetTag.normalized_name)
            )
        ).scalars().all()
        return list(rows)

    async def set_asset_tags(
        self, *, project_id: UUID, asset_id: UUID, actor: User, names: list[str]
    ) -> list[AssetTag]:
        asset = await self._get_asset(project_id=project_id, asset_id=asset_id, actor=actor)
        if not isinstance(names, list):
            raise ValidationAppError("tags must be a list of names")
        normalized_names = [normalize_tag_name(name) for name in names]
        tags: list[AssetTag] = []
        for name in names:
            tags.append(
                await self.create_tag(project_id=project_id, actor=actor, name=name)
            )
        await self._session.execute(
            delete(AssetTagLink).where(AssetTagLink.asset_id == asset.id)
        )
        for tag in tags:
            if tag.normalized_name in normalized_names:
                self._session.add(
                    AssetTagLink(asset_id=asset.id, tag_id=tag.id)
                )
        await self._session.flush()
        return tags

    async def list_assets(
        self,
        *,
        project_id: UUID,
        actor: User,
        kind: str | None = None,
        status: str | None = None,
        name: str | None = None,
        tags: list[str] | None = None,
    ) -> list[Asset]:
        await self._require_project(project_id=project_id, actor=actor)
        query = select(Asset).where(Asset.project_id == project_id)
        if kind:
            query = query.where(Asset.kind == kind)
        if status:
            if status not in ASSET_STATUSES:
                raise ValidationAppError(
                    "status must be one of draft/active/recycled"
                )
            query = query.where(Asset.status == status)
        if name:
            query = query.where(Asset.name.ilike(f"%{name}%"))
        if tags:
            tag_rows = (
                await self._session.execute(
                    select(AssetTag).where(
                        AssetTag.project_id == project_id,
                        AssetTag.normalized_name.in_(
                            [normalize_tag_name(tag) for tag in tags]
                        ),
                    )
                )
            ).scalars().all()
            if not tag_rows:
                return []
            tag_ids = [tag.id for tag in tag_rows]
            linked_asset_ids = (
                await self._session.execute(
                    select(AssetTagLink.asset_id).where(
                        AssetTagLink.tag_id.in_(tag_ids)
                    )
                )
            ).scalars().all()
            if not linked_asset_ids:
                return []
            query = query.where(Asset.id.in_(list(linked_asset_ids)))
        query = query.order_by(Asset.kind, Asset.name)
        rows = (
            await self._session.execute(query)
        ).scalars().all()
        return list(rows)

    async def recycle_asset(
        self, *, project_id: UUID, asset_id: UUID, actor: User
    ) -> Asset:
        asset = await self._get_asset(project_id=project_id, asset_id=asset_id, actor=actor)
        if asset.status == "recycled":
            raise ValidationAppError("asset is already recycled")
        asset.status = "recycled"
        await self._session.flush()
        return asset

    async def restore_asset(
        self, *, project_id: UUID, asset_id: UUID, actor: User
    ) -> Asset:
        asset = await self._get_asset(project_id=project_id, asset_id=asset_id, actor=actor)
        if asset.status != "recycled":
            raise ValidationAppError("only recycled assets can be restored")
        asset.status = "active"
        await self._session.flush()
        return asset

    async def tag_counts(
        self, *, project_id: UUID, actor: User
    ) -> dict[str, int]:
        await self._require_project(project_id=project_id, actor=actor)
        rows = (
            await self._session.execute(
                select(AssetTag.normalized_name, func.count(AssetTagLink.asset_id))
                .join(AssetTagLink, AssetTagLink.tag_id == AssetTag.id)
                .where(AssetTag.project_id == project_id)
                .group_by(AssetTag.normalized_name)
            )
        ).all()
        return {name: count for name, count in rows}
