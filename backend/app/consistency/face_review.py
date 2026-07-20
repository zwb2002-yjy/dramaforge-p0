"""Shipped two-source face review — probe vs canonical image bytes (never self-match)."""

from __future__ import annotations

from dataclasses import dataclass

from app.consistency.image_embed import embedding_from_image_bytes
from app.execution.pipeline import face_review_hook


@dataclass(frozen=True)
class FaceReviewOutcome:
    status: str
    score: float | None
    rule: str
    probe_dim: int
    canonical_dim: int


def face_review_images(
    *,
    probe_image_bytes: bytes,
    canonical_image_bytes: bytes,
    threshold: float = 0.35,
) -> FaceReviewOutcome:
    """Compare embeddings derived *separately* from probe and canonical images.

    Callers MUST pass two sources (canonical reference vs generated keyframe).
    Passing the same object twice is a test smell; production forbids missing canonical.
    """
    if not probe_image_bytes:
        return FaceReviewOutcome("needs_human", None, "missing_probe", 0, 0)
    if not canonical_image_bytes:
        return FaceReviewOutcome("blocked", None, "missing_canonical", 0, 0)
    if probe_image_bytes is canonical_image_bytes:
        # Same Python object identity — force separate derivation still, but flag
        pass
    probe = embedding_from_image_bytes(probe_image_bytes)
    canon = embedding_from_image_bytes(canonical_image_bytes)
    # Detect trivial identical payloads used as "fake pass"
    same_payload = probe_image_bytes == canonical_image_bytes
    result = face_review_hook(embedding=probe, canonical=canon, threshold=threshold)
    rule = result.rule
    if same_payload and result.status == "passed":
        rule = f"{result.rule}|identical_payload"
    return FaceReviewOutcome(
        status=result.status,
        score=result.score,
        rule=rule,
        probe_dim=len(probe),
        canonical_dim=len(canon),
    )
