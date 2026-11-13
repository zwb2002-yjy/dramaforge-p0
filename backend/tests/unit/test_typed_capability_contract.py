"""Fictional reviewed contracts prove validation, never real model availability."""

from copy import deepcopy
from uuid import uuid4

import pytest
from app.providers.capability_manifest_v2 import CapabilityBound
from app.providers.capability_resolver import (
    CapabilityResolutionError,
    CapabilityResolver,
    ProductCapabilityPolicy,
    ReferenceMetadata,
)
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.intents import VideoGenerationIntentV1
from app.providers.manifest import ModelCapabilityManifest, read_catalog_manifest
from app.providers.source_evidence import (
    SourceEvidenceStore,
    SourceRecord,
    SourceScope,
    SourceSnapshot,
    reviewed_manifest_subtree_hash,
)

STATUS = "documented_supported"
OP = "/operations/video.generate"


def bound(value):
    return {"kind": "bounded", "value": value, "claim_status": STATUS}


def fixture():
    scope = SourceScope(
        provider_type="example",
        protocol_profile="example_v1",
        model_id="fictional",
        api_version="v1",
        region="test",
    )
    source = SourceRecord(
        source_id="fictional",
        kind="official_api_doc",
        url="https://example.invalid/test-only",
        applies_to=(scope,),
    )
    snapshot = SourceSnapshot(
        source_snapshot_id="fictional-r1",
        source_id=source.source_id,
        capture_status="captured",
        content_sha256="a" * 64,
        locator="isolated test",
        review_status="reviewed",
        reviewed_scopes=(scope,),
    )
    raw = {
        "schema_version": "2",
        "manifest_version": "test",
        **scope.model_dump(),
        "model_revision": "r1",
        "media_kind": "video",
        "display_name": "Fictional",
        "lifecycle": "preview",
        "documented_at": "2026-10-13",
        "operations": {
            "video.generate": {
                "operation": "video.generate",
                "claim_status": STATUS,
                "evidence_group_ref": "fictional-r1",
                "input_contracts": {
                    "frames": {
                        "claim_status": STATUS,
                        "minimum_total_references": bound(1),
                        "maximum_total_references": bound(2),
                        "maximum_total_bytes": bound(2000),
                        "input_slots": {
                            role: {
                                "claim_status": STATUS,
                                "minimum": bound(0),
                                "maximum": bound(1),
                                "media_types": ["image/png"],
                                "ordering": "preserve",
                                "max_bytes": bound(1000),
                                "min_width": bound(16),
                                "max_width": bound(1024),
                                "min_height": bound(16),
                                "max_height": bound(1024),
                            }
                            for role in ("first_frame", "last_frame")
                        },
                    },
                    "text": {
                        "claim_status": STATUS,
                        "minimum_total_references": bound(0),
                        "maximum_total_references": bound(0),
                        "input_slots": {},
                    },
                },
                "output_options": {
                    "duration_seconds": {
                        "type": "integer",
                        "control": "native",
                        "claim_status": STATUS,
                        "enum": [5, 10],
                    },
                    "resolution": {
                        "type": "string",
                        "control": "native",
                        "claim_status": STATUS,
                        "enum": ["720p", "1080p"],
                    },
                },
                "constraints": [
                    {
                        "kind": "conditional",
                        "claim_status": STATUS,
                        "when": {"duration_seconds": 10},
                        "allowed": {"resolution": ["720p"]},
                    }
                ],
            }
        },
    }
    for parameter in raw["operations"]["video.generate"]["output_options"].values():
        parameter["required"] = False
    review(raw)
    return raw, SourceEvidenceStore(sources=(source,), snapshots=(snapshot,))


def review(raw):
    raw["operations"]["video.generate"]["evidence_review"] = {
        "covers": OP,
        "reviewed_subtree_hash": reviewed_manifest_subtree_hash(raw, OP),
        "reviewed_by": "test fixture",
        "review_kind": "human",
        "locator": "isolated fixture",
    }


