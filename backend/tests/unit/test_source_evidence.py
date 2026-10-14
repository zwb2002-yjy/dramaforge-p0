"""Controlled provenance fixtures do not claim support for real provider models."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from app.providers.catalog_loader import hash_manifest
from app.providers.source_evidence import (
    SourceCheck,
    SourceEvidenceStore,
    SourceRecord,
    SourceScope,
    SourceSnapshot,
    capability_claim_paths,
    load_source_evidence,
    resolve_field_evidence,
    reviewed_manifest_subtree_hash,
)

SCOPE = SourceScope(
    provider_type="example",
    protocol_profile="example_v1",
    model_id="example-001",
    api_version="v1",
    region="CN",
)
OP = "/operations/video.generate"


def _fixture():
    """Simulate a reviewer and official source entirely inside this isolated test."""
    source = SourceRecord(
        source_id="one-api",
        kind="official_api_doc",
        url="https://official.example.invalid/video",
        applies_to=(SCOPE,),
    )
    snapshot = SourceSnapshot(
        source_snapshot_id="one-api-body-r1",
        source_id=source.source_id,
        capture_status="captured",
        content_sha256="a" * 64,
        locator="Parameters",
        review_status="reviewed",
        reviewed_scopes=(SCOPE,),
    )
    store = SourceEvidenceStore(sources=(source,), snapshots=(snapshot,))
    manifest = {
        "operations": {
            "video.generate": {
                "claim_status": "documented_supported",
                "evidence_group_ref": snapshot.source_snapshot_id,
                "output_options": {
                    f"p{i}": {"value": i, "claim_status": "documented_supported"} for i in range(8)
                },
            }
        }
    }
    op = manifest["operations"]["video.generate"]
    op["evidence_review"] = {
        "covers": OP,
        "reviewed_subtree_hash": reviewed_manifest_subtree_hash(manifest, OP),
        "reviewed_by": "isolated fixture reviewer",
        "review_kind": "human",
        "locator": "Parameters table",
    }
    return manifest, store


def _resolve(manifest, store, name="p0", scope=SCOPE, status="documented_supported"):
    return resolve_field_evidence(
        manifest,
        pointer=f"{OP}/output_options/{name}/value",
        scope=scope,
        claim_status=status,
        store=store,
    )


def test_one_url_and_reviewed_group_trace_eight_fields_but_ninth_invalidates_review():
    manifest, store = _fixture()
    assert len(store.sources) == 1 and len({source.url for source in store.sources}) == 1
    assert all(_resolve(manifest, store, f"p{i}").officially_supported for i in range(8))
    assert _resolve(manifest, store).resolution == "inherited"
    manifest["operations"]["video.generate"]["output_options"]["p8"] = {
        "value": 8,
        "claim_status": "unknown",
    }
    assert _resolve(manifest, store).blocker == "EVIDENCE_REVIEW_STALE"
    assert not _resolve(manifest, store, "p8", status="unknown").officially_supported


def test_group_does_not_upgrade_unknown_field_or_accept_callers_forged_status():
    manifest, store = _fixture()
    op = manifest["operations"]["video.generate"]
    op["output_options"]["p0"]["claim_status"] = "unknown"
    op["evidence_review"]["reviewed_subtree_hash"] = reviewed_manifest_subtree_hash(manifest, OP)
    assert _resolve(manifest, store).blocker == "CLAIM_STATUS_MISMATCH"
    assert _resolve(manifest, store, status="unknown").blocker == "CLAIM_UNKNOWN"


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_id", "example-002"),
        ("protocol_profile", "other_v1"),
        ("region", "US"),
        ("api_version", "v2"),
        ("region", "unknown"),
    ],
)
def test_exact_applicability_never_inherits_between_models_protocols_regions_or_versions(
    field, value
):
    manifest, store = _fixture()
    assert (
        _resolve(manifest, store, scope=SCOPE.model_copy(update={field: value})).blocker
        == "SOURCE_SCOPE_MISMATCH"
    )


def test_check_logs_and_review_notes_do_not_change_manifest_revision_or_review_hash():
    manifest, store = _fixture()
    original = deepcopy(manifest)
    digest = hash_manifest(manifest)
    review_hash = reviewed_manifest_subtree_hash(manifest, OP)
    checked = store.append_check(
        SourceCheck(
            check_id="check-1",
            source_snapshot_ref=store.snapshots[0].source_snapshot_id,
            checked_at=datetime.now(UTC),
            result="unchanged",
            http_status=200,
            observed_content_sha256="a" * 64,
            note="No capability change",
        )
    )
    assert checked.snapshots == store.snapshots and manifest == original
    assert hash_manifest(manifest) == digest
    op = manifest["operations"]["video.generate"]
    op["evidence_review"]["review_notes"] = "a reviewer annotation"
    assert reviewed_manifest_subtree_hash(manifest, OP) == review_hash


def test_literal_values_and_parameter_names_that_look_like_audit_keys_are_semantic():
    manifest, _store = _fixture()
    digest = reviewed_manifest_subtree_hash(manifest, OP)
    op = manifest["operations"]["video.generate"]
    op["output_options"]["checked_at"] = {
        "value": {"source_url": "literal wire value"},
        "claim_status": "unknown",
    }
    assert reviewed_manifest_subtree_hash(manifest, OP) != digest
    digest = reviewed_manifest_subtree_hash(manifest, OP)
    op["output_options"]["checked_at"]["value"]["source_url"] = "changed literal"
    assert reviewed_manifest_subtree_hash(manifest, OP) != digest


def test_field_override_is_local_and_its_support_state_is_hashed():
    manifest, store = _fixture()
    op = manifest["operations"]["video.generate"]
    before = reviewed_manifest_subtree_hash(manifest, OP)
    op["evidence_overrides"] = {
        "output_options/p0": {
            "source_snapshot_ref": store.snapshots[0].source_snapshot_id,
            "claim_status": "conflicting",
            "evidence_review": {**op["evidence_review"], "covers": f"{OP}/output_options/p0"},
        }
    }
    assert reviewed_manifest_subtree_hash(manifest, OP) != before
    override = op["evidence_overrides"]["output_options/p0"]
    override["evidence_review"]["reviewed_subtree_hash"] = reviewed_manifest_subtree_hash(
        manifest, f"{OP}/output_options/p0"
    )
    op["evidence_review"]["reviewed_subtree_hash"] = reviewed_manifest_subtree_hash(manifest, OP)
    assert _resolve(manifest, store).blocker == "CLAIM_CONFLICTING"
    assert _resolve(manifest, store, "p1").officially_supported
    assert _resolve(manifest, store).resolution == "explicit"
    old = reviewed_manifest_subtree_hash(manifest, f"{OP}/output_options/p0")
    override["claim_status"] = "documented_supported"
    assert reviewed_manifest_subtree_hash(manifest, f"{OP}/output_options/p0") != old
    assert _resolve(manifest, store).blocker == "EVIDENCE_REVIEW_STALE"


def test_snapshots_and_check_records_are_append_only_and_urls_are_deduplicated():
    _manifest, store = _fixture()
    with pytest.raises(ValueError, match="cannot be rewritten"):
        store.append_snapshot(store.snapshots[0].model_copy(update={"content_sha256": "b" * 64}))
    with pytest.raises(ValueError, match="URLs must be unique"):
        SourceEvidenceStore(
            sources=(
                *store.sources,
                store.sources[0].model_copy(update={"source_id": "duplicate-url"}),
            )
        )


def test_operation_override_wins_over_nearer_parameter_group():
    manifest, store = _fixture()
    op = manifest["operations"]["video.generate"]
    parameter = op["output_options"]["p0"]
    parameter["evidence_group_ref"] = store.snapshots[0].source_snapshot_id
    parameter["evidence_review"] = {**op["evidence_review"], "covers": f"{OP}/output_options/p0"}
    op["evidence_overrides"] = {
        "output_options/p0": {
            "source_snapshot_ref": store.snapshots[0].source_snapshot_id,
            "claim_status": "conflicting",
            "evidence_review": {**parameter["evidence_review"]},
        }
    }
    review_hash = reviewed_manifest_subtree_hash(manifest, f"{OP}/output_options/p0")
    parameter["evidence_review"]["reviewed_subtree_hash"] = review_hash
    op["evidence_overrides"]["output_options/p0"]["evidence_review"]["reviewed_subtree_hash"] = (
        review_hash
    )
    assert _resolve(manifest, store).blocker == "CLAIM_CONFLICTING"
    assert _resolve(manifest, store).resolution == "explicit"


def test_nearest_parameter_group_preserves_its_explicit_parameter_status():
    manifest, store = _fixture()
    op = manifest["operations"]["video.generate"]
    parameter = op["output_options"]["p0"]
    parameter["evidence_group_ref"] = store.snapshots[0].source_snapshot_id
    parameter["evidence_review"] = {**op["evidence_review"], "covers": f"{OP}/output_options/p0"}
    parameter["evidence_review"]["reviewed_subtree_hash"] = reviewed_manifest_subtree_hash(
        manifest, f"{OP}/output_options/p0"
    )
    assert _resolve(manifest, store).officially_supported


def test_nearest_group_does_not_override_deeper_unknown_claim():
    manifest, store = _fixture()
    parameter = manifest["operations"]["video.generate"]["output_options"]["p0"]
    parameter["value"] = {"value": 1, "claim_status": "unknown"}
    parameter["evidence_group_ref"] = store.snapshots[0].source_snapshot_id
    parameter["evidence_review"] = {
        "covers": f"{OP}/output_options/p0",
        "reviewed_by": "fixture",
        "review_kind": "human",
        "locator": "Table",
        "reviewed_subtree_hash": reviewed_manifest_subtree_hash(
            manifest, f"{OP}/output_options/p0"
        ),
    }
    result = resolve_field_evidence(
        manifest,
        pointer=f"{OP}/output_options/p0/value/value",
        scope=SCOPE,
        claim_status="unknown",
        store=store,
    )
    assert result.blocker == "CLAIM_UNKNOWN" and not result.officially_supported


def test_ancestor_supported_override_cannot_upgrade_deeper_unknown_claim():
    manifest, store = _fixture()
    op = manifest["operations"]["video.generate"]
    op["output_options"]["p0"]["value"] = {"value": 1, "claim_status": "unknown"}
    op["evidence_overrides"] = {
        "output_options/p0": {
            "source_snapshot_ref": store.snapshots[0].source_snapshot_id,
            "claim_status": "documented_supported",
            "evidence_review": {**op["evidence_review"], "covers": f"{OP}/output_options/p0"},
        }
    }
    override = op["evidence_overrides"]["output_options/p0"]
    override["evidence_review"]["reviewed_subtree_hash"] = reviewed_manifest_subtree_hash(
        manifest, f"{OP}/output_options/p0"
    )
    result = resolve_field_evidence(
        manifest,
        pointer=f"{OP}/output_options/p0/value/value",
        scope=SCOPE,
        claim_status="unknown",
        store=store,
    )
    assert result.blocker == "CLAIM_UNKNOWN" and not result.officially_supported


def test_hash_and_resolution_use_the_same_nearest_override_for_identical_target():
    manifest, store = _fixture()
    op = manifest["operations"]["video.generate"]
    op["evidence_overrides"] = {"output_options/p0/value": {"claim_status": "documented_supported"}}
    parameter = op["output_options"]["p0"]
    parameter["evidence_overrides"] = {
        "value": {
            "claim_status": "conflicting",
            "source_snapshot_ref": store.snapshots[0].source_snapshot_id,
            "evidence_review": {**op["evidence_review"], "covers": f"{OP}/output_options/p0/value"},
        }
    }
    override = parameter["evidence_overrides"]["value"]
    digest = reviewed_manifest_subtree_hash(manifest, f"{OP}/output_options/p0/value")
    override["evidence_review"]["reviewed_subtree_hash"] = digest
    assert _resolve(manifest, store).blocker == "CLAIM_CONFLICTING"
    override["claim_status"] = "documented_supported"
    assert reviewed_manifest_subtree_hash(manifest, f"{OP}/output_options/p0/value") != digest
    assert _resolve(manifest, store).blocker == "EVIDENCE_REVIEW_STALE"


def test_more_specific_override_wins_independent_of_mapping_order():
    manifest, store = _fixture()
    op = manifest["operations"]["video.generate"]
    op["evidence_overrides"] = {
        "output_options/p0": {
            "source_snapshot_ref": store.snapshots[0].source_snapshot_id,
            "claim_status": "unknown",
            "evidence_review": {**op["evidence_review"], "covers": f"{OP}/output_options/p0"},
        },
        "output_options/p0/value": {
            "source_snapshot_ref": store.snapshots[0].source_snapshot_id,
            "claim_status": "conflicting",
            "evidence_review": {**op["evidence_review"], "covers": f"{OP}/output_options/p0/value"},
        },
    }
    specific = op["evidence_overrides"]["output_options/p0/value"]
    specific["evidence_review"]["reviewed_subtree_hash"] = reviewed_manifest_subtree_hash(
        manifest, f"{OP}/output_options/p0/value"
    )
    assert _resolve(manifest, store).blocker == "CLAIM_CONFLICTING"
    op["evidence_overrides"] = dict(reversed(list(op["evidence_overrides"].items())))
    assert _resolve(manifest, store).blocker == "CLAIM_CONFLICTING"


def test_original_baseline_captures_are_not_rewritten_by_later_reviews():
    store = load_source_evidence()
    # The original captures remain unreviewed; new reviewed snapshots append
    # separate identities rather than rewriting the stage-two evidence.
    baseline_snapshots = store.snapshots[:20]
    baseline_checks = store.checks[:20]
    assert len(baseline_snapshots) == len(baseline_checks) == 20
    assert len({source.url for source in store.sources}) == len(store.sources)
    assert all(snapshot.review_status == "unreviewed" for snapshot in baseline_snapshots)
    assert all(snapshot.content_sha256 for snapshot in store.snapshots)
    assert all(not snapshot.reviewed_scopes for snapshot in baseline_snapshots)
    assert all(
        check.source_snapshot_ref in {s.source_snapshot_id for s in baseline_snapshots}
        for check in baseline_checks
    )


def test_unchecked_source_projection_has_null_date_and_does_not_claim_support(monkeypatch):
    from app.providers import capability_sources

    source = SourceRecord(
        source_id="not-checked",
        kind="official_api_doc",
        url="https://official.example.invalid/api",
        applies_to=(SCOPE,),
    )
    store = SourceEvidenceStore(sources=(source,))
    monkeypatch.setattr(capability_sources, "load_source_evidence", lambda: store)
    (projection,) = capability_sources.official_sources(
        "example/example-001", protocol_profile="example_v1"
    )
    assert projection.checked_at is None and projection.source_snapshot_ref is None
    assert projection.status == "source_registered_not_checked"
    assert projection.model_dump(mode="json")["checked_at"] is None
    assert (
        capability_sources.official_sources("example/example-001", protocol_profile="other_v1")
        == []
    )


def test_logical_source_preserves_url_kind_and_historical_applicability():
    _manifest, store = _fixture()
    original = store.sources[0]
    with pytest.raises(ValueError, match="cannot change"):
        store.append_source(original.model_copy(update={"url": "https://changed.example.invalid"}))
    with pytest.raises(ValueError, match="cannot be removed"):
        store.append_source(original.model_copy(update={"applies_to": ()}))
    wider = original.model_copy(
        update={
            "applies_to": (
                *original.applies_to,
                SCOPE.model_copy(update={"model_id": "example-002"}),
            )
        }
    )
    assert store.append_source(wider).snapshots == store.snapshots


@pytest.mark.parametrize("rule", ["requires", "exclusion", "conditional", "derived", "forced"])
def test_constraint_parameter_names_are_never_stripped_as_audit_metadata(rule):
    manifest, _store = _fixture()
    op = manifest["operations"]["video.generate"]
    op["constraints"] = {rule: {"checked_at": "wire value"}}
    before = reviewed_manifest_subtree_hash(manifest, OP)
    op["constraints"][rule]["checked_at"] = "changed value"
    assert reviewed_manifest_subtree_hash(manifest, OP) != before


@pytest.mark.parametrize(
    "mapping",
    [
        "common_options",
        "native_options",
        "options",
        "protocol_facts",
        "wire_options",
        "dimension_bounds",
    ],
)
def test_actual_manifest_parameter_mappings_keep_reserved_parameter_names(mapping):
    manifest, _store = _fixture()
    op = manifest["operations"]["video.generate"]
    op[mapping] = {"checked_at": {"type": "string", "default": "first"}}
    digest = reviewed_manifest_subtree_hash(manifest, OP)
    op[mapping]["checked_at"]["default"] = "second"
    assert reviewed_manifest_subtree_hash(manifest, OP) != digest


def test_wire_attribute_literals_are_hashed_without_becoming_evidence_overrides():
    manifest, _store = _fixture()
    op = manifest["operations"]["video.generate"]
    op["wire_attributes"] = {
        "evidence_overrides": {"literal": "first"},
        "source_url": "wire value",
    }
    digest = reviewed_manifest_subtree_hash(manifest, OP)
    op["wire_attributes"]["evidence_overrides"]["literal"] = "second"
    assert reviewed_manifest_subtree_hash(manifest, OP) != digest


def test_claim_paths_ignore_literals_and_keep_reserved_parameter_names():
    manifest, _store = _fixture()
    op = manifest["operations"]["video.generate"]
    op["protocol_facts"] = {
        "source_url": {
            "type": "object",
            "claim_status": "documented_supported",
            "default": {"claim_status": "documented_supported", "kind": "unknown"},
        }
    }
    op["wire_attributes"] = {"claim_status": "conflicting", "kind": "unknown"}
    paths = capability_claim_paths(manifest)
    assert f"{OP}/protocol_facts/source_url" in paths
    assert len(paths) == 10
    assert not any("/default" in path or "/wire_attributes" in path for path in paths)


@pytest.mark.parametrize(
    "result,digest",
    [("unchanged", None), ("unchanged", "b" * 64), ("changed", None), ("changed", "a" * 64)],
)
def test_source_checks_cannot_claim_a_hash_result_that_disagrees_with_snapshot(result, digest):
    _manifest, store = _fixture()
    check = SourceCheck(
        check_id="invalid-hash-check",
        source_snapshot_ref=store.snapshots[0].source_snapshot_id,
        checked_at=datetime.now(UTC),
        result=result,
        observed_content_sha256=digest,
    )
    with pytest.raises(ValueError, match="hash"):
        store.append_check(check)


@pytest.mark.parametrize("capture", ["unreviewed", "unavailable", "synthetic"])
def test_http_success_and_synthetic_fixtures_do_not_prove_official_support(capture):
    manifest, store = _fixture()
    snapshot = store.snapshots[0]
    source = store.sources[0]
    if capture == "synthetic":
        source = source.model_copy(update={"kind": "synthetic_test"})
    elif capture == "unreviewed":
        snapshot = snapshot.model_copy(
            update={"review_status": "unreviewed", "reviewed_scopes": ()}
        )
    else:
        snapshot = SourceSnapshot(
            source_snapshot_id=snapshot.source_snapshot_id,
            source_id=source.source_id,
            capture_status="unavailable",
            locator="source unavailable",
        )
    changed = SourceEvidenceStore(sources=(source,), snapshots=(snapshot,))
    assert not _resolve(manifest, changed).officially_supported
