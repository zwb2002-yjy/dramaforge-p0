"""Character-reference evidence for the ``identity_review`` production node.

No biometric embedding or similarity score is computed. The review verifies
that independent Canonical and generated Artifacts exist, then deliberately
asks the creator to judge visual identity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IdentityReviewResult:
    status: str
    rule: str


def identity_review_images(
    *,
    probe_image_bytes: bytes,
    canonical_image_bytes: bytes,
) -> IdentityReviewResult:
    """Verify two-source evidence without pretending to judge visual identity."""
    if not probe_image_bytes:
        return IdentityReviewResult("blocked", "missing_probe")
    if not canonical_image_bytes:
        return IdentityReviewResult("blocked", "missing_canonical")
    if probe_image_bytes == canonical_image_bytes:
        return IdentityReviewResult("blocked", "identical_payload_invalid_evidence")
    return IdentityReviewResult("needs_human", "visual_identity_requires_human_review")
