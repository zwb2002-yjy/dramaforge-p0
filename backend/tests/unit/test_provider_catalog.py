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
from shutil import copytree

import pytest
from app.providers import registry as registry_module
from app.providers.bootstrap import build_v3_registry, transport_profile_id_for
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.catalog_service import ModelCatalogService
from app.providers.manifest import ModelCapabilityManifest
from app.shared.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = BACKEND.parent / "fixtures" / "providers" / "contracts"
FROZEN_SEEDS_PATH = BACKEND / "alembic" / "_seeds_0015.py"
CATALOG_DIR = BACKEND / "app" / "providers" / "model_catalog"


def _identity(manifest: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(manifest["provider_type"]),
        str(manifest["protocol_profile"]),
        str(manifest["model_id"]),
        str(manifest["model_revision"]),
    )


def _assert_fixture_completeness(
    manifests: list[dict[str, object]], fixtures_dir: Path
) -> None:
    by_identity = {_identity(manifest): manifest for manifest in manifests}
    assert len(by_identity) == len(manifests)
    fixtures = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in fixtures_dir.glob("*.json")
    ]
    fixture_by_identity = {_identity(fixture["manifest"]): fixture for fixture in fixtures}
    assert len(fixture_by_identity) == len(fixtures)
    assert fixture_by_identity.keys() == by_identity.keys()
    for identity, fixture in fixture_by_identity.items():
        manifest = by_identity[identity]
        assert fixture["manifest"] == manifest
        assert fixture["manifest_hash"] == hash_manifest(manifest)
        assert fixture["contract"]["wire_template"]["method"] in {"POST", "GET"}


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
    loaded = ModelCatalogLoader().load()
    active = [item for item in loaded if item.publication_lifecycle == "active"]
    assert len(active) == len(SEED_MANIFESTS)
    assert {_identity(item.as_dict()) for item in active} == {
        _identity(manifest) for manifest in SEED_MANIFESTS
    }
    for manifest in SEED_MANIFESTS:
        parsed = ModelCapabilityManifest.model_validate(manifest)
        assert parsed.model_revision
        assert parsed.catalog_source == "official_static"


def test_contract_hash_is_deterministic_and_order_insensitive() -> None:
    first = hash_manifest(SEED_MANIFESTS[0])
    reordered = dict(SEED_MANIFESTS[0])
    operations = dict(reordered["operations"])
    operations["video.generate"] = operations.pop("image.generate")  # move key
    reordered["operations"] = operations
    assert hash_manifest(reordered) != first  # different content
    assert hash_manifest(dict(SEED_MANIFESTS[0])) == first  # same dict, order safe


def test_seed_manifests_match_registry_plugins() -> None:
    for plugin in registry_module.list_plugins():
        expected = {
            _identity(manifest)
            for manifest in SEED_MANIFESTS
            if (manifest["provider_type"], manifest["protocol_profile"])
            == (plugin.provider_type, plugin.protocol_profile)
        }
        assert {_identity(manifest) for manifest in plugin.catalog_manifests} == expected
    for manifest in SEED_MANIFESTS:
        registry_module.get_plugin(manifest["provider_type"], manifest["protocol_profile"])
        assert transport_profile_id_for(
            manifest["provider_type"], manifest["protocol_profile"], manifest["media_kind"]
        ) is not None


def test_contract_fixtures_match_current_seed_hash() -> None:
    _assert_fixture_completeness(SEED_MANIFESTS, CONTRACTS_DIR)


def test_catalog_loader_discovers_new_same_protocol_manifest(tmp_path: Path) -> None:
    catalog = tmp_path / "model_catalog"
    copytree(CATALOG_DIR, catalog)
    dummy = dict(SEED_MANIFESTS[0])
    dummy["model_id"] = "test-catalog-extension"
    dummy["display_name"] = "Test catalog extension"
    dummy_path = catalog / dummy["provider_type"] / "test-catalog-extension.json"
    dummy_path.write_text(json.dumps(dummy), encoding="utf-8")

    loaded = ModelCatalogLoader(catalog).load()
    manifests = [item.as_dict() for item in loaded if item.publication_lifecycle == "active"]
    assert _identity(dummy) in {item.identity for item in loaded}
    registry, _ = build_v3_registry(
        seed_manifests=[ModelCapabilityManifest.model_validate(item) for item in manifests]
    )
    assert registry.get(f"{dummy['provider_type']}/{dummy['model_id']}")

    fixtures = tmp_path / "contracts"
    copytree(CONTRACTS_DIR, fixtures)
    with pytest.raises(AssertionError):
        _assert_fixture_completeness(manifests, fixtures)
    sample = json.loads((CONTRACTS_DIR / "agnes-image-2.1-flash.json").read_text("utf-8"))
    sample["manifest"] = dummy
    sample["manifest_hash"] = hash_manifest(dummy)
    (fixtures / "test-catalog-extension.json").write_text(json.dumps(sample), encoding="utf-8")
    _assert_fixture_completeness(manifests, fixtures)


