"""Model catalog types, seed data, frozen migration snapshot, and read-only service.

Stage A1 acceptance:
- ModelCapabilityManifest validates the seed manifests.
- contract hash is deterministic and order/whitespace insensitive.
- Seed manifests match the registry plugins' catalog_manifests.
- Contract fixtures (fixtures/providers/contracts/*.json) match the current seed
  hash (runtime source of truth).
- The frozen migration snapshot (_seeds_0015.py) matches the current seed hash
  (replay stability; the migration never imports runtime code).
- ModelCatalogService is read-only and resolves active revisions.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path

import pytest
from app.providers import registry as registry_module
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.catalog_service import ModelCatalogService
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest
from app.shared.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = BACKEND.parent / "fixtures" / "providers" / "contracts"
FROZEN_SEEDS_PATH = BACKEND / "alembic" / "_seeds_0015.py"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


def _load_frozen() -> object:
    spec = importlib.util.spec_from_file_location("_seeds_0015", str(FROZEN_SEEDS_PATH))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_all_seed_manifests_parse() -> None:
    assert len(SEED_MANIFESTS) == 14
    for manifest in SEED_MANIFESTS:
        parsed = ModelCapabilityManifest.model_validate(manifest)
        expected_revision = (
            "v2" if parsed.model_id in {"agnes-image-2.1-flash", "MiniMax-H3"}
            or parsed.manifest_version == "2026-09-30-ref2va-v2" else "v1"
        )
        assert parsed.model_revision == expected_revision
        assert parsed.catalog_source in {"official_static", "protocol_contract"}


def test_sglang_t2v_migration_matches_catalog_contract() -> None:
    path = BACKEND / "alembic" / "versions" / "20260929_0078_sglang_h3_t2v_contract.py"
    spec = importlib.util.spec_from_file_location("sglang_h3_t2v_contract", str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeded = next(
        item for item in SEED_MANIFESTS if item["model_id"] == "@contract/sglang-h3-t2v-v1"
    )
    assert seeded == module._MANIFEST


def test_sglang_ref2va_migration_matches_catalog_contract() -> None:
    path = BACKEND / "alembic" / "versions" / "20260930_0080_sglang_h3_ref2va_contract.py"
    spec = importlib.util.spec_from_file_location("sglang_h3_ref2va_contract", str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeded = next(
        item for item in SEED_MANIFESTS if item["model_id"] == "@contract/sglang-h3-ref2va-v1"
    )
    assert seeded == module._MANIFEST


def test_sglang_fl2va_and_ref2va_v2_migration_matches_catalog_contracts() -> None:
    path = BACKEND / "alembic" / "versions" / "20260930_0082_sglang_h3_fl2va_and_ref2va_v2.py"
    spec = importlib.util.spec_from_file_location("sglang_h3_expanded_contracts", str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    by_identity = {(m["model_id"], m["model_revision"]): m for m in SEED_MANIFESTS}
    for manifest in module._MANIFESTS:
        assert manifest == by_identity[(manifest["model_id"], manifest["model_revision"])]


def test_sglang_fl2va_exposes_only_each_modes_frame_slots() -> None:
    seeded = next(
        item for item in SEED_MANIFESTS
        if item["model_id"] == "@contract/sglang-h3-fl2va-v1"
    )
    manifest = to_v3_model_manifest(
        ModelCapabilityManifest.model_validate(seeded), transport_profile_id="test"
    )
    expected = {
        Capability.VIDEO_TEXT_TO_VIDEO: set(),
        Capability.VIDEO_IMAGE_TO_VIDEO: {"first_frame"},
        Capability.VIDEO_LAST_FRAME_TO_VIDEO: {"last_frame"},
        Capability.VIDEO_FIRST_LAST_FRAME: {"first_frame", "last_frame"},
    }
    for capability, slots in expected.items():
        spec = manifest.capability_specs[capability]
        assert set(spec.input_slots) == slots
        assert all(slot.required for slot in spec.input_slots.values())


def test_minimax_t2v_migration_matches_catalog_contract() -> None:
    path = BACKEND / "alembic" / "versions" / "20260929_0079_minimax_h3_t2v_contract.py"
    spec = importlib.util.spec_from_file_location("minimax_h3_t2v_contract", str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeded = next(
        item
        for item in SEED_MANIFESTS
        if item["model_id"] == "MiniMax-H3" and item["model_revision"] == "v2"
    )
    assert seeded == module._MANIFEST


def test_contract_hash_is_deterministic_and_order_insensitive() -> None:
    first = hash_manifest(SEED_MANIFESTS[0])
    reordered = dict(SEED_MANIFESTS[0])
    operations = dict(reordered["operations"])
    operations["video.generate"] = operations.pop("image.generate")  # move key
    reordered["operations"] = operations
    assert hash_manifest(reordered) != first  # different content
    assert hash_manifest(dict(SEED_MANIFESTS[0])) == first  # same dict, order safe


def test_seed_manifests_match_registry_plugins() -> None:
    agnes = registry_module.get_plugin("agnes", "agnes_cn_v1")
    ark = registry_module.get_plugin("volcengine", "ark_cn_v1")
    minimax = registry_module.get_plugin("minimax", "minimax_cn_v1")
    agnes_ids = [m["model_id"] for m in agnes.catalog_manifests]
    ark_ids = [m["model_id"] for m in ark.catalog_manifests]
    minimax_ids = [m["model_id"] for m in minimax.catalog_manifests]
    assert agnes_ids == [
        "agnes-image-2.1-flash",
        "agnes-video-v2.0",
        "@contract/agnes-video-openai-async-v2",
    ]
    assert ark_ids == [
        "doubao-seedream-4-0-250828",
        "doubao-seedance-1-0-pro-250528",
        "doubao-seedance-2-0-260128",
    ]
    assert minimax_ids == ["image-01", "MiniMax-H3"]
    for model_id in agnes_ids + ark_ids + minimax_ids:
        assert any(m["model_id"] == model_id for m in SEED_MANIFESTS)


def test_contract_fixtures_match_current_seed_hash() -> None:
    fixture_files = sorted(CONTRACTS_DIR.glob("*.json"))
    assert len(fixture_files) == 9
    manifest_by_id = {(m["model_id"], m["model_revision"]): m for m in SEED_MANIFESTS}
    for fixture_path in fixture_files:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        identity = (fixture["manifest"]["model_id"], fixture["manifest"]["model_revision"])
        assert identity in manifest_by_id
        assert fixture["manifest_hash"] == hash_manifest(manifest_by_id[identity])
        assert fixture["manifest_hash"] == hash_manifest(fixture["manifest"])
        assert fixture["contract"]["wire_template"]["method"] in {"POST", "GET"}


def test_frozen_migration_snapshot_matches_current_seed_hash() -> None:
    frozen = _load_frozen()
    frozen_manifests = frozen.FROZEN_0015
    assert len(frozen_manifests) == 4
    by_identity = {(m["model_id"], m["model_revision"]): m for m in SEED_MANIFESTS}
    for frozen_manifest in frozen_manifests:
        frozen_hash = frozen.hash_seed(frozen_manifest)
        assert frozen_hash == hash_manifest(frozen_manifest)
        current = by_identity.get((frozen_manifest["model_id"], frozen_manifest["model_revision"]))
        if current is not None:
            assert hash_manifest(current) == frozen_hash
    current_image = next(
        item for item in SEED_MANIFESTS if item["model_id"] == "agnes-image-2.1-flash"
    )
    frozen_image = next(
        item for item in frozen_manifests if item["model_id"] == "agnes-image-2.1-flash"
    )
    assert current_image["model_revision"] == "v2"
    assert frozen_image["model_revision"] == "v1"
    assert hash_manifest(current_image) != frozen.hash_seed(frozen_image)


def test_frozen_snapshot_is_self_contained() -> None:
    # The migration must never import runtime code; assert the frozen module has
    # no app.* import and carries its own hash implementation.
    source = FROZEN_SEEDS_PATH.read_text(encoding="utf-8")
    assert "from app." not in source
    assert "import app" not in source
    assert "def hash_seed" in source


async def test_catalog_service_is_read_only_and_resolves_active_entries(
    session: AsyncSession,
) -> None:
    # Seed both current and historical contracts to exercise revision selection.
    for manifest in SEED_MANIFESTS:
        documented_at = manifest.get("documented_at")
        entry = ModelCatalogEntry(
            provider_type=manifest["provider_type"],
            protocol_profile=manifest["protocol_profile"],
            model_id=manifest["model_id"],
            model_revision=manifest["model_revision"],
            display_name=manifest["display_name"],
            media_kind=manifest["media_kind"],
            lifecycle="active",
            catalog_source="official_static",
            capability_manifest_json=manifest,
            option_schema_json=manifest.get("option_schema") or {},
            documented_at=date.fromisoformat(documented_at) if documented_at else None,
            contract_manifest_hash=hash_manifest(manifest),
        )
        session.add(entry)
    await session.flush()

    service = ModelCatalogService(session)
    entries = await service.list_entries(provider_type="agnes", media_kind="image")
    assert len(entries) == 1
    assert entries[0].model_id == "agnes-image-2.1-flash"

    active = await service.active_entry_for(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-v2.0",
    )
    assert active is not None
    assert active.contract_manifest_hash == hash_manifest(
        [m for m in SEED_MANIFESTS if m["model_id"] == "agnes-video-v2.0"][0]
    )
    ref2va = await service.active_entry_for(
        provider_type="openai_compatible_media",
        protocol_profile="openai_media_v1",
        model_id="@contract/sglang-h3-ref2va-v1",
    )
    assert ref2va is not None
    assert ref2va.model_revision == "v2"

    missing = await service.active_entry_for(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="not-a-model",
    )
    assert missing is None

    # The service must not expose any write/upsert method.
    write_methods = {
        name
        for name in dir(service)
        if any(token in name for token in ("seed", "upsert", "create", "insert"))
    }
    assert write_methods == set()
