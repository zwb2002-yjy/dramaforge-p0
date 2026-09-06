"""P4-11 ProviderOperation request_summary standardization tests (03 §41)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.providers.request_summary import (
    RequestSummaryError,
    build_request_summary,
    normalize_request_summary,
    semantic_fingerprint,
    validate_no_secrets,
)


def test_build_request_summary_has_four_canonical_keys() -> None:
    summary = build_request_summary(
        translation_report={"transformations": []},
        effective_request_redacted={"prompt": "..."},
        reference_delivery=[
            {"role": "first_frame", "artifact_id": str(uuid4()), "status": "exact"}
        ],
    )
    canonical = ("translation_report", "effective_request_redacted",
                "reference_delivery", "semantic_fingerprint")
    assert set(canonical).issubset(summary)
    assert summary["effective_request_redacted"] == {"prompt": "..."}
    assert len(summary["semantic_fingerprint"]) == 64


def test_build_request_summary_rejects_secrets() -> None:
    with pytest.raises(RequestSummaryError, match="api_key"):
        build_request_summary(effective_request_redacted={"api_key": "sk-secret"})
    with pytest.raises(RequestSummaryError, match="forbidden key"):
        build_request_summary(effective_request_redacted={"Authorization": "Bearer x"})


def test_normalize_request_summary_folds_legacy_keys() -> None:
    artifact_id = str(uuid4())
    summary = normalize_request_summary(
        {
            "kind": "keyframe",
            "effective_request": {"prompt": "p"},
            "reference_artifact_ids": [artifact_id],
        }
    )
    assert "effective_request_redacted" in summary
    # legacy key is preserved for backward compatibility
    assert summary["effective_request"] == {"prompt": "p"}
    assert summary["effective_request_redacted"] == {"prompt": "p"}
    assert summary["reference_delivery"] == [
        {"role": "reference", "artifact_id": artifact_id, "status": "delivered"}
    ]
    assert "semantic_fingerprint" in summary
    assert len(summary["semantic_fingerprint"]) == 64


def test_normalize_request_summary_is_idempotent() -> None:
    first = normalize_request_summary({"effective_request": {"prompt": "p"}})
    second = normalize_request_summary(first)
    assert first["semantic_fingerprint"] == second["semantic_fingerprint"]


def test_validate_no_secrets_walks_nested() -> None:
    with pytest.raises(RequestSummaryError, match="ciphertext"):
        validate_no_secrets({"nested": {"credentials": {"ciphertext": "x"}}})


def test_semantic_fingerprint_is_deterministic() -> None:
    assert semantic_fingerprint({"a": 1, "b": [1, 2]}) == semantic_fingerprint(
        {"b": [1, 2], "a": 1}
    )
