"""Coverage rejects unchecked mappings instead of manufacturing completion."""

import importlib.util
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "knowledge_audit", ROOT / "scripts/audit_model_knowledge.py"
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

IDENTITY = ("example", "example_v1", "fictional", "r1")
POINTER = "/operations/image.generate/output_options/size/maximum/value"
RAW = {
    "operations": {
        "image.generate": {
            "output_options": {"size": {"maximum": {"value": 512}, "enum": [256, 512]}}
        }
    }
}
CLAIMS = [{"id": "limit", "identity": IDENTITY, "value": 512}]
CANDIDATES = {
    IDENTITY[:3]: SimpleNamespace(
        identity=IDENTITY, manifest_hash="a" * 64, as_dict=lambda: deepcopy(RAW)
    )
}


def mapping(**changes):
    return {
        "claim_id": "limit",
        "classification": "structured",
        "schema_path": POINTER,
        "mapping_review": "Reviewed the exact output size maximum.",
        "candidate_identity": IDENTITY,
        "candidate_manifest_hash": "a" * 64,
        "expected_value": 512,
        **changes,
    }


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"classification": "invented_verified"}, "classification"),
        ({"schema_path": "/model_id"}, "operations pointer"),
        ({"candidate_manifest_hash": "b" * 64}, "stale candidate"),
        ({"candidate_identity": (*IDENTITY[:3], "r2")}, "stale candidate"),
        ({"expected_value": "512"}, "explicitly reviewed mapping"),
        ({"mapping_review": " "}, "explicit review"),
        ({"claim_id": "absent"}, "unknown or duplicate"),
        ({"extra_fact": True}, "mapping fields"),
    ],
)
def test_invalid_mapping_is_not_classified_as_coverage(changes, reason):
    with pytest.raises(ValueError, match=reason):
        audit._classify_baseline_claims(CLAIMS, [mapping(**changes)], CANDIDATES)


def test_duplicate_mapping_is_rejected_and_missing_claim_remains_unassessed():
    with pytest.raises(ValueError, match="duplicate"):
        audit._classify_baseline_claims(CLAIMS, [mapping(), mapping()], CANDIDATES)
    (row,) = audit._classify_baseline_claims(CLAIMS, [], CANDIDATES)
    assert row["classification"] == "not_assessed" and row["schema_path"] is None


def test_normalization_needs_both_exact_reviewed_value_and_explicit_transformation():
    claims = [{**CLAIMS[0], "value": 0.000512}]
    with pytest.raises(ValueError, match="mapping transformation"):
        audit._classify_baseline_claims(claims, [mapping()], CANDIDATES)
    (row,) = audit._classify_baseline_claims(
        claims, [mapping(transformation="decimal_MB_to_bytes")], CANDIDATES
    )
    assert row["mapped_value"] == 512 and row["original_value"] == 0.000512


def test_source_annotation_cannot_inflate_structured_capability_count():
    with pytest.raises(ValueError, match="not capability mappings"):
        audit._classify_baseline_claims(
            CLAIMS, [mapping(classification="source_annotation")], CANDIDATES
        )
    (row,) = audit._classify_baseline_claims(
        CLAIMS, [mapping(classification="source_annotation", schema_path=None)], CANDIDATES
    )
    assert row["schema_path"] is None


@pytest.mark.parametrize("index", ["-1", "01", "١", "~2"])
def test_malformed_array_pointer_cannot_count_as_a_mapping(index):
    with pytest.raises(ValueError, match="invalid JSON pointer"):
        audit._classify_baseline_claims(
            CLAIMS,
            [mapping(schema_path=f"/operations/image.generate/output_options/size/enum/{index}")],
            CANDIDATES,
        )
