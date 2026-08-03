"""Deterministic Video Drift sampling and evidence redaction tests."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from app.consistency import video_drift
from app.consistency.video_drift import (
    VIDEO_DRIFT_POLICY_STATUS,
    VIDEO_DRIFT_SAMPLING_VERSION,
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


def test_video_scores_are_desensitized_and_policy_remains_probe_required(
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
    assert VIDEO_DRIFT_POLICY_STATUS == "PROBE_REQUIRED"
