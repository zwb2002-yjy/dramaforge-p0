"""Deterministic Video Drift sampling without an unapproved pass threshold."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

from app.consistency.image_embed import embedding_from_image_bytes

VIDEO_DRIFT_SAMPLING_VERSION = "opencv-start-mid-end-scene-v1"
# Approved 2026-08-04 on 6 real frozen-sample videos (P0-VIDEO-01 §12.3).
# Decision rule: mean of scored frames >= 0.40 -> passed; otherwise blocked;
# no scored frames or >half unscorable -> needs_human. Real distribution:
# identity-preserving videos 0.416-0.605, drifting video (shot 10) 0.179.
VIDEO_DRIFT_POLICY_STATUS = "APPROVED"
VIDEO_DRIFT_POLICY_ID = "P0-VIDEO-DRIFT-2026-08-04"
VIDEO_DRIFT_THRESHOLD = 0.40


@dataclass(frozen=True, slots=True)
class VideoFrameSample:
    timestamp_seconds: float
    role: str
    image_bytes: bytes


def _encode_png(frame: Any) -> bytes:
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("video frame PNG encoding failed")
    return bytes(encoded)


def extract_video_samples(video_bytes: bytes) -> list[VideoFrameSample]:
    """Extract start/mid/end plus up to two strongest repeatable scene changes."""
    if not video_bytes:
        raise ValueError("video Artifact is empty")
    with tempfile.TemporaryDirectory(prefix="dramaforge-drift-") as temp_dir:
        path = Path(temp_dir) / "source.mp4"
        path.write_bytes(video_bytes)
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise ValueError("video Artifact cannot be decoded")
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            if frame_count < 1 or fps <= 0:
                raise ValueError("video Artifact has invalid frame metadata")

            anchors = {0: "start", frame_count // 2: "mid", frame_count - 1: "end"}
            scan_indices = sorted(
                {round(index * (frame_count - 1) / 11) for index in range(min(frame_count, 12))}
            )
            decoded: dict[int, Any] = {}
            previous_gray: Any = None
            changes: list[tuple[float, int]] = []
            for frame_index in sorted(set(anchors) | set(scan_indices)):
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok or frame is None:
                    continue
                decoded[frame_index] = frame
                if frame_index in scan_indices:
                    gray = cv2.resize(
                        cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                        (64, 64),
                    )
                    if previous_gray is not None:
                        delta = float(cv2.absdiff(gray, previous_gray).mean())
                        changes.append((delta, frame_index))
                    previous_gray = gray

            for rank, (_, frame_index) in enumerate(
                sorted(changes, key=lambda item: (-item[0], item[1]))[:2],
                start=1,
            ):
                anchors.setdefault(frame_index, f"scene_change_{rank}")

            samples: list[VideoFrameSample] = []
            for frame_index, role in sorted(anchors.items()):
                selected_frame: Any = decoded.get(frame_index)
                if selected_frame is None:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                    ok, fallback_frame = capture.read()
                    if not ok or fallback_frame is None:
                        continue
                    selected_frame = fallback_frame
                samples.append(
                    VideoFrameSample(
                        timestamp_seconds=round(frame_index / fps, 3),
                        role=role,
                        image_bytes=_encode_png(selected_frame),
                    )
                )
            if not {sample.role for sample in samples}.issuperset({"start", "mid", "end"}):
                raise ValueError("video start/mid/end frames could not be decoded")
            return samples
        finally:
            capture.release()


def decide_video_drift(rows: list[dict[str, object]]) -> dict[str, object]:
    """Approved Video Drift decision (P0-VIDEO-DRIFT-2026-08-04, §12.3).

    passed:      mean of scored frames >= 0.40
    blocked:     mean of scored frames < 0.40
    needs_human: no scored frames, or more than half the sampled frames are
                 unscorable (no detectable face / embedding failure). Fail-closed:
                 a needs_human review blocks downstream and approve; the intended
                 human path is re-running the video (or manual media), never an
                 approve-time override (P0 decision 2026-08-04).

    The returned evidence includes the scored-frame distribution (min/max and
    count above threshold) so a single high frame masking a mostly-drifting
    video is visible to a human reviewer without changing the decision rule.
    """
    scored: list[float] = []
    for row in rows:
        if row.get("status") == "scored":
            value = row.get("score")
            if isinstance(value, int | float):
                scored.append(float(value))
    total = len(rows)
    # A "scored" row whose score is non-numeric carries no usable evidence; count
    # it as unscorable so scored_frames + unscorable_frames always equals total.
    unscorable = total - len(scored)
    base: dict[str, object] = {
        "scored_frames": len(scored),
        "total_frames": total,
        "unscorable_frames": unscorable,
    }
    if not scored or (total and unscorable > total / 2):
        return {
            "status": "needs_human",
            "reason": "insufficient_scored_frames",
            **base,
        }
    mean = sum(scored) / len(scored)
    return {
        "status": "passed" if mean >= VIDEO_DRIFT_THRESHOLD else "blocked",
        "reason": "drift_mean_gate",
        "mean_score": round(mean, 6),
        "threshold": VIDEO_DRIFT_THRESHOLD,
        "policy_id": VIDEO_DRIFT_POLICY_ID,
        "min_score": round(min(scored), 6),
        "max_score": round(max(scored), 6),
        "frames_above_threshold": sum(1 for s in scored if s >= VIDEO_DRIFT_THRESHOLD),
        **base,
    }


def score_video_samples(
    samples: list[VideoFrameSample],
    *,
    canonical_image_bytes: bytes,
) -> list[dict[str, object]]:
    """Return desensitized per-frame scores; never persist embedding arrays."""
    canonical = embedding_from_image_bytes(canonical_image_bytes)
    rows: list[dict[str, object]] = []
    for sample in samples:
        try:
            probe = embedding_from_image_bytes(sample.image_bytes)
            score = sum(a * b for a, b in zip(probe, canonical, strict=True))
            rows.append(
                {
                    "timestamp_seconds": sample.timestamp_seconds,
                    "role": sample.role,
                    "status": "scored",
                    "score": score,
                    "rule_version": VIDEO_DRIFT_SAMPLING_VERSION,
                }
            )
        except Exception as exc:  # noqa: BLE001 - a bad frame remains review evidence
            rows.append(
                {
                    "timestamp_seconds": sample.timestamp_seconds,
                    "role": sample.role,
                    "status": "unscorable",
                    "score": None,
                    "error_type": type(exc).__name__,
                    "rule_version": VIDEO_DRIFT_SAMPLING_VERSION,
                }
            )
    return rows
