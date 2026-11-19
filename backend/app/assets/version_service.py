"""P2-01 AssetVersion lifecycle: candidate / formal / historical / rejected."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.from_artifact_service import AssetAdoptionReceipt
from app.assets.models import Asset, AssetVersion
from app.assets.public_asset_models import (
    ProjectPublicAssetLink,
    PublicAssetPublication,
)
from app.assets.public_assets import PublicAssetService, PublicDisplay
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

ASSET_VERSION_STATUSES = ("candidate", "formal", "historical", "rejected")


@dataclass(frozen=True)
class CandidateReceipt:
    asset_id: UUID
    asset_version_id: UUID
    version_number: int
    created_asset_revision: int
    created: bool


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

    async def create_candidate_with_receipt(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        actor: User,
        expected_asset_version: int,
        request_key: str,
        request_hash: str,
        name: str | None = None,
        description: str | None = None,
        metadata_json: dict[str, object] | None = None,
        base_public_asset_link_id: UUID | None = None,
    ) -> CandidateReceipt:
        """Create one keyed candidate at the expected Asset revision."""
        if not 1 <= len(request_key) <= 160:
            raise ValidationAppError("Invalid candidate request key")
        asset = await self._get_asset(
            project_id=project_id, asset_id=asset_id, actor=actor, for_update=True
        )
        replay = await self._session.scalar(
            select(AssetVersion).where(
                AssetVersion.project_id == project_id,
                AssetVersion.asset_id == asset_id,
                AssetVersion.creation_request_key == request_key,
            )
        )
        if replay is not None:
            if replay.creation_request_hash != request_hash:
                raise ConflictError(
                    "This candidate request key was already used with a different input",
                    details={
                        "code": "ASSET_CREATION_REQUEST_REUSED",
                        "asset_id": str(asset.id),
                        "asset_version_id": str(replay.id),
                    },
                )
            return CandidateReceipt(
                asset_id=asset.id,
                asset_version_id=replay.id,
                version_number=replay.version_number,
                created_asset_revision=asset.version,
                created=False,
            )
        if asset.version != expected_asset_version:
            raise ConflictError(
                "Asset version changed; reload before deciding",
                details={"code": "ASSET_STALE_VERSION", "version": asset.version},
            )
        base_publication_id: UUID | None = None
        if base_public_asset_link_id is not None:
            link = await self._session.scalar(
                select(ProjectPublicAssetLink).where(
                    ProjectPublicAssetLink.id == base_public_asset_link_id,
                    ProjectPublicAssetLink.project_id == project_id,
                )
            )
            if link is None:
                raise ValidationAppError(
                    "public link does not belong to the current project",
                    details={"code": "REFERENCE_PROJECT_MISMATCH"},
                )
            if link.detached_at is not None:
                raise ConflictError(
                    "public link is detached",
                    details={"code": "REFERENCE_PUBLIC_LINK_DETACHED"},
                )
            publication = await self._session.get(
                PublicAssetPublication, link.publication_id
            )
            if publication is None or publication.status != "available":
                raise ConflictError(
                    "public asset is not available",
                    details={"code": "PUBLIC_ASSET_NOT_AVAILABLE"},
                )
            base_publication_id = publication.id
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
            base_publication_id=base_publication_id,
            base_public_asset_link_id=base_public_asset_link_id,
            creation_request_key=request_key,
            creation_request_hash=request_hash,
            created_by=actor.id,
        )
        self._session.add(version)
        await self._session.flush()
        return CandidateReceipt(
            asset_id=asset.id,
            asset_version_id=version.id,
            version_number=version.version_number,
            created_asset_revision=asset.version,
            created=True,
        )
    async def promote_with_receipt(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        version_id: UUID,
        actor: User,
        expected_asset_version: int,
        request_key: str,
        request_hash: str,
        public_display: PublicDisplay | None = None,
    ) -> AssetAdoptionReceipt:
        """Promote one candidate as an explicit adoption decision with a replay receipt."""
        if not 1 <= len(request_key) <= 160:
            raise ValidationAppError("Invalid adoption request key")
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
        if candidate.adoption_request_key == request_key:
            if candidate.adoption_request_hash != request_hash:
                raise ConflictError(
                    "This adoption request key was already used with a different decision",
                    details={
                        "code": "ASSET_ADOPTION_REQUEST_REUSED",
                        "asset_id": str(asset.id),
                        "asset_version_id": str(candidate.id),
                    },
                )
            return AssetAdoptionReceipt(
                asset_id=asset.id,
                asset_version_id=candidate.id,
                accepted_asset_revision=int(candidate.adopted_asset_revision or asset.version),
                publication_id=None,
                created=False,
            )
        if candidate.adopted_asset_revision is not None:
            raise ConflictError(
                "This asset version was already adopted",
                details={
                    "code": "ASSET_VERSION_ALREADY_ADOPTED",
                    "asset_id": str(asset.id),
                    "asset_version_id": str(candidate.id),
                    "accepted_asset_revision": candidate.adopted_asset_revision,
                },
            )
        if asset.version != expected_asset_version:
            raise ConflictError(
                "Asset version changed; reload before deciding",
                details={"code": "ASSET_STALE_VERSION", "version": asset.version},
            )
        if candidate.status != "candidate":
            raise ValidationAppError(
                "only candidate versions can be promoted",
                details={"status": candidate.status},
            )
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
        asset.version += 1
        candidate.adoption_request_key = request_key
        candidate.adoption_request_hash = request_hash
        candidate.adopted_asset_revision = asset.version
        await self._session.flush()
        publication_id: UUID | None = None
        if public_display is not None:
            published = await PublicAssetService(
                self._session, actor=actor
            ).publish(candidate.id, display=public_display)
            publication_id = published.id
        return AssetAdoptionReceipt(
            asset_id=asset.id,
            asset_version_id=candidate.id,
            accepted_asset_revision=asset.version,
            publication_id=publication_id,
            created=True,
        )
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
