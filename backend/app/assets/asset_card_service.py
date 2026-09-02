"""Asset card reads from the canonical AssetVersion reference graph."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import (
    Asset,
    AssetVersion,
    AssetVersionReference,
)
from app.shared.errors import NotFoundError

# Canonical expected reference roles per asset kind (aligned with the
# vocabulary in migration 20260826_0044_phase2_asset_references.py).
_CHARACTER_ROLES = (
    "front_face",
    "three_quarter",
    "profile",
    "half_body",
    "full_body",
    "expression",
    "outfit",
)
_SCENE_ROLES = (
    "layout_reference",
    "lighting_reference",
    "style_reference",
    "scene_reference",
)


def _expected_roles(kind: str) -> tuple[str, ...]:
    if kind == "scene":
        return _SCENE_ROLES
    return _CHARACTER_ROLES  # character, prop, and unknown kinds get the character set


def _missing_roles(kind: str, present: set[str]) -> list[str]:
    return [role for role in _expected_roles(kind) if role not in present]


class AssetCardReadService:
    """Read the current AssetVersion and its explicit references."""

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

    async def read_card(
        self, *, project_id: UUID, asset_id: UUID, actor: User
    ) -> dict[str, object]:
        asset = await self._get_asset(project_id=project_id, asset_id=asset_id, actor=actor)
        current: AssetVersion | None = None
        if asset.current_version_id is not None:
            current = (
                await self._session.execute(
                    select(AssetVersion).where(
                        AssetVersion.id == asset.current_version_id,
                        AssetVersion.project_id == project_id,
                    )
                )
            ).scalar_one_or_none()

        references: list[dict[str, object]] = []
        if current is not None:
            version_rows = (
                await self._session.execute(
                    select(AssetVersionReference)
                    .where(
                        AssetVersionReference.project_id == project_id,
                        AssetVersionReference.asset_version_id == current.id,
                    )
                    .order_by(
                        AssetVersionReference.sort_order,
                        AssetVersionReference.label,
                    )
                )
            ).scalars().all()
            for version_ref in version_rows:
                references.append(
                    {
                        "artifact_id": version_ref.artifact_id,
                        "reference_role": version_ref.reference_role,
                        "label": version_ref.label,
                        "sort_order": version_ref.sort_order,
                        "metadata": dict(version_ref.metadata_json),
                        "source": "version",
                    }
                )

        present_roles: set[str] = set()
        for reference in references:
            role = reference.get("reference_role")
            if isinstance(role, str):
                present_roles.add(role)

        return {
            "asset_id": asset.id,
            "project_id": asset.project_id,
            "kind": asset.kind,
            "name": asset.name,
            "description": asset.description,
            "status": asset.status,
            "version": asset.version,
            "metadata": dict(asset.metadata_json),
            "current_version_id": asset.current_version_id,
            "current_version_number": current.version_number if current else None,
            "current_version_status": current.status if current else None,
            "references": references,
            "missing_reference_roles": _missing_roles(asset.kind, present_roles),
        }
