"""Unit tests for shipped consistency.face pure helpers (S0-A)."""

from __future__ import annotations

import math

import pytest
from app.consistency.face import (
    EMBEDDING_DIM,
    FaceAnomalyLabel,
    classify_detection,
    classify_match,
    evaluate_pairs_at_threshold,
    fixture_sufficiency,
    is_unit_vector,
    l2_normalize,
    latency_summary,
    pair_score,
    percentile,
    threshold_candidates,
)


def _unit_axis(i: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i] = 1.0
    return v


def test_l2_normalize_shape_and_norm() -> None:
    raw = [1.0] * EMBEDDING_DIM
    out = l2_normalize(raw)
    assert len(out) == EMBEDDING_DIM
    assert is_unit_vector(out)
    expected = 1.0 / math.sqrt(EMBEDDING_DIM)
    assert abs(out[0] - expected) < 1e-9


def test_l2_normalize_rejects_wrong_dim() -> None:
    with pytest.raises(ValueError, match="512"):
        l2_normalize([1.0, 2.0, 3.0])


def test_l2_normalize_rejects_zero() -> None:
    with pytest.raises(ValueError, match="zero"):
        l2_normalize([0.0] * EMBEDDING_DIM)


def test_pair_score_identical_is_one() -> None:
    a = l2_normalize([float(i % 7 + 1) for i in range(EMBEDDING_DIM)])
    assert pair_score(a, a) == pytest.approx(1.0, abs=1e-6)


def test_pair_score_orthogonal_axes_near_zero() -> None:
    score = pair_score(_unit_axis(0), _unit_axis(1))
    assert score == pytest.approx(0.0, abs=1e-6)


def test_classify_detection_labels() -> None:
    assert classify_detection(face_count=0) == FaceAnomalyLabel.NO_FACE
    assert classify_detection(face_count=2) == FaceAnomalyLabel.MULTIPLE_FACES
    assert (
        classify_detection(face_count=1, det_score=0.1, min_det_score=0.5)
        == FaceAnomalyLabel.LOW_QUALITY
    )
    assert classify_detection(face_count=1, det_score=0.9) is None
    assert (
        classify_detection(face_count=1, provider_error=True)
        == FaceAnomalyLabel.PROVIDER_ERROR
    )


def test_classify_match_threshold() -> None:
    assert classify_match(0.55, threshold=0.5) == FaceAnomalyLabel.MATCHED
    assert classify_match(0.4, threshold=0.5) == FaceAnomalyLabel.BELOW_THRESHOLD


def test_evaluate_pairs_far_frr() -> None:
    same = [0.9, 0.8, 0.3]  # one reject at thr=0.5
    diff = [0.1, 0.6, 0.2]  # one accept at thr=0.5
    row = evaluate_pairs_at_threshold(same, diff, threshold=0.5)
    assert row["false_rejects"] == 1
    assert row["false_accepts"] == 1
    assert row["frr"] == pytest.approx(1 / 3)
    assert row["far"] == pytest.approx(1 / 3)


def test_threshold_candidates_grid_length() -> None:
    rows = threshold_candidates([0.9, 0.2], [0.1, 0.8], grid=[0.3, 0.5])
    assert len(rows) == 2
    assert rows[0]["threshold"] == 0.3


def test_percentile_and_latency_summary() -> None:
    assert percentile([10.0, 20.0, 30.0, 40.0], 50) == pytest.approx(25.0)
    summary = latency_summary([10.0, 20.0, 30.0, 40.0])
    assert summary["mean_ms"] == pytest.approx(25.0)
    assert summary["count"] == 4.0


def test_fixture_sufficiency_blocked_and_ok() -> None:
    blocked = fixture_sufficiency(same_pairs=0, diff_pairs=0, anomaly_samples=0)
    assert blocked["status"] == "BLOCKED_BY_FIXTURE"
    assert blocked["sufficient"] is False
    ok = fixture_sufficiency(same_pairs=20, diff_pairs=20, anomaly_samples=10)
    assert ok["status"] == "OK"
    assert ok["sufficient"] is True