def resolve(raw, store, references=(), output=None, policy=None):
    ids = [uuid4() for _ in references]
    return CapabilityResolver().resolve(
        manifest=read_catalog_manifest(raw),
        intent=VideoGenerationIntentV1(
            prompt="test",
            selection={"mode": "explicit_binding", "model_binding_id": uuid4()},
            references=[
                {"artifact_id": identifier, "role": role}
                for identifier, (role, _) in zip(ids, references, strict=True)
            ],
            output=output or {},
        ),
        reference_metadata=[
            ReferenceMetadata(
                artifact_id=identifier,
                **{
                    "mime_type": "image/png",
                    "byte_size": 500,
                    "width": 64,
                    "height": 64,
                    **metadata,
                },
            )
            for identifier, (_, metadata) in zip(ids, references, strict=True)
        ],
        policy=policy or ProductCapabilityPolicy(allowed_contracts=frozenset({"text", "frames"})),
        evidence_store=store,
    )


def test_fake_model_full_offline_matching_preserves_order_and_identity():
    raw, store = fixture()
    result = resolve(
        raw,
        store,
        [("last_frame", {}), ("first_frame", {})],
        {"duration_seconds": 5, "resolution": "1080p"},
    )
    assert result.matched_contract == "frames"
    assert result.reference_roles == ("last_frame", "first_frame")
    assert result.model_id == "fictional" and result.model_revision == "r1"
    assert resolve(raw, store).matched_contract == "text"


@pytest.mark.parametrize("status", ["unknown", "conflicting", "documented_unsupported"])
def test_unknown_conflicting_unsupported_fields_never_inherit_support(status):
    raw, store = fixture()
    raw["operations"]["video.generate"]["output_options"]["resolution"]["claim_status"] = status
    review(raw)
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store, output={"resolution": "720p"})
    assert "CLAIM_" in str(error.value.reasons)


def test_unknown_bound_is_not_unlimited_and_missing_metadata_blocks():
    raw, store = fixture()
    slot = raw["operations"]["video.generate"]["input_contracts"]["frames"]["input_slots"][
        "first_frame"
    ]
    slot["maximum"] = {"kind": "unknown", "claim_status": "unknown"}
    review(raw)
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store, [("first_frame", {})])
    assert "CAPABILITY_BOUND_UNKNOWN" in str(error.value.reasons)
    slot["maximum"] = {"kind": "unlimited", "claim_status": STATUS}
    review(raw)
    assert resolve(raw, store, [("first_frame", {})]).matched_contract == "frames"
    with pytest.raises(ValueError):
        CapabilityBound(kind="unlimited")
    with pytest.raises(ValueError):
        CapabilityBound(kind="bounded", value=True)


@pytest.mark.parametrize(
    "output",
    [{"duration_seconds": 10, "resolution": "1080p"}, {"duration_seconds": True}, {"seed": 4}],
)
def test_conditional_wrong_type_and_undeclared_options_block(output):
    raw, store = fixture()
    with pytest.raises(CapabilityResolutionError):
        resolve(raw, store, output=output)


def test_scope_and_stale_review_and_product_closed_are_independent():
    raw, store = fixture()
    raw["region"] = "other"
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store)
    assert "SOURCE_SCOPE_MISMATCH" in str(error.value.reasons)
    raw["region"] = "test"
    raw["operations"]["video.generate"]["output_options"]["resolution"]["enum"].append("2K")
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store)
    assert "EVIDENCE_REVIEW_STALE" in str(error.value.reasons)
    review(raw)
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store, policy=ProductCapabilityPolicy(allowed_contracts=frozenset()))
    assert error.value.code == "PRODUCT_CAPABILITY_CLOSED"


def test_derived_forced_rules_are_auditable_and_cannot_replace_explicit_values():
    raw, store = fixture()
    op = raw["operations"]["video.generate"]
    op["output_options"]["reference_count"] = {
        "type": "integer",
        "required": False,
        "control": "derived",
        "claim_status": STATUS,
        "enum": [0, 1, 2],
    }
    op["constraints"].extend(
        [
            {
                "kind": "derived",
                "claim_status": STATUS,
                "target": "reference_count",
                "derivation": "reference_count",
            },
            {"kind": "forced", "claim_status": STATUS, "target": "resolution", "value": "720p"},
        ]
    )
    review(raw)
    plan = resolve(raw, store, [("first_frame", {})])
    assert plan.effective_options == {"reference_count": 1, "resolution": "720p"}
    assert plan.transformations == (OP + "/constraints/1", OP + "/constraints/2")
    with pytest.raises(CapabilityResolutionError):
        resolve(raw, store, output={"resolution": "1080p"})


