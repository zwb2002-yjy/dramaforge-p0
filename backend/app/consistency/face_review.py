"""Shipped two-source face review — probe vs canonical image bytes (never self-match)."""

from __future__ import annotations

from dataclasses import dataclass

from app.consistency.image_embed import embedding_from_image_bytes


@dataclass(frozen=True)
class FaceReviewResult:
    status: str
    score: float | None
    rule: str


@dataclass(frozen=True)
class FaceReviewOutcome:
    status: str
    score: float | None
    rule: str
    probe_dim: int
    canonical_dim: int


def face_review_hook(
    *,
    embedding: list[float] | None,
    canonical: list[float] | None,
    threshold: float,
) -> FaceReviewResult:
    """Compare two 512-d embeddings (already derived from separate image sources)."""
    if embedding is None or canonical is None:
        return FaceReviewResult(status="needs_human", score=None, rule="missing_embedding")
    if len(embedding) != 512 or len(canonical) != 512:
        return FaceReviewResult(status="blocked", score=None, rule="dim_mismatch")
    score = sum(a * b for a, b in zip(embedding, canonical, strict=True))
    if score >= threshold:
        return FaceReviewResult(status="passed", score=score, rule="threshold")
    return FaceReviewResult(status="blocked", score=score, rule="below_threshold")


def face_review_images(
    *,
    probe_image_bytes: bytes,
    canonical_image_bytes: bytes,
    threshold: float,
) -> FaceReviewOutcome:
    """Compare embeddings derived *separately* from probe and canonical images.

    Callers MUST pass two sources (canonical reference vs generated keyframe).
    Passing the same object twice is a test smell; production forbids missing canonical.
    """
    if not probe_image_bytes:
        return FaceReviewOutcome("needs_human", None, "missing_probe", 0, 0)
    if not canonical_image_bytes:
        return FaceReviewOutcome("blocked", None, "missing_canonical", 0, 0)
    probe = embedding_from_image_bytes(probe_image_bytes)
    canon = embedding_from_image_bytes(canonical_image_bytes)
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
