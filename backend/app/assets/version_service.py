"""P2-01 AssetVersion lifecycle: candidate / formal / historical / rejected."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Asset, AssetVersion
from app.shared.errors import NotFoundError, ValidationAppError

ASSET_VERSION_STATUSES = ("candidate", "formal", "historical", "rejected")


class AssetVersionService:
    """Owns the immutable asset-version lifecycle.

    ``Asset.version`` is a monotonic version-number counter; the *current
    formal* is always ``Asset.current_version_id``. Promote is atomic: old
    formal -> historical, candidate -> formal, pointer update.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_asset(
        self, *, project_id: UUID, asset_id: UUID, actor: User, for_update: bool = False
    ) -> Asset:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        query = select(Asset).where(
            Asset.id == asset_id, Asset.project_id == project_id
        )
        if for_update:
            query = query.with_for_update()
        asset = (
            await self._session.execute(query)
        ).scalar_one_or_none()
        if asset is None:
            raise NotFoundError("asset not found")
        return asset

    async def _get_version(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        version_id: UUID,
        actor: User,
        for_update: bool = False,
    ) -> AssetVersion:
        query = select(AssetVersion).where(
            AssetVersion.id == version_id,
            AssetVersion.project_id == project_id,
            AssetVersion.asset_id == asset_id,
        )
        if for_update:
            query = query.with_for_update()
        version = (
            await self._session.execute(query)
        ).scalar_one_or_none()
        if version is None:
            raise NotFoundError("asset version not found")
        return version

    async def create_candidate(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        actor: User,
        name: str | None = None,
        description: str | None = None,
        metadata_json: dict[str, object] | None = None,
    ) -> AssetVersion:
        asset = await self._get_asset(
            project_id=project_id, asset_id=asset_id, actor=actor, for_update=True
        )
        next_version = asset.version + 1
        asset.version = next_version
        version = AssetVersion(
            project_id=project_id,
            asset_id=asset_id,
            version_number=next_version,
            kind=asset.kind,
            name=name if name is not None else asset.name,
            description=description if description is not None else asset.description,
            metadata_json=(
                dict(metadata_json)
                if metadata_json is not None
                else dict(asset.metadata_json)
            ),
            status="candidate",
            created_by=actor.id,
        )
        self._session.add(version)
        await self._session.flush()
        return version

    async def promote(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        version_id: UUID,
        actor: User,
    ) -> AssetVersion:
        """Atomically make the candidate the single current formal version."""
        asset = await self._get_asset(
            project_id=project_id, asset_id=asset_id, actor=actor, for_update=True
        )
        candidate = await self._get_version(
            project_id=project_id,
            asset_id=asset_id,
            version_id=version_id,
            actor=actor,
            for_update=True,
        )
        if candidate.status != "candidate":
            raise ValidationAppError(
                "only candidate versions can be promoted",
                details={"status": candidate.status},
            )
        # Demote any existing formal first so only one formal exists at a time.
        current_formal = (
            await self._session.execute(
                select(AssetVersion)
                .where(
                    AssetVersion.asset_id == asset_id,
                    AssetVersion.project_id == project_id,
                    AssetVersion.status == "formal",
                    AssetVersion.id != candidate.id,
                )
                .with_for_update()
            )
        ).scalars().all()
        for old in current_formal:
            old.status = "historical"
        candidate.status = "formal"
        asset.current_version_id = candidate.id
        await self._session.flush()
        return candidate

    async def reject(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        version_id: UUID,
        actor: User,
    ) -> AssetVersion:
        await self._get_asset(project_id=project_id, asset_id=asset_id, actor=actor)
        candidate = await self._get_version(
            project_id=project_id,
            asset_id=asset_id,
            version_id=version_id,
            actor=actor,
        )
        if candidate.status != "candidate":
            raise ValidationAppError(
                "only candidate versions can be rejected",
                details={"status": candidate.status},
            )
        candidate.status = "rejected"
        await self._session.flush()
        return candidate

    async def list_history(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        actor: User,
    ) -> list[AssetVersion]:
        await self._get_asset(project_id=project_id, asset_id=asset_id, actor=actor)
        rows = (
            await self._session.execute(
                select(AssetVersion)
                .where(
                    AssetVersion.project_id == project_id,
                    AssetVersion.asset_id == asset_id,
                )
                .order_by(AssetVersion.version_number.desc())
            )
        ).scalars().all()
        return list(rows)

    async def resolve_current(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        actor: User,
    ) -> AssetVersion | None:
        asset = await self._get_asset(project_id=project_id, asset_id=asset_id, actor=actor)
        if asset.current_version_id is not None:
            return await self._get_version(
                project_id=project_id,
                asset_id=asset_id,
                version_id=asset.current_version_id,
                actor=actor,
            )
        return (
            await self._session.execute(
                select(AssetVersion)
                .where(
                    AssetVersion.project_id == project_id,
                    AssetVersion.asset_id == asset_id,
                    AssetVersion.status == "formal",
                )
                .order_by(AssetVersion.version_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
