"""FFmpeg renderer for the persisted OpenCut Timeline.

The renderer is deliberately byte-oriented: the Worker resolves all Artifact
bytes and this module only applies the immutable Timeline edit instructions.
It never queries the database or invents production lineage.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.production.timeline_subtitles import (
    TimelineTimingError,
    build_timeline_subtitles,
)


class TimelineRenderError(RuntimeError):
    """Raised when a Timeline edit cannot be rendered safely."""


@dataclass(frozen=True)
class TimelineRenderClip:
    clip_id: str
    video_artifact_id: str
    video_bytes: bytes
    audio_bytes: bytes | None
    subtitle_text: str
    source_in_seconds: float
    duration_seconds: float
    transition_kind: str | None = None
    transition_duration_seconds: float = 0.0
    audio_artifact_id: str | None = None
    source_out_seconds: float | None = None


@dataclass(frozen=True)
class TimelineRenderResult:
    data: bytes
    ffprobe: dict[str, Any]
    summary: dict[str, Any]
    subtitle_data: bytes = b""


def _quote_subtitle_path(path: Path) -> str:
    return path.as_posix().replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


async def _run(command: list[str], *, timeout: float) -> tuple[bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise TimelineRenderError("Timeline FFmpeg process timed out") from exc
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[-1200:]
        raise TimelineRenderError(detail or f"FFmpeg exited with {process.returncode}")
    return stdout, stderr


async def _probe(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise TimelineRenderError("ffprobe executable not found")
    stdout, _stderr = await _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=index,codec_type,codec_name,width,height,channels,sample_rate",
            "-of",
            "json",
            str(path),
        ],
        timeout=60.0,
    )
    try:
        return dict(json.loads(stdout.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TimelineRenderError("ffprobe returned invalid JSON") from exc


async def _render_clip(clip: TimelineRenderClip, *, directory: Path, index: int) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TimelineRenderError("ffmpeg executable not found")
    video = directory / f"source-{index}.mp4"
    audio = directory / f"audio-{index}.wav"
    output = directory / f"timeline-clip-{index}.mp4"
    video.write_bytes(clip.video_bytes)

    command = [ffmpeg, "-y", "-ss", f"{clip.source_in_seconds:.3f}"]
    source_duration = (
        clip.source_out_seconds - clip.source_in_seconds
        if clip.source_out_seconds is not None
        else clip.duration_seconds
    )
    command.extend(["-t", f"{source_duration:.3f}", "-i", str(video)])
    if clip.audio_bytes:
        audio.write_bytes(clip.audio_bytes)
        command.extend(["-i", str(audio)])
    else:
        command.extend(["-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono"])
    if abs(source_duration - clip.duration_seconds) > 0.0005:
        command.extend(
            ["-vf", f"setpts=(PTS-STARTPTS)*{clip.duration_seconds / source_duration:.9f}"]
        )
    command.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            f"{clip.duration_seconds:.3f}",
            "-af",
            "apad",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-metadata",
            f"comment=dramaforge-timeline-clip:{clip.clip_id}",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    await _run(command, timeout=300.0)
    if not output.is_file() or output.stat().st_size <= 0:
        raise TimelineRenderError(f"Timeline clip {clip.clip_id} produced no output")
    return output


async def _concat_cuts(paths: list[Path], *, output: Path, lineage: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TimelineRenderError("ffmpeg executable not found")
    manifest = output.with_name("timeline-concat.txt")
    manifest.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in paths) + "\n",
        encoding="utf-8",
    )
    await _run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-c",
            "copy",
            "-metadata",
            f"comment=dramaforge-timeline-render:{lineage}",
            "-movflags",
            "+faststart",
            str(output),
        ],
        timeout=300.0,
    )


async def _assemble_segments(
    clips: list[TimelineRenderClip],
    paths: list[Path],
    *,
    output: Path,
    lineage: str,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TimelineRenderError("ffmpeg executable not found")
    if any(clip.transition_kind not in {"crossfade", "cut", None} for clip in clips[1:]):
        raise TimelineRenderError("unsupported Timeline transition")
    command = [ffmpeg, "-y"]
    for path in paths:
        command.extend(["-i", str(path)])
    filters: list[str] = []
    for index in range(len(paths)):
        filters.append(f"[{index}:v]setpts=PTS-STARTPTS[v{index}]")
        filters.append(f"[{index}:a]asetpts=PTS-STARTPTS[a{index}]")
    current_video = "v0"
    current_audio = "a0"
    time_map = build_timeline_subtitles(clips)
    for index in range(1, len(paths)):
        timing = time_map.clips[index]
        duration = timing.overlap_ms / 1000
        next_video = f"vxf{index}"
        next_audio = f"axf{index}"
        if clips[index].transition_kind == "crossfade":
            filters.append(
                f"[{current_video}][v{index}]xfade=transition=fade:duration="
                f"{duration:.3f}:offset={timing.start_ms / 1000:.3f}[{next_video}]"
            )
            filters.append(
                f"[{current_audio}][a{index}]acrossfade=d={duration:.3f}:c1=tri:c2=tri[{next_audio}]"
            )
        else:
            filters.append(f"[{current_video}][v{index}]concat=n=2:v=1:a=0[{next_video}]")
            filters.append(f"[{current_audio}][a{index}]concat=n=2:v=0:a=1[{next_audio}]")
        current_video = next_video
        current_audio = next_audio
    filters.append(f"[{current_video}]format=yuv420p[vout]")
    filters.append(f"[{current_audio}]anull[aout]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-metadata",
            f"comment=dramaforge-timeline-render:{lineage}",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    await _run(command, timeout=600.0)


async def _mix_music(
    *,
    source: Path,
    music: bytes,
    output: Path,
    volume: float,
    duration: float,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TimelineRenderError("ffmpeg executable not found")
    music_path = output.with_name("timeline-music.wav")
    music_path.write_bytes(music)
    bounded_volume = min(1.0, max(0.0, volume))
    await _run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-stream_loop",
            "-1",
            "-i",
            str(music_path),
            "-filter_complex",
            f"[1:a]volume={bounded_volume:.3f}[music];[0:a][music]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output),
        ],
        timeout=300.0,
    )


def _test_render(clips: list[TimelineRenderClip], *, lineage: str) -> TimelineRenderResult:
    digest = hashlib.sha256(lineage.encode("utf-8"))
    time_map = build_timeline_subtitles(clips)
    digest.update(json.dumps(time_map.evidence(), sort_keys=True).encode("utf-8"))
    for clip in clips:
        digest.update(clip.video_artifact_id.encode("utf-8"))
        digest.update(clip.video_bytes)
        digest.update(clip.audio_bytes or b"")
        digest.update(clip.subtitle_text.encode("utf-8"))
        digest.update(f"{clip.source_in_seconds:.3f}:{clip.duration_seconds:.3f}".encode())
    data = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + digest.digest()
    duration = time_map.duration_ms / 1000
    probe = {
        "format": {"duration": f"{duration:.3f}", "format_name": "mp4"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264"},
            {"index": 1, "codec_type": "audio", "codec_name": "aac"},
        ],
    }
    return TimelineRenderResult(
        data=data,
        ffprobe=probe,
        subtitle_data=time_map.srt_bytes,
        summary={
            "subtitle_cue_count": time_map.cue_count,
            "timeline_time_map": time_map.evidence(),
            "rendered_duration_seconds": duration,
            "subtitle_burn_applied": bool(time_map.srt_bytes),
            "test_render": True,
            "timeline_renderer": "ffmpeg-v2",
            "clip_count": len(clips),
            "subtitle_clip_count": sum(bool(clip.subtitle_text.strip()) for clip in clips),
            "audio_clip_count": sum(bool(clip.audio_bytes) for clip in clips),
        },
    )


async def render_timeline(
    clips: list[TimelineRenderClip],
    *,
    lineage: str,
    music_bytes: bytes | None = None,
    music_volume: float = 0.12,
) -> TimelineRenderResult:
    """Render the supplied Timeline edits into one playable MP4."""
    if not clips:
        raise TimelineRenderError("Timeline has no clips")
    if any(clip.source_in_seconds < 0 or clip.duration_seconds <= 0 for clip in clips):
        raise TimelineRenderError("Timeline clip trim/duration is invalid")
    try:
        time_map = build_timeline_subtitles(clips)
    except TimelineTimingError as exc:
        raise TimelineRenderError(str(exc)) from exc
    clips = [
        replace(
            clip,
            source_in_seconds=timing.source_in_ms / 1000,
            source_out_seconds=timing.source_out_ms / 1000,
            duration_seconds=timing.duration_ms / 1000,
            transition_duration_seconds=timing.overlap_ms / 1000,
        )
        for clip, timing in zip(clips, time_map.clips, strict=True)
    ]
    if get_settings().app_env == "test":
        return _test_render(clips, lineage=lineage)

    with tempfile.TemporaryDirectory(prefix="dramaforge-timeline-") as temp:
        directory = Path(temp)
        paths = [
            await _render_clip(clip, directory=directory, index=index)
            for index, clip in enumerate(clips, start=1)
        ]
        assembled = directory / "assembled.mp4"
        has_crossfade = any(clip.transition_kind == "crossfade" for clip in clips[1:])
        if has_crossfade:
            await _assemble_segments(clips, paths, output=assembled, lineage=lineage)
        else:
            await _concat_cuts(paths, output=assembled, lineage=lineage)
        duration = time_map.duration_ms / 1000
        if music_bytes:
            mixed = directory / "mixed.mp4"
            await _mix_music(
                source=assembled,
                music=music_bytes,
                output=mixed,
                volume=music_volume,
                duration=duration,
            )
            assembled = mixed
        if time_map.srt_bytes:
            subtitle = directory / "final-subtitles.srt"
            subtitle.write_bytes(time_map.srt_bytes)
            burned = directory / "subtitled.mp4"
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg is None:
                raise TimelineRenderError("ffmpeg executable not found")
            await _run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(assembled),
                    "-vf",
                    f"subtitles=filename='{_quote_subtitle_path(subtitle)}'",
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "copy",
                    "-t",
                    f"{duration:.3f}",
                    "-movflags",
                    "+faststart",
                    str(burned),
                ],
                timeout=300.0,
            )
            assembled = burned
        data = assembled.read_bytes()
        probe = await _probe(assembled)
        return TimelineRenderResult(
            data=data,
            ffprobe=probe,
            subtitle_data=time_map.srt_bytes,
            summary={
                "subtitle_cue_count": time_map.cue_count,
                "timeline_time_map": time_map.evidence(),
                "subtitle_burn_applied": bool(time_map.srt_bytes),
                "timeline_renderer": "ffmpeg-v2",
                "clip_count": len(clips),
                "crossfade": has_crossfade,
                "music_mixed": bool(music_bytes),
                "rendered_duration_seconds": round(duration, 3),
                "subtitle_clip_count": sum(bool(clip.subtitle_text.strip()) for clip in clips),
                "audio_clip_count": sum(bool(clip.audio_bytes) for clip in clips),
            },
        )


__all__ = ["TimelineRenderClip", "TimelineRenderError", "TimelineRenderResult", "render_timeline"]
