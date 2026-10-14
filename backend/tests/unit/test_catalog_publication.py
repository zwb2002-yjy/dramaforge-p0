"""Lifecycle permission changes preserve the exact immutable capability revision."""

from app.providers.catalog_loader import ModelCatalogLoader, hash_manifest
from app.providers.catalog_publication import (
    catalog_new_create_blocker,
    effective_publication_lifecycle,
    publication_events,
)


def test_official_retirement_is_independent_of_old_manifest_and_revisions():
    event = publication_events()[0]
    assert event.model_id == "agnes-video-v2.0"
    assert event.source_url and event.captured_content_sha256 and event.reviewed_by
    assert event.reviewed_statement.endswith("（已下线）")
    for item in ModelCatalogLoader().load():
        if item.identity[:3] == (event.provider_type, event.protocol_profile, event.model_id):
            assert item.publication_lifecycle == "retired"
            raw = item.as_dict()
            if raw.get("schema_version", "1") != "1":
                assert raw["lifecycle"] == "preview"
                continue
            assert raw["lifecycle"] == "active"
            assert item.manifest_hash == hash_manifest(raw)
            assert (
                item.manifest_hash
                == "93eee37ddff1d2e35d272ef43cf39b32a738738dd1d065c7752bcde8f9d12738"
            )


def test_retirement_never_spreads_to_other_models_or_protocols():
    assert (
        effective_publication_lifecycle("agnes", "agnes_cn_v1", "agnes-video-v2.0", "active")
        == "retired"
    )
    assert (
        effective_publication_lifecycle("agnes", "other-protocol", "agnes-video-v2.0", "active")
        == "active"
    )
    assert (
        effective_publication_lifecycle("agnes", "agnes_cn_v1", "agnes-video-v2.1", "active")
        == "active"
    )


def test_official_evidence_restrictions_bind_exact_frozen_revisions_without_retirement():
    restrictions = [event for event in publication_events() if event.new_create_blocker]
    assert len(restrictions) == 6
    loaded = {item.identity: item for item in ModelCatalogLoader().load()}
    for event in restrictions:
        identity = (
            event.provider_type,
            event.protocol_profile,
            event.model_id,
            event.model_revision,
        )
        item = loaded[identity]
        assert item.manifest_hash == event.contract_manifest_hash
        assert item.publication_lifecycle == item.as_dict()["lifecycle"] == "active"
        assert (
            catalog_new_create_blocker(*identity, item.manifest_hash)
            == "MODEL_OFFICIAL_EVIDENCE_GAP"
        )
        assert catalog_new_create_blocker(*identity, "b" * 64) == "CATALOG_MANIFEST_HASH_MISMATCH"
        assert (
            catalog_new_create_blocker(*identity[:3], "other-revision", item.manifest_hash) is None
        )
        assert event.audit_inventory_sha256
