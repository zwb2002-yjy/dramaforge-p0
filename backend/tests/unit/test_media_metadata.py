"""Deterministic metadata persisted from exact provider media bytes."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest
from app.execution.product_path import _inspect_media_metadata
from PIL import Image


def test_image_metadata_comes_from_decoded_bytes() -> None:
    output = BytesIO()
    Image.new("RGB", (73, 131), color=(12, 34, 56)).save(output, format="PNG")

    metadata = _inspect_media_metadata(kind="keyframe", data=output.getvalue())

    assert metadata.width == 73
    assert metadata.height == 131
    assert metadata.duration_seconds is None


def test_video_metadata_comes_from_decoded_frames(tmp_path: Path) -> None:
    path = tmp_path / "metadata.mp4"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        24.0,
        (72, 128),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV MP4 writer is unavailable in this environment")
    try:
        frame = np.full((128, 72, 3), (40, 80, 120), dtype=np.uint8)
        for _ in range(121):
            writer.write(frame)
    finally:
        writer.release()

    metadata = _inspect_media_metadata(kind="video", data=path.read_bytes())

    assert metadata.width == 72
    assert metadata.height == 128
    assert metadata.duration_seconds is not None
    assert float(metadata.duration_seconds) == pytest.approx(121 / 24, abs=0.01)
