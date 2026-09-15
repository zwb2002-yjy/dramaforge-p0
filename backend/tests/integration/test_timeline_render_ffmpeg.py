"""R6 real FFmpeg proof; synthetic local media, never Provider output substitutes.

This file is the formal delivery proof for the EditSession -> Final Film render
path.  It deliberately runs the production FFmpeg branch (never ``_test_render``)
and verifies the produced bytes by decoding them, so a self-reported codec
dictionary can never stand in for a playable film.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from app.config import get_settings
from app.production import timeline_renderer as renderer
from app.production.timeline_renderer import TimelineRenderClip, TimelineRenderError


async def _decode_whole_file(path: Path) -> str:
    """Decode every stream of ``path`` and return FFmpeg diagnostics.

    ``ffprobe`` only reports container metadata, so a file that cannot be
    decoded can still describe itself as H.264/AAC.  Decoding the complete file
    is the independent check the release contract requires; a non-zero exit code
    is reported as a diagnostic instead of raising, so callers can assert both
    "clean decode" and "refuses to decode".
    """
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Real FFmpeg is required for formal delivery verification"
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return "ffmpeg decode timed out"
    if process.returncode == 0:
        return stderr.decode("utf-8", errors="replace")
    return f"ffmpeg exited with {process.returncode}: {stderr.decode('utf-8', 'replace')}"


async def _mean_volume_db(path: Path) -> float:
    """Measure the decoded audio track's mean volume in dBFS."""
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Real FFmpeg is required for formal delivery verification"
    _stdout, stderr = await renderer._run(
        [
            ffmpeg,
            "-v",
            "info",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        timeout=120,
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", stderr.decode("utf-8", "replace"))
    assert match, "FFmpeg reported no mean_volume for the delivered audio track"
    return float(match.group(1))


def _dialogue_wav(seconds: float, frequency: float, *, sample_rate: int = 22050) -> bytes:
    """Build a deterministic mono WAV standing in for one shot's dialogue audio."""
    frames = int(seconds * sample_rate)
    samples = bytearray()
    for index in range(frames):
        # Two-tone envelope keeps the track non-constant so volume analysis is meaningful.
        value = 0.45 * math.sin(2 * math.pi * frequency * index / sample_rate)
        value += 0.25 * math.sin(2 * math.pi * (frequency * 1.5) * index / sample_rate)
        samples += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767))
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(samples))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(samples))
    )
    return header + bytes(samples)


