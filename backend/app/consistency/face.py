"""Face embedding pure helpers for S0-A spike and later consistency.face_review.

Heavy InsightFace loading stays in scripts/run_s0_face_spike.py and heavy workers.
This module only handles 512-d L2 normalization, pair scoring, and anomaly labels.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum

EMBEDDING_DIM = 512


class FaceAnomalyLabel(StrEnum):
    """Stable anomaly / match classification labels (05 七层防线 / face_review)."""

    MATCHED = "matched"
    BELOW_THRESHOLD = "below_threshold"
    NO_FACE = "no_face"
    MULTIPLE_FACES = "multiple_faces"
    LOW_QUALITY = "low_quality"
    PROVIDER_ERROR = "provider_error"


def l2_normalize(vector: Sequence[float], *, dim: int = EMBEDDING_DIM) -> list[float]:
    """Return an L2-normalized vector of length ``dim``.

    Raises:
        ValueError: if length is not ``dim`` or the vector is zero-norm.
    """
    if len(vector) != dim:
        raise ValueError(f"embedding length must be {dim}, got {len(vector)}")
    values = [float(x) for x in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 0.0:
        raise ValueError("cannot L2-normalize a zero vector")
    return [v / norm for v in values]


def is_unit_vector(vector: Sequence[float], *, tol: float = 1e-5) -> bool:
    """True if vector length is EMBEDDING_DIM and L2 norm is ~1."""
    if len(vector) != EMBEDDING_DIM:
        return False
    norm = math.sqrt(sum(float(v) * float(v) for v in vector))
    return abs(norm - 1.0) <= tol


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity for two equal-length vectors (prefer L2-normalized inputs)."""
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    if len(a) != EMBEDDING_DIM:
        raise ValueError(f"embedding length must be {EMBEDDING_DIM}, got {len(a)}")
    return sum(float(x) * float(y) for x, y in zip(a, b, strict=True))


def pair_score(a: Sequence[float], b: Sequence[float]) -> float:
    """Identity similarity score in [-1, 1] after independent L2 normalization."""
    return cosine_similarity(l2_normalize(a), l2_normalize(b))


def classify_detection(
    *,
    face_count: int,
    det_score: float | None = None,
    min_det_score: float = 0.5,
    provider_error: bool = False,
) -> FaceAnomalyLabel | None:
    """Classify pre-embedding detection state.

    Returns None when exactly one usable face is present (embedding may proceed).
    """
    if provider_error:
        return FaceAnomalyLabel.PROVIDER_ERROR
    if face_count <= 0:
        return FaceAnomalyLabel.NO_FACE
    if face_count > 1:
        return FaceAnomalyLabel.MULTIPLE_FACES
    if det_score is not None and det_score < min_det_score:
        return FaceAnomalyLabel.LOW_QUALITY
    return None


def classify_match(
    score: float,
    *,
    threshold: float,
) -> FaceAnomalyLabel:
    """Compare a pair score to a decision threshold."""
    if score >= threshold:
        return FaceAnomalyLabel.MATCHED
    return FaceAnomalyLabel.BELOW_THRESHOLD


def evaluate_pairs_at_threshold(
    same_scores: Sequence[float],
    diff_scores: Sequence[float],
    *,
    threshold: float,
) -> dict[str, float | int]:
    """Compute FAR/FRR at a fixed threshold from desensitized score lists.

    FAR = false accept rate among different-identity pairs (score >= thr).
    FRR = false reject rate among same-identity pairs (score < thr).
    """
    same_n = len(same_scores)
    diff_n = len(diff_scores)
    false_accepts = sum(1 for s in diff_scores if s >= threshold)
    false_rejects = sum(1 for s in same_scores if s < threshold)
    far = (false_accepts / diff_n) if diff_n else float("nan")
    frr = (false_rejects / same_n) if same_n else float("nan")
    return {
        "threshold": threshold,
        "same_pairs": same_n,
        "diff_pairs": diff_n,
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "far": far,
        "frr": frr,
    }


def threshold_candidates(
    same_scores: Sequence[float],
    diff_scores: Sequence[float],
    *,
    grid: Sequence[float] | None = None,
) -> list[dict[str, float | int]]:
    """Evaluate a small threshold grid; does not invent scores."""
    if grid is None:
        grid = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    return [
        evaluate_pairs_at_threshold(same_scores, diff_scores, threshold=t) for t in grid
    ]


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile for p in [0, 100]."""
    if not values:
        raise ValueError("percentile requires non-empty values")
    if p < 0 or p > 100:
        raise ValueError("p must be in [0, 100]")
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def latency_summary(latencies_ms: Sequence[float]) -> dict[str, float]:
    """Mean and common percentiles for latency samples (milliseconds)."""
    if not latencies_ms:
        raise ValueError("latencies_ms must be non-empty")
    vals = [float(x) for x in latencies_ms]
    return {
        "count": float(len(vals)),
        "mean_ms": sum(vals) / len(vals),
        "p50_ms": percentile(vals, 50),
        "p95_ms": percentile(vals, 95),
        "p99_ms": percentile(vals, 99),
        "max_ms": max(vals),
    }


# Minimum fixture counts required by agent.md S0-A Gate.
MIN_SAME_PAIRS = 20
MIN_DIFF_PAIRS = 20
MIN_ANOMALY_SAMPLES = 10


def fixture_sufficiency(
    *,
    same_pairs: int,
    diff_pairs: int,
    anomaly_samples: int,
) -> dict[str, object]:
    """Return whether sample inventory meets S0-A Gate counts."""
    ok = (
        same_pairs >= MIN_SAME_PAIRS
        and diff_pairs >= MIN_DIFF_PAIRS
        and anomaly_samples >= MIN_ANOMALY_SAMPLES
    )
    return {
        "sufficient": ok,
        "same_pairs": same_pairs,
        "diff_pairs": diff_pairs,
        "anomaly_samples": anomaly_samples,
        "required": {
            "same_pairs": MIN_SAME_PAIRS,
            "diff_pairs": MIN_DIFF_PAIRS,
            "anomaly_samples": MIN_ANOMALY_SAMPLES,
        },
        "status": "OK" if ok else "BLOCKED_BY_FIXTURE",
    }
