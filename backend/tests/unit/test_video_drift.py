"""Deterministic Video Drift sampling and evidence redaction tests."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from app.consistency import video_drift
from app.consistency.video_drift import (
    VIDEO_DRIFT_POLICY_ID,
    VIDEO_DRIFT_POLICY_STATUS,
    VIDEO_DRIFT_SAMPLING_VERSION,
    VIDEO_DRIFT_THRESHOLD,
    decide_video_drift,
    extract_video_samples,
    score_video_samples,
)


def _make_sample_mp4(path: Path) -> bytes:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10.0,
        (64, 64),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV MP4 writer is unavailable in this environment")
    try:
        for index in range(30):
            if index < 10:
                color = (0, 0, 255)
            elif index < 20:
                color = (0, 255, 0)
            else:
                color = (255, 0, 0)
            frame = np.full((64, 64, 3), color, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()
    return path.read_bytes()


def test_video_samples_include_stable_anchors_and_scene_roles(tmp_path: Path) -> None:
    video_bytes = _make_sample_mp4(tmp_path / "drift.mp4")
    first = extract_video_samples(video_bytes)
    second = extract_video_samples(video_bytes)

    assert {sample.role for sample in first}.issuperset({"start", "mid", "end"})
    assert [(sample.role, sample.timestamp_seconds) for sample in first] == [
        (sample.role, sample.timestamp_seconds) for sample in second
    ]
    assert first[0].timestamp_seconds == 0.0
    assert first[-1].timestamp_seconds >= first[0].timestamp_seconds
    assert all(sample.image_bytes.startswith(b"\x89PNG") for sample in first)


def test_video_scores_are_desensitized_and_policy_is_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = [
        video_drift.VideoFrameSample(0.0, "start", b"start"),
        video_drift.VideoFrameSample(1.0, "mid", b"mid"),
        video_drift.VideoFrameSample(2.0, "end", b"end"),
    ]

    def deterministic_embedding(data: bytes) -> list[float]:
        return [1.0, 0.0] if data == b"canonical" else [0.8, 0.6]

    monkeypatch.setattr(video_drift, "embedding_from_image_bytes", deterministic_embedding)
    rows = score_video_samples(samples, canonical_image_bytes=b"canonical")

    assert len(rows) == 3
    assert all(row["status"] == "scored" for row in rows)
    assert all(row["score"] == pytest.approx(0.8) for row in rows)
    assert all(row["rule_version"] == VIDEO_DRIFT_SAMPLING_VERSION for row in rows)
    assert all("embedding" not in row for row in rows)
    assert VIDEO_DRIFT_POLICY_STATUS == "APPROVED"
    assert VIDEO_DRIFT_POLICY_ID == "P0-VIDEO-DRIFT-2026-08-04"
    assert VIDEO_DRIFT_THRESHOLD == 0.40


def _scored(score: float) -> dict[str, object]:
    return {"status": "scored", "score": score}


def _unscorable() -> dict[str, object]:
    return {"status": "unscorable", "score": None}


def test_drift_mean_at_or_above_threshold_passes() -> None:
    rows = [_scored(0.5), _scored(0.35), _scored(0.4)]  # mean = 0.4167
    decision = decide_video_drift(rows)
    assert decision["status"] == "passed"
    assert decision["mean_score"] == pytest.approx(0.4167, abs=1e-3)
    assert decision["policy_id"] == VIDEO_DRIFT_POLICY_ID
    assert decision["min_score"] == pytest.approx(0.35)
    assert decision["max_score"] == pytest.approx(0.5)
    assert decision["frames_above_threshold"] == 2


def test_drift_mean_below_threshold_blocks() -> None:
    rows = [_scored(0.5), _scored(0.2), _scored(0.3)]  # mean = 0.333
    decision = decide_video_drift(rows)
    assert decision["status"] == "blocked"
    assert decision["min_score"] == pytest.approx(0.2)
    assert decision["frames_above_threshold"] == 1


def test_drift_mean_pass_surfaces_distribution_for_human_review() -> None:
    # [0.90, 0.20, 0.20] passes on mean (0.433) yet two of three frames sit near
    # the drifting range; the compact distribution must make that visible.
    decision = decide_video_drift([_scored(0.9), _scored(0.2), _scored(0.2)])
    assert decision["status"] == "passed"
    assert decision["mean_score"] == pytest.approx(0.4333, abs=1e-3)
    assert decision["min_score"] == pytest.approx(0.2)
    assert decision["max_score"] == pytest.approx(0.9)
    assert decision["frames_above_threshold"] == 1


def test_drift_no_scored_frames_needs_human() -> None:
    decision = decide_video_drift([_unscorable(), _unscorable()])
    assert decision["status"] == "needs_human"
    assert decision["reason"] == "insufficient_scored_frames"


def test_drift_majority_unscorable_needs_human() -> None:
    rows = [_scored(0.9), _unscorable(), _unscorable()]  # 2/3 unscorable > half
    decision = decide_video_drift(rows)
    assert decision["status"] == "needs_human"


def test_drift_exactly_half_unscorable_uses_scored_mean() -> None:
    rows = [_scored(0.9), _scored(0.9), _unscorable(), _unscorable()]  # exactly half
    decision = decide_video_drift(rows)
    assert decision["status"] == "passed"


def test_drift_scored_row_with_non_numeric_score_counts_as_unscorable() -> None:
    rows = [_scored(0.9), {"status": "scored", "score": None}, _unscorable()]
    decision = decide_video_drift(rows)
    assert decision["scored_frames"] == 1
    assert decision["unscorable_frames"] == 2
    assert decision["total_frames"] == 3
    # Invariant: every sampled frame is either scored or unscorable, never both.
    assert decision["scored_frames"] + decision["unscorable_frames"] == decision["total_frames"]
    assert decision["status"] == "needs_human"


def test_drift_real_sample_distribution_separates_drifting_video() -> None:
    # Approved on 2026-08-04 from 6 real frozen-sample videos: the identity
    # preserving videos (shot 1/4/5/8/9) mean 0.416-0.605; the drifting video
    # (shot 10) mean 0.179. Rule mean >= 0.40 passes the former, blocks the latter.
    preserving = decide_video_drift(
        [_scored(0.679), _scored(0.348), _scored(0.363), _scored(0.289), _scored(0.403)]
    )
    drifting = decide_video_drift(
        [_scored(0.583), _scored(0.184), _scored(0.152), _scored(-0.004), _scored(-0.021)]
    )
    assert preserving["status"] == "passed"  # shot 4, mean 0.416
    assert drifting["status"] == "blocked"  # shot 10, mean 0.179
