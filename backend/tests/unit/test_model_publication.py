"""Reviewed Global model revisions do not silently inherit publication state."""

from __future__ import annotations

from datetime import date

import pytest
from app.providers.catalog_loader import ModelCatalogLoader, hash_manifest
from app.providers.model_publication import (
    publish_global_model_revision,
    set_model_publication_lifecycle,
)
from app.providers.model_system_models import ModelPublicationEvent, ModelPublicationState
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_reviewed_manifest_is_frozen_separately_from_unknown_lifecycle() -> None:
    source = next(
        item.as_dict()
        for item in ModelCatalogLoader().load()
        if item.identity[0] == "minimax"
        and item.identity[2] == "MiniMax-H3"
        and item.publication_lifecycle == "preview"
    )
    reviewed_at = date.fromisoformat(source["documented_at"])
    load_all_models()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            with pytest.raises(ValueError, match="source snapshot"):
                await publish_global_model_revision(
                    session, manifest=source, source_snapshot_id=" ", documented_at=reviewed_at
                )
            row = await publish_global_model_revision(
                session,
                manifest=source,
                source_snapshot_id="reviewed-minimax-20260929",
                documented_at=reviewed_at,
            )
            frozen_body = {
                key: value
                for key, value in source.items()
                if key not in {"lifecycle", "catalog_source"}
            }
            assert row.manifest_json == frozen_body
            assert row.manifest_hash == hash_manifest(frozen_body)
            assert row.source_snapshot_id == "reviewed-minimax-20260929"
            assert row.implementation_status == "manifest_mapped"
            assert (await session.get(ModelPublicationState, row.id)).lifecycle == "unknown"
            events = list((await session.scalars(select(ModelPublicationEvent))).all())
            assert len(events) == 1
            assert events[0].to_lifecycle == "unknown"
            await set_model_publication_lifecycle(
                session,
                model_capability_revision_id=row.id,
                lifecycle="legacy",
                reason="official lifecycle reviewed for this source snapshot",
            )
            assert (await session.get(ModelPublicationState, row.id)).lifecycle == "legacy"
            events = list((await session.scalars(select(ModelPublicationEvent))).all())
            assert len(events) == 2
            assert {(event.from_lifecycle, event.to_lifecycle) for event in events} == {
                (None, "unknown"),
                ("unknown", "legacy"),
            }
            assert row.manifest_hash == hash_manifest(frozen_body)
    finally:
        await engine.dispose()