def test_unimplemented_edit_is_preserved_without_runtime_registration():
    raw, _ = fixture()
    raw["operations"]["video.edit"] = {"operation": "video.edit", "claim_status": "unknown"}
    manifest = read_catalog_manifest(raw)
    assert "video.edit" in manifest.operations
    with pytest.raises(ValueError, match="versioned Catalog reader"):
        ModelCapabilityManifest.model_validate(raw)
    with pytest.raises(ValueError, match="schema version"):
        read_catalog_manifest({**raw, "schema_version": "3"})


def test_existing_catalog_hashes_remain_raw_and_no_new_active_schema(tmp_path):
    import json

    from app.providers.catalog_loader import hash_manifest

    original = ModelCatalogLoader().load()
    assert all(item.manifest_hash == hash_manifest(item.as_dict()) for item in original)
    raw, _ = fixture()
    root = tmp_path / "example"
    root.mkdir()
    (root / "typed.json").write_text(json.dumps({**raw, "lifecycle": "active"}))
    with pytest.raises(ValueError, match="explicit implementation publication"):
        ModelCatalogLoader(tmp_path).load()


def test_ambiguity_is_never_resolved_by_policy_or_first_candidate():
    raw, store = fixture()
    contracts = raw["operations"]["video.generate"]["input_contracts"]
    contracts["duplicate"] = deepcopy(contracts["text"])
    review(raw)
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store)
    assert error.value.code == "MANIFEST_CONTRACT_AMBIGUOUS"


@pytest.mark.parametrize(
    "relative",
    [
        "output_options/resolution/enum",
        "output_options/resolution/enum/0",
        "output_options/resolution/control",
        "input_contracts/frames/input_slots/first_frame/media_types",
        "input_contracts/frames/input_slots/first_frame/maximum/value",
    ],
)
def test_leaf_override_blocks_consumed_fact_even_with_reviewed_supported_parent(relative):
    raw, store = fixture()
    op = raw["operations"]["video.generate"]
    pointer = OP + "/" + relative
    op["evidence_overrides"] = {
        "/" + relative: {
            "claim_status": "conflicting",
            "source_snapshot_ref": "fictional-r1",
            "evidence_review": {
                "covers": OP,
                "reviewed_subtree_hash": "a" * 64,
                "reviewed_by": "test",
                "review_kind": "human",
                "locator": "test",
            },
        }
    }
    review(raw)
    op["evidence_overrides"]["/" + relative]["evidence_review"]["reviewed_subtree_hash"] = (
        reviewed_manifest_subtree_hash(raw, OP)
    )
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store, [("first_frame", {})], {"resolution": "720p"})
    assert pointer in str(error.value.reasons)


def test_final_rules_reject_later_forced_value_and_enum_does_not_ignore_bounds():
    raw, store = fixture()
    op = raw["operations"]["video.generate"]
    op["constraints"].append(
        {"kind": "forced", "claim_status": STATUS, "target": "resolution", "value": "1080p"}
    )
    review(raw)
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store, output={"duration_seconds": 10})
    assert "CONDITIONAL_VALUE_FORBIDDEN" in str(error.value.reasons)
    op["constraints"] = []
    op["output_options"]["duration_seconds"]["maximum"] = bound(5)
    review(raw)
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store, output={"duration_seconds": 10})
    assert "CAPABILITY_LIMIT_EXCEEDED" in str(error.value.reasons)


@pytest.mark.parametrize(
    "changed", [{"mime_type": "image/jpeg"}, {"byte_size": 1200}, {"width": 2048}, {"height": None}]
)
def test_media_metadata_failures_are_strict(changed):
    raw, store = fixture()
    with pytest.raises(CapabilityResolutionError):
        resolve(raw, store, [("first_frame", changed)])


