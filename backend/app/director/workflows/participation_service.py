"""Multi-character participation DB binding validation (WF5/WF6).

Fail-closed: any referenced character, asset version, wardrobe or identity
reference must belong to the same project.  Cross-workspace references raise
before any provider work can be created.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion, AssetVersionReference
from app.director.workflows.character_participation import ShotParticipationPlan
from app.shared.errors import ValidationAppError


async def validate_participation_bindings(
    session: AsyncSession,
    *,
    project_id: UUID,
    plan: ShotParticipationPlan,
) -> None:
    """Validate every participation binding against the project's asset graph."""
    for item in plan.participations:
        asset = await session.get(Asset, item.asset_id)
        if asset is None:
            raise ValidationAppError(
                f"participation references unknown character asset {item.asset_id}",
                details={"code": "PARTICIPATION_ASSET_NOT_FOUND",
                         "asset_id": str(item.asset_id)},
            )
        if asset.project_id != project_id:
            raise ValidationAppError(
                f"participation asset {item.asset_id} is not in project {project_id}",
                details={"code": "PARTICIPATION_ASSET_CROSS_WORKSPACE",
                         "asset_id": str(item.asset_id)},
            )
        if asset.kind != "character":
            raise ValidationAppError(
                f"participation asset {item.asset_id} is not a character asset",
                details={"code": "PARTICIPATION_ASSET_KIND_MISMATCH",
                         "asset_id": str(item.asset_id), "kind": asset.kind},
            )
        if item.asset_version_id is not None:
            await _require_asset_version_for_asset(
                session, project_id=project_id, asset_id=item.asset_id,
                asset_version_id=item.asset_version_id,
            )
        if item.wardrobe_asset_version_id is not None:
            await _require_asset_version_kind(
                session, project_id=project_id,
                asset_version_id=item.wardrobe_asset_version_id,
                kind="wardrobe",
            )
        for reference_id in item.identity_reference_ids:
            await _require_project_reference(
                session, project_id=project_id, reference_id=reference_id
            )


async def _require_asset_version_for_asset(
    session: AsyncSession,
    *,
    project_id: UUID,
    asset_id: UUID,
    asset_version_id: UUID,
) -> None:
    version = await session.get(AssetVersion, asset_version_id)
    if version is None or version.project_id != project_id:
        raise ValidationAppError(
            f"asset version {asset_version_id} is not in project {project_id}",
            details={
                "code": "PARTICIPATION_ASSET_VERSION_CROSS_WORKSPACE",
                "asset_version_id": str(asset_version_id),
            },
        )
    if version.asset_id != asset_id:
        raise ValidationAppError(
            f"asset version {asset_version_id} does not belong to asset {asset_id}",
            details={
                "code": "PARTICIPATION_ASSET_VERSION_MISMATCH",
                "asset_version_id": str(asset_version_id),
                "asset_id": str(asset_id),
            },
        )


async def _require_asset_version_kind(
    session: AsyncSession,
    *,
    project_id: UUID,
    asset_version_id: UUID,
    kind: str,
) -> None:
    version = await session.get(AssetVersion, asset_version_id)
    if version is None or version.project_id != project_id:
        raise ValidationAppError(
            f"asset version {asset_version_id} is not in project {project_id}",
            details={
                "code": "PARTICIPATION_ASSET_VERSION_CROSS_WORKSPACE",
                "asset_version_id": str(asset_version_id),
            },
        )
    if version.kind != kind:
        raise ValidationAppError(
            f"asset version {asset_version_id} is not a {kind} asset",
            details={
                "code": "PARTICIPATION_ASSET_KIND_MISMATCH",
                "asset_version_id": str(asset_version_id),
                "kind": version.kind,
                "expected_kind": kind,
            },
        )


async def _require_project_reference(
    session: AsyncSession,
    *,
    project_id: UUID,
    reference_id: UUID,
) -> None:
    reference = await session.get(AssetVersionReference, reference_id)
    if reference is None or reference.project_id != project_id:
        raise ValidationAppError(
            f"identity reference {reference_id} is not in project {project_id}",
            details={
                "code": "PARTICIPATION_REFERENCE_CROSS_WORKSPACE",
                "reference_id": str(reference_id),
            },
        )