@pytest.mark.asyncio
async def test_real_ffmpeg_uses_final_subtitle_clock_for_trim_crossfade_and_music(
    tmp_path, monkeypatch, record_property
):
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Real FFmpeg is required for R6 verification"
    settings = get_settings().model_copy(update={"app_env": "development"})
    monkeypatch.setattr(renderer, "get_settings", lambda: settings)
    sources = []
    for name in ("red", "blue"):
        path = tmp_path / f"{name}.mp4"
        prefix = 1.0 if name == "red" else 0.5
        await renderer._run(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s=320x240:r=20:d={prefix}",
                "-f",
                "lavfi",
                "-i",
                f"color=c={name}:s=320x240:r=20:d={4 - prefix}",
                "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map",
                "[v]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            timeout=30,
        )
        sources.append(path.read_bytes())
    music = tmp_path / "music.wav"
    await renderer._run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=22050",
            "-t",
            "4",
            str(music),
        ],
        timeout=30,
    )
    clips = [
        TimelineRenderClip(
            "red",
            "red-video",
            sources[0],
            _dialogue_wav(2.0, 220.0),
            "第一行\nLine two",
            1,
            2,
        ),
        TimelineRenderClip(
            "blue",
            "blue-video",
            sources[1],
            _dialogue_wav(2.0, 330.0),
            "Blue shot",
            0.5,
            2,
            transition_kind="crossfade",
            transition_duration_seconds=0.5,
        ),
    ]
    result = await renderer.render_timeline(
        clips, lineage="r6-local-proof", music_bytes=music.read_bytes()
    )
    assert not result.summary.get("test_render")
    assert result.summary["subtitle_burn_applied"] and result.summary["music_mixed"]
    assert result.summary["subtitle_cue_count"] == 2
    assert result.summary["audio_clip_count"] == 2
    assert abs(float(result.ffprobe["format"]["duration"]) - 3.5) <= 0.12
    assert {s["codec_name"] for s in result.ffprobe["streams"]} == {"h264", "aac"}
    text = result.subtitle_data.decode("utf-8")
    assert "00:00:00,000 --> 00:00:02,000\n第一行\nLine two" in text
    assert "00:00:01,500 --> 00:00:03,500\nBlue shot" in text
    output = tmp_path / "final.mp4"
    output.write_bytes(result.data)

    decode_errors = await _decode_whole_file(output)
    assert decode_errors.strip() == "", f"Delivered MP4 did not decode cleanly: {decode_errors}"
    delivered_mean_volume = await _mean_volume_db(output)
    assert delivered_mean_volume > -60.0, (
        f"Delivered MP4 has no audible audio content (mean volume {delivered_mean_volume} dBFS)"
    )

    async def sample(seconds):
        data, _ = await renderer._run(
            [
                ffmpeg,
                "-v",
                "error",
                "-ss",
                str(seconds),
                "-i",
                str(output),
                "-frames:v",
                "1",
                "-vf",
                "crop=40:40:0:0,scale=1:1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            timeout=30,
        )
        assert len(data) == 3
        return tuple(data)

    red, blue = await sample(0.3), await sample(3.0)
    assert red[0] > red[2] + 100 and blue[2] > blue[0] + 100
    silent = await renderer.render_timeline([replace(clips[0], subtitle_text="")], lineage="empty")
    assert silent.subtitle_data == b"" and not silent.summary["subtitle_burn_applied"]
    assert abs(float(silent.ffprobe["format"]["duration"]) - 2) <= 0.12
    empty_output = tmp_path / "empty.mp4"
    empty_output.write_bytes(silent.data)

    async def white_pixels(path):
        data, _ = await renderer._run(
            [
                ffmpeg,
                "-v",
                "error",
                "-ss",
                "0.3",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "crop=320:120:0:120",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            timeout=30,
        )
        return sum(min(data[index : index + 3]) > 170 for index in range(0, len(data), 3))

    burned_pixels = await white_pixels(output)
    empty_pixels = await white_pixels(empty_output)
    assert burned_pixels > empty_pixels + 10, "The final subtitle pass did not burn visible text"
    retimed = await renderer.render_timeline(
        [replace(clips[0], source_in_seconds=0.5, source_out_seconds=1.5, duration_seconds=2.0)],
        lineage="retimed",
    )
    assert abs(float(retimed.ffprobe["format"]["duration"]) - 2) <= 0.12
    assert retimed.summary["timeline_time_map"][0]["source_out_ms"] == 1500
    assert b"00:00:00,000 --> 00:00:02,000" in retimed.subtitle_data
    record_property(
        "render_evidence",
        json.dumps(
            {
                "actual_renderer": "ffmpeg",
                "mp4_sha256": hashlib.sha256(result.data).hexdigest(),
                "srt_sha256": hashlib.sha256(result.subtitle_data).hexdigest(),
                "duration": result.ffprobe["format"]["duration"],
                "time_map": result.summary["timeline_time_map"],
                "sampled_red": red,
                "sampled_blue": blue,
                "source_video_provider_calls": 0,
                "burned_text_pixels": burned_pixels,
                "empty_text_pixels": empty_pixels,
                "full_decode_stderr": decode_errors,
                "delivered_mean_volume_dbfs": delivered_mean_volume,
                "audio_clip_count": result.summary["audio_clip_count"],
            },
            sort_keys=True,
        ),
    )


async def test_corrupt_source_media_fails_the_delivery_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A damaged source must fail closed instead of producing a delivery artifact."""
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Real FFmpeg is required for formal delivery verification"
    settings = get_settings().model_copy(update={"app_env": "development"})
    monkeypatch.setattr(renderer, "get_settings", lambda: settings)
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048)
    clips = [
        TimelineRenderClip(
            "clip-1",
            "video-1",
            corrupt.read_bytes(),
            _dialogue_wav(1.0, 220.0),
            "Corrupt source",
            0.0,
            1.0,
        )
    ]
    with pytest.raises(TimelineRenderError):
        await renderer.render_timeline(clips, lineage="corrupt-source")


async def test_test_mode_render_is_marked_and_cannot_prove_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test stub is labelled, and its bytes can never be delivered media."""
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Real FFmpeg is required for formal delivery verification"
    settings = get_settings().model_copy(update={"app_env": "test"})
    monkeypatch.setattr(renderer, "get_settings", lambda: settings)
    clips = [
        TimelineRenderClip(
            "clip-1",
            "video-1",
            b"not-a-real-video",
            b"not-a-real-audio",
            "stub subtitle",
            0.0,
            1.5,
        )
    ]
    rendered = await renderer.render_timeline(clips, lineage="stub-proof")
    assert rendered.summary.get("test_render") is True
    assert rendered.ffprobe["format"]["format_name"] == "mp4"
    stub_path = tmp_path / "stub.mp4"
    stub_path.write_bytes(rendered.data)
    decode_errors = await _decode_whole_file(stub_path)
    assert decode_errors.strip() != "", (
        "The test-mode stub unexpectedly decoded as real media; a delivery proof "
        "would then accept rendered test artifacts"
    )