def test_video_fps_codec_and_aggregate_limits_are_checked():
    raw, store = fixture()
    contracts = raw["operations"]["video.generate"]["input_contracts"]
    contracts["references"] = {
        "claim_status": STATUS,
        "minimum_total_references": bound(1),
        "maximum_total_references": bound(2),
        "maximum_total_bytes": bound(1000),
        "max_total_duration_seconds": {"reference_video": bound(10)},
        "input_slots": {
            "reference_video": {
                "claim_status": STATUS,
                "minimum": bound(1),
                "maximum": bound(2),
                "media_types": ["video/mp4"],
                "ordering": "preserve",
                "codecs": ["h264"],
                "min_width": bound(16),
                "max_width": bound(1024),
                "min_height": bound(16),
                "max_height": bound(1024),
                "max_bytes": bound(1000),
                "min_fps": bound(20),
                "max_fps": bound(30),
                "min_duration_seconds": bound(2),
                "max_duration_seconds": bound(8),
            }
        },
    }
    review(raw)
    data = {"mime_type": "video/mp4", "fps": 24, "codec": "h264", "duration_seconds": 6}
    policy = ProductCapabilityPolicy(allowed_contracts=frozenset({"references"}))
    assert (
        resolve(raw, store, [("reference_video", data)], policy=policy).matched_contract
        == "references"
    )
    for change in ({"fps": 60}, {"codec": "vp9"}, {"duration_seconds": None}):
        with pytest.raises(CapabilityResolutionError):
            resolve(raw, store, [("reference_video", {**data, **change})], policy=policy)
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store, [("reference_video", data), ("reference_video", data)], policy=policy)
    assert "max_total_duration_seconds" in str(error.value.reasons)


def test_new_schema_lifecycle_is_outside_hash_but_legacy_hash_is_unchanged():
    from app.providers.catalog_loader import hash_manifest

    raw, _ = fixture()
    assert hash_manifest(raw) == hash_manifest({**raw, "lifecycle": "retired"})
    legacy = {"lifecycle": "active"}
    assert hash_manifest(legacy) != hash_manifest({"lifecycle": "retired"})


def test_later_rule_activates_an_earlier_forced_rule_without_unsafe_pass():
    raw, store = fixture()
    op = raw["operations"]["video.generate"]
    op["constraints"] = [
        {
            "kind": "forced",
            "claim_status": STATUS,
            "when": {"duration_seconds": 10},
            "target": "resolution",
            "value": "720p",
        },
        {"kind": "forced", "claim_status": STATUS, "target": "duration_seconds", "value": 10},
    ]
    review(raw)
    assert resolve(raw, store).effective_options == {"duration_seconds": 10, "resolution": "720p"}
    with pytest.raises(CapabilityResolutionError):
        resolve(raw, store, output={"resolution": "1080p"})


def test_uppercase_mime_cannot_bypass_dimension_limits():
    raw, store = fixture()
    with pytest.raises(CapabilityResolutionError):
        resolve(raw, store, [("first_frame", {"mime_type": "IMAGE/PNG", "width": 2048})])


def test_omitted_parameter_cannot_bypass_conflicting_requiredness():
    raw, store = fixture()
    op = raw["operations"]["video.generate"]
    op["evidence_overrides"] = {
        "/output_options/resolution/required": {
            "claim_status": "conflicting",
            "source_snapshot_ref": "fictional-r1",
            "evidence_review": {
                "covers": OP,
                "reviewed_subtree_hash": "a" * 64,
                "reviewed_by": "test",
                "review_kind": "human",
                "locator": "test",
            },
        }
    }
    review(raw)
    op["evidence_overrides"]["/output_options/resolution/required"]["evidence_review"][
        "reviewed_subtree_hash"
    ] = reviewed_manifest_subtree_hash(raw, OP)
    with pytest.raises(CapabilityResolutionError) as error:
        resolve(raw, store)
    assert "/required: CLAIM_CONFLICTING" in str(error.value.reasons)