def test_catalog_loader_rejects_duplicate_identity(tmp_path: Path) -> None:
    provider_dir = tmp_path / SEED_MANIFESTS[0]["provider_type"]
    provider_dir.mkdir()
    payload = json.dumps(SEED_MANIFESTS[0])
    (provider_dir / "one.json").write_text(payload, encoding="utf-8")
    (provider_dir / "two.json").write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate model catalog identity"):
        ModelCatalogLoader(tmp_path).load()


def test_preview_catalog_requires_explicit_implementation_status(tmp_path: Path) -> None:
    preview = tmp_path / "minimax" / "preview"
    preview.mkdir(parents=True)
    manifest = dict(next(item for item in SEED_MANIFESTS if item["provider_type"] == "minimax"))
    manifest["model_id"] = "candidate"
    manifest["lifecycle"] = "preview"
    path = preview / "candidate.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="implementation status"):
        ModelCatalogLoader(tmp_path).load()
    manifest["implementation_status"] = "documented"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = ModelCatalogLoader(tmp_path).load()
    assert loaded[0].publication_lifecycle == "preview"
    assert loaded[0].as_dict()["implementation_status"] == "documented"
    manifest["implementation_status"] = "contract_tested"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert ModelCatalogLoader(tmp_path).load()[0].publication_lifecycle == "preview"


def test_packaged_preview_catalog_has_model_evidence_and_no_active_collision() -> None:
    loaded = ModelCatalogLoader().load()
    previews = [item for item in loaded if item.publication_lifecycle == "preview"]
    assert previews
    active = {item.identity for item in loaded if item.publication_lifecycle == "active"}
    for item in previews:
        assert item.identity not in active
        manifest = ModelCapabilityManifest.model_validate(item.as_dict())
        assert manifest.lifecycle == "preview"
        assert manifest.implementation_status in {"discovered", "documented", "contract_tested"}
        assert manifest.evidence
        assert all(
            evidence.source_url.startswith("https://")
            for evidence in manifest.evidence.values()
        )


def test_unknown_protocol_profile_fails_registry_bootstrap() -> None:
    unknown = dict(SEED_MANIFESTS[0])
    unknown["protocol_profile"] = "unregistered_profile"
    with pytest.raises(ValueError, match="no registered transport profile"):
        build_v3_registry(seed_manifests=[ModelCapabilityManifest.model_validate(unknown)])


def test_revision_publication_keeps_legacy_manifest_bytes(tmp_path: Path) -> None:
    catalog = tmp_path / "model_catalog"
    copytree(CATALOG_DIR, catalog)
    original = ModelCatalogLoader(catalog).load()[0]
    old_hash = original.manifest_hash
    legacy_dir = original.source_path.parent / "legacy"
    legacy_dir.mkdir()
    original.source_path.rename(legacy_dir / original.source_path.name)
    revised = original.as_dict()
    revised["model_revision"] = "next-revision"
    (original.source_path.parent / "08-next-revision.json").write_text(
        json.dumps(revised), encoding="utf-8"
    )

    loaded = ModelCatalogLoader(catalog).load()
    old = next(item for item in loaded if item.identity == original.identity)
    current = next(item for item in loaded if item.identity[3] == "next-revision")
    assert old.manifest_hash == old_hash
    assert old.publication_lifecycle == "legacy"
    assert current.publication_lifecycle == "active"


def test_frozen_migration_snapshot_matches_current_seed_hash() -> None:
    frozen = _load_frozen()
    frozen_manifests = frozen.FROZEN_0015
    assert len(frozen_manifests) == 4
    by_identity = {(m["model_id"], m["model_revision"]): m for m in SEED_MANIFESTS}
    for frozen_manifest in frozen_manifests:
        frozen_hash = frozen.hash_seed(frozen_manifest)
        assert frozen_hash == hash_manifest(frozen_manifest)
        current = by_identity.get(
            (frozen_manifest["model_id"], frozen_manifest["model_revision"])
        )
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
    # In-memory seed of the two agnes entries so the read-only service has data.
    for manifest in SEED_MANIFESTS:
        if manifest["provider_type"] != "agnes":
            continue
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
