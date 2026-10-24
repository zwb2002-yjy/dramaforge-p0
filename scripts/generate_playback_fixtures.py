"""Generate tiny deterministic media for browser playback tests; no Provider calls."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image


def make_video(target: Path, color: str, frequency: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=160x90:r=12",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=22050",
            "-t",
            "0.8",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "32k",
            "-movflags",
            "+faststart",
            "-metadata",
            "creation_time=2026-10-09T00:00:00Z",
            str(target / f"{color}-tone.mp4"),
        ],
        check=True,
    )


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "fixtures" / "playback"
    target.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (160, 90), (40, 90, 140)).save(target / "blue-frame.png")
    make_video(target, "red", 440)
    make_video(target, "blue", 660)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=22050",
            "-t",
            "1.2",
            "-c:a",
            "pcm_s16le",
            str(target / "tone.wav"),
        ],
        check=True,
    )
    from app.consistency.video_drift import extract_video_samples

    for sample in extract_video_samples((target / "red-tone.mp4").read_bytes()):
        if sample.role in {"start", "end"}:
            (target / f"red-{sample.role}.png").write_bytes(sample.image_bytes)
    print(json.dumps({"fixtures": [file.name for file in target.iterdir() if file.is_file()]}))


if __name__ == "__main__":
    main()
