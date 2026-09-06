"""Read-only model catalog access. Seeds are written by migrations only."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.catalog_models import ModelCatalogEntry


class ModelCatalogService:
    """Read-only queries over :class:`ModelCatalogEntry`. No upsert methods."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_entries(
        self,
        *,
        provider_type: str | None = None,
        protocol_profile: str | None = None,
        media_kind: str | None = None,
        lifecycle: str | None = None,
    ) -> list[ModelCatalogEntry]:
        stmt = select(ModelCatalogEntry)
        if provider_type is not None:
            stmt = stmt.where(ModelCatalogEntry.provider_type == provider_type)
        if protocol_profile is not None:
            stmt = stmt.where(ModelCatalogEntry.protocol_profile == protocol_profile)
        if media_kind is not None:
            stmt = stmt.where(ModelCatalogEntry.media_kind == media_kind)
        if lifecycle is not None:
            stmt = stmt.where(ModelCatalogEntry.lifecycle == lifecycle)
        stmt = stmt.order_by(
            ModelCatalogEntry.provider_type,
            ModelCatalogEntry.protocol_profile,
            ModelCatalogEntry.model_id,
            ModelCatalogEntry.model_revision,
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def entry_for_model(
        self,
        *,
        provider_type: str,
        protocol_profile: str,
        model_id: str,
        model_revision: str | None = None,
    ) -> ModelCatalogEntry | None:
        """Return a specific revision row (or any row when revision is None)."""
        stmt = select(ModelCatalogEntry).where(
            ModelCatalogEntry.provider_type == provider_type,
            ModelCatalogEntry.protocol_profile == protocol_profile,
            ModelCatalogEntry.model_id == model_id,
        )
        if model_revision is not None:
            stmt = stmt.where(ModelCatalogEntry.model_revision == model_revision)
        stmt = stmt.order_by(ModelCatalogEntry.model_revision.desc()).limit(1)
        return cast(ModelCatalogEntry | None, await self._session.scalar(stmt))

    async def active_entry_for(
        self,
        *,
        provider_type: str,
        protocol_profile: str,
        model_id: str,
    ) -> ModelCatalogEntry | None:
        """Return the active revision row, or None when none is active."""
        return cast(
            ModelCatalogEntry | None,
            await self._session.scalar(
                select(ModelCatalogEntry).where(
                    ModelCatalogEntry.provider_type == provider_type,
                    ModelCatalogEntry.protocol_profile == protocol_profile,
                    ModelCatalogEntry.model_id == model_id,
                    ModelCatalogEntry.lifecycle == "active",
                )
            ),
        )

    async def manifest_for(self, entry_id: UUID) -> dict[str, Any] | None:
        entry = await self._session.get(ModelCatalogEntry, entry_id)
        if entry is None:
            return None
        return dict(entry.capability_manifest_json or {})
