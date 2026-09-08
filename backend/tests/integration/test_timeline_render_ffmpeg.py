"""R6 real FFmpeg proof; synthetic local media, never Provider output substitutes."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace

import pytest
from app.config import get_settings
from app.production import timeline_renderer as renderer
from app.production.timeline_renderer import TimelineRenderClip


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
        TimelineRenderClip("red", "red-video", sources[0], None, "第一行\nLine two", 1, 2),
        TimelineRenderClip(
            "blue",
            "blue-video",
            sources[1],
            None,
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
    assert abs(float(result.ffprobe["format"]["duration"]) - 3.5) <= 0.12
    assert {s["codec_name"] for s in result.ffprobe["streams"]} == {"h264", "aac"}
    text = result.subtitle_data.decode("utf-8")
    assert "00:00:00,000 --> 00:00:02,000\n第一行\nLine two" in text
    assert "00:00:01,500 --> 00:00:03,500\nBlue shot" in text
    output = tmp_path / "final.mp4"
    output.write_bytes(result.data)

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
            },
            sort_keys=True,
        ),
    )
