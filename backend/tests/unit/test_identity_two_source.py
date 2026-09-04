"""Identity review validates independent evidence without biometric scoring."""

from __future__ import annotations

from app.consistency.identity_review import identity_review_images


def test_identical_payload_is_not_valid_two_source_evidence() -> None:
    payload = b"same artifact"
    identical = identity_review_images(
        probe_image_bytes=payload,
        canonical_image_bytes=payload,
    )
    assert identical.status == "blocked"
    assert identical.rule == "identical_payload_invalid_evidence"


def test_independent_payloads_require_human_visual_review() -> None:
    result = identity_review_images(
        probe_image_bytes=b"generated shot artifact",
        canonical_image_bytes=b"canonical character artifact",
    )
    assert result.status == "needs_human"
    assert result.rule == "visual_identity_requires_human_review"


def test_missing_canonical_is_blocked() -> None:
    result = identity_review_images(
        probe_image_bytes=b"generated shot artifact",
        canonical_image_bytes=b"",
    )
    assert result.status == "blocked"
    assert result.rule == "missing_canonical"


def test_missing_probe_is_blocked() -> None:
    result = identity_review_images(
        probe_image_bytes=b"",
        canonical_image_bytes=b"canonical character artifact",
    )
    assert result.status == "blocked"
    assert result.rule == "missing_probe"
