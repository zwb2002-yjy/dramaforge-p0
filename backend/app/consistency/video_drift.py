"""Deterministic Video Drift sampling without an unapproved pass threshold."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

from app.consistency.image_embed import embedding_from_image_bytes

VIDEO_DRIFT_SAMPLING_VERSION = "opencv-start-mid-end-scene-v1"
VIDEO_DRIFT_POLICY_STATUS = "PROBE_REQUIRED"


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
