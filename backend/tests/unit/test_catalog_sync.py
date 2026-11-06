"""Immutable catalog sync and publication transitions."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from shutil import copytree
from uuid import uuid4

import pytest
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_sync import CatalogRevisionConflict, sync_model_catalog
from app.providers.models import ProviderModelBinding
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

CATALOG_DIR = Path(__file__).resolve().parents[2] / "app" / "providers" / "model_catalog"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    load_all_models()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def test_sync_is_dry_by_default_idempotent_and_rejects_hash_drift(
    session: AsyncSession,
) -> None:
    source = ModelCatalogLoader().load()
    planned = await sync_model_catalog(session, manifests=source)
    assert len(planned.inserted) == len(source)
    assert await session.scalar(select(ModelCatalogEntry).limit(1)) is None

    inserted = await sync_model_catalog(session, manifests=source, apply=True)
    assert inserted.inserted == planned.inserted
    again = await sync_model_catalog(session, manifests=source, apply=True)
    assert again.inserted == ()
    assert again.lifecycle_updated == ()
    assert again.unchanged == len(source)

    row = await session.scalar(select(ModelCatalogEntry).limit(1))
    assert row is not None
    row.contract_manifest_hash = "0" * 64
    await session.flush()
    with pytest.raises(CatalogRevisionConflict, match="hash changed"):
        await sync_model_catalog(session, manifests=source, apply=True)


async def test_new_revision_preserves_old_row_and_demotes_it_to_legacy(
    session: AsyncSession, tmp_path: Path
) -> None:
    source = ModelCatalogLoader().load()
    await sync_model_catalog(session, manifests=source, apply=True)
    original = source[0]
    old_row = await session.scalar(
        select(ModelCatalogEntry).where(ModelCatalogEntry.model_id == original.identity[2])
    )
    assert old_row is not None
    old_id, old_hash = old_row.id, old_row.contract_manifest_hash
    binding = ProviderModelBinding(
        workspace_id=uuid4(),
        connection_id=uuid4(),
        media_type=old_row.media_kind,
        model_id=old_row.model_id,
        purpose="keyframe" if old_row.media_kind == "image" else "video",
        catalog_entry_id=old_id,
        capability_manifest_hash=old_hash,
        invoke_model_value=old_row.model_id,
        created_by=uuid4(),
        updated_by=uuid4(),
    )
    session.add(binding)
    await session.flush()
    binding_id = binding.id

    catalog = tmp_path / "model_catalog"
    copytree(CATALOG_DIR, catalog)
    old_file = next(
        path for path in catalog.rglob("*.json") if path.name == original.source_path.name
    )
    legacy_dir = old_file.parent / "legacy"
    legacy_dir.mkdir()
    old_file.rename(legacy_dir / old_file.name)
    revised = original.as_dict()
    revised["model_revision"] = "next-revision"
    revised["implementation_status"] = "documented"
    (old_file.parent / "08-next-revision.json").write_text(json.dumps(revised), encoding="utf-8")
    result = await sync_model_catalog(
        session, manifests=ModelCatalogLoader(catalog).load(), apply=True
    )
    assert len(result.inserted) == 1
    assert original.identity in result.lifecycle_updated
    assert old_row.id == old_id
    assert old_row.contract_manifest_hash == old_hash
    assert old_row.lifecycle == "legacy"
    assert binding.id == binding_id
    assert binding.catalog_entry_id == old_id
    assert binding.capability_manifest_hash == old_hash
    new_row = await session.scalar(
        select(ModelCatalogEntry).where(ModelCatalogEntry.model_revision == "next-revision")
    )
    assert new_row is not None and new_row.lifecycle == "active"


async def test_retired_row_cannot_be_republished_implicitly(session: AsyncSession) -> None:
    source = ModelCatalogLoader().load()
    await sync_model_catalog(session, manifests=source, apply=True)
    row = await session.scalar(select(ModelCatalogEntry).limit(1))
    assert row is not None
    row.lifecycle = "retired"
    await session.flush()
    with pytest.raises(CatalogRevisionConflict, match="cannot be reactivated"):
        await sync_model_catalog(session, manifests=source, apply=True)
