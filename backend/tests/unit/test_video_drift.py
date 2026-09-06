"""Deterministic temporal-review sampling and evidence tests."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from app.consistency.video_drift import (
    VIDEO_DRIFT_POLICY_ID,
    VIDEO_DRIFT_POLICY_STATUS,
    VIDEO_DRIFT_SAMPLING_VERSION,
    VideoFrameSample,
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
            writer.write(np.full((64, 64, 3), color, dtype=np.uint8))
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


def test_video_samples_are_hashed_for_human_review() -> None:
    samples = [
        VideoFrameSample(0.0, "start", b"start"),
        VideoFrameSample(1.0, "mid", b"mid"),
        VideoFrameSample(2.0, "end", b"end"),
    ]
    rows = score_video_samples(samples, canonical_image_bytes=b"canonical")

    assert len(rows) == 3
    assert all(row["status"] == "available_for_human_review" for row in rows)
    assert all(row["rule_version"] == VIDEO_DRIFT_SAMPLING_VERSION for row in rows)
    assert all(len(str(row["frame_content_hash"])) == 64 for row in rows)
    assert len({str(row["canonical_content_hash"]) for row in rows}) == 1
    assert all("score" not in row for row in rows)
    assert all("embedding" not in row for row in rows)
    assert all("threshold" not in row for row in rows)
    assert VIDEO_DRIFT_POLICY_STATUS == "HUMAN_REVIEW_REQUIRED"
    assert VIDEO_DRIFT_POLICY_ID == "live-dialogue-temporal-review-v1"


def test_video_drift_decision_always_requires_human_review() -> None:
    rows = [
        {"status": "available_for_human_review", "frame_content_hash": "a" * 64},
        {"status": "available_for_human_review", "frame_content_hash": "b" * 64},
    ]
    assert decide_video_drift(rows) == {
        "status": "needs_human",
        "reason": "temporal_identity_requires_human_review",
        "total_frames": 2,
        "policy_id": VIDEO_DRIFT_POLICY_ID,
    }
