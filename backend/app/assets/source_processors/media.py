"""Bounded audio/video extraction: FFprobe/FFmpeg plus local whisper.cpp and OCR.

Audio is transcribed in fixed 30 s windows with a 1 s alignment overlap; the overlap is
never counted twice. Video keeps its own time base, transcribes the audio track and
samples bounded key frames for OCR/visual input. Silence, music and noise never become
invented dialogue, and sampling is reported as sampling, not frame-by-frame review.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from app.assets.source_processors import asr, ocr
from app.assets.source_processors.contracts import (
    AUDIO_WINDOW_MS,
    AUDIO_WINDOW_OVERLAP_MS,
    MAX_MEDIA_DURATION_MS,
    MAX_MEDIA_WINDOWS,
    MAX_VIDEO_FRAMES,
    MEDIA_TIMEOUT_SECONDS,
    Collector,
    ParsedSource,
    ProcessorUse,
    SourceParseError,
    coverage,
    processor_evidence,
    processor_settings_hash,
)

PARSER_KEY = "ffmpeg-whisper-tesseract-v1"
PARSER_VERSION = "ffmpeg-whisper-tesseract-v1"
PROCESSOR_REF = "ffmpeg"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}
SAMPLE_RATE = 16_000
FRAME_MAX_WIDTH = 1280


@dataclass(frozen=True)
class MediaInfo:
    duration_ms: int
    has_audio: bool
    has_video: bool
    width: int | None
    height: int | None
    rotation: int


def _run(
    args: list[str], *, timeout: int = MEDIA_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError:
        raise SourceParseError("source_processor_unavailable") from None
    except (OSError, subprocess.SubprocessError):
        raise SourceParseError("source_processor_unavailable") from None


def _tool_version(binary: str) -> str:
    completed = _run([binary, "-version"], timeout=20)
    first = (completed.stdout or b"").decode("utf-8", "replace").splitlines()
    if not first:
        raise SourceParseError("source_processor_unavailable")
    return first[0].strip()


def ffmpeg_use() -> ProcessorUse:
    return ProcessorUse(
        ref=PROCESSOR_REF,
        engine="ffmpeg",
        version=_tool_version("ffmpeg"),
        settings_hash=processor_settings_hash({
            "format_family": "media",
            "sample_rate": SAMPLE_RATE,
            "window_ms": AUDIO_WINDOW_MS,
            "index_base": 0,
        }),
    )


def probe(path: Path) -> MediaInfo:
    completed = _run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        timeout=60,
    )
    if completed.returncode != 0:
        raise SourceParseError("source_media_invalid")
    try:
        payload = json.loads(completed.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise SourceParseError("source_media_invalid") from exc
    streams = payload.get("streams") or []
    audio = [item for item in streams if item.get("codec_type") == "audio"]
    video = [item for item in streams if item.get("codec_type") == "video"]
    try:
        duration_ms = int(float((payload.get("format") or {}).get("duration") or 0) * 1000)
    except (TypeError, ValueError):
        raise SourceParseError("source_media_invalid") from None
    if duration_ms <= 0:
        raise SourceParseError("source_media_invalid")
    if duration_ms > MAX_MEDIA_DURATION_MS:
        raise SourceParseError("source_duration_limit")
    width = height = None
    rotation = 0
    if video:
        width = int(video[0].get("width") or 0) or None
        height = int(video[0].get("height") or 0) or None
        for side_data in video[0].get("side_data_list") or []:
            if "rotation" in side_data:
                rotation = int(float(side_data["rotation"]))
    return MediaInfo(
        duration_ms=duration_ms,
        has_audio=bool(audio),
        has_video=bool(video),
        width=width,
        height=height,
        rotation=rotation,
    )


def _decode_audio(source: Path, target: Path) -> None:
    completed = _run(
        [
            "ffmpeg", "-v", "error", "-nostdin", "-y",
            "-i", str(source), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-f", "wav", str(target),
        ]
    )
    if completed.returncode != 0 or not target.exists():
        raise SourceParseError("source_media_decode_failed")


def _window_spans(duration_ms: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    while start < duration_ms and len(spans) < MAX_MEDIA_WINDOWS:
        end = min(start + AUDIO_WINDOW_MS, duration_ms)
        spans.append((start, end))
        if end >= duration_ms:
            break
        start = end - AUDIO_WINDOW_OVERLAP_MS
    if duration_ms > 0 and len(spans) >= MAX_MEDIA_WINDOWS:
        last_end = spans[-1][1]
        if last_end < duration_ms:
            raise SourceParseError("source_content_limit")
    return spans


def _transcribe_windows(
    wav_path: Path,
    *,
    duration_ms: int,
    collector: Collector,
    time_offset_ms: int = 0,
) -> tuple[int, int]:
    """Transcribe bounded windows; return (windows processed, windows with speech)."""
    spans = _window_spans(duration_ms)
    with wave.open(str(wav_path), "rb") as source:
        if source.getframerate() != SAMPLE_RATE or source.getnchannels() != 1:
            raise SourceParseError("source_media_decode_failed")
        total_frames = source.getnframes()
        with_speech = 0
        for index, (start_ms, end_ms) in enumerate(spans):
            start_frame = int(start_ms * SAMPLE_RATE / 1000)
            end_frame = min(int(end_ms * SAMPLE_RATE / 1000), total_frames)
            source.setpos(start_frame)
            frames = source.readframes(max(0, end_frame - start_frame))
            if not frames:
                continue
            with tempfile.TemporaryDirectory(prefix="df-media-") as work:
                window_path = Path(work) / "window.wav"
                with wave.open(str(window_path), "wb") as window:
                    window.setnchannels(1)
                    window.setsampwidth(2)
                    window.setframerate(SAMPLE_RATE)
                    window.writeframes(frames)
                segments = asr.transcribe(window_path)
            added = 0
            for segment in segments:
                absolute_start = start_ms + segment.start_ms
                if index > 0 and absolute_start < start_ms + AUDIO_WINDOW_OVERLAP_MS // 2:
                    # The overlapping second already belongs to the previous window.
                    continue
                absolute_end = max(start_ms + segment.end_ms, absolute_start + 1)
                collector.add(
                    segment.text,
                    locator_kind="time_range",
                    locator={
                        "kind": "time_range",
                        "start_ms": absolute_start + time_offset_ms,
                        "end_ms": absolute_end + time_offset_ms,
                        "char_start": 0,
                        "char_end": len(segment.text),
                        "window_index": index,
                    },
                    evidence_meta={
                        "processor": asr.PROCESSOR_REF,
                        "machine_transcript": True,
                        "window_start_ms": start_ms,
                        "window_end_ms": end_ms,
                    },
                    extraction_method="transcript",
                    processor_ref=asr.PROCESSOR_REF,
                )
                added += 1
            if added:
                with_speech += 1
    return len(spans), with_speech


def _sample_times(duration_ms: int) -> list[int]:
    minutes = max(1, (duration_ms + 59_999) // 60_000)
    count = min(MAX_VIDEO_FRAMES, minutes)
    step = duration_ms / (count + 1)
    return [int(step * (index + 1)) for index in range(count)]


def _frame_png(source: Path, time_ms: int) -> bytes:
    completed = _run(
        [
            "ffmpeg", "-v", "error", "-nostdin",
            "-ss", f"{time_ms / 1000:.3f}", "-i", str(source),
            "-frames:v", "1", "-vf", f"scale='min({FRAME_MAX_WIDTH},iw)':-2",
            "-f", "image2pipe", "-vcodec", "png", "pipe:1",
        ],
        timeout=120,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise SourceParseError("source_media_decode_failed")
    return completed.stdout


def _video_frames(
    source: Path,
    info: MediaInfo,
    collector: Collector,
    *,
    language: str | None,
) -> tuple[int, int]:
    """Sample bounded frames; return (frames sampled, frames with OCR text)."""
    times = _sample_times(info.duration_ms)
    width = info.width or 0
    height = info.height or 0
    with_text = 0
    for index, time_ms in enumerate(times):
        png = _frame_png(source, time_ms)
        collector.add(
            "",
            locator_kind="image_region",
            locator={
                "kind": "image_region",
                "frame": index,
                "time_ms": time_ms,
                "bbox": {"x": 0, "y": 0, "width": width, "height": height},
                "image_width": width,
                "image_height": height,
                "char_start": 0,
                "char_end": 0,
            },
            evidence_meta={
                "processor": PROCESSOR_REF,
                "sampled_frame": True,
                "rotation": info.rotation,
            },
            extraction_method="visual_input",
            processor_ref=PROCESSOR_REF,
            keep_empty=True,
        )
        if language is None:
            continue
        with tempfile.TemporaryDirectory(prefix="df-video-") as work:
            path = Path(work) / "frame.png"
            path.write_bytes(png)
            lines, meta = ocr.ocr_image(path, language=language)
        if lines:
            with_text += 1
        for line in lines:
            collector.add(
                line.text,
                locator_kind="image_region",
                locator={
                    "kind": "image_region",
                    "frame": index,
                    "time_ms": time_ms,
                    "bbox": {
                        "x": line.left,
                        "y": line.top,
                        "width": line.width,
                        "height": line.height,
                    },
                    "image_width": width,
                    "image_height": height,
                    "char_start": 0,
                    "char_end": len(line.text),
                },
                evidence_meta={
                    "processor": ocr.PROCESSOR_REF,
                    "ocr_language": meta["language"],
                    "confidence": line.confidence,
                    "sampled_frame": True,
                    "rotation": info.rotation,
                },
                extraction_method="ocr",
                processor_ref=ocr.PROCESSOR_REF,
            )
    return len(times), with_text


def parse_media(data: bytes, *, extension: str) -> ParsedSource:
    if extension not in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS:
        raise SourceParseError("source_format_unsupported")
    if asr.executable() is None:
        raise SourceParseError("source_processor_unavailable")
    language = ocr.selected_language() if ocr.executable() is not None else None
    uses: dict[str, ProcessorUse] = {PROCESSOR_REF: ffmpeg_use()}
    if language is not None:
        uses[ocr.PROCESSOR_REF] = ocr.processor_use(language)
    collector = Collector()
    with tempfile.TemporaryDirectory(prefix="df-media-") as work:
        source = Path(work) / f"source{extension}"
        source.write_bytes(data)
        info = probe(source)
        if not info.has_audio and not info.has_video:
            raise SourceParseError("source_media_invalid")
        if info.has_audio:
            # A verified model identity is required only when audio is transcribed.
            _model_path, model_digest = asr.require_model()
            uses[asr.PROCESSOR_REF] = ProcessorUse(
                ref=asr.PROCESSOR_REF,
                engine="whisper.cpp",
                version=asr.version(),
                model_sha256=model_digest,
                settings_hash=processor_settings_hash({
                    "model_sha256": model_digest,
                    "language": asr.DEFAULT_LANGUAGE,
                    "window_ms": AUDIO_WINDOW_MS,
                    "overlap_ms": AUDIO_WINDOW_OVERLAP_MS,
                }),
            )
        windows = 0
        windows_with_speech = 0
        frames = 0
        frames_with_text = 0
        if info.has_audio:
            wav_path = Path(work) / "audio.wav"
            _decode_audio(source, wav_path)
            windows, windows_with_speech = _transcribe_windows(
                wav_path, duration_ms=info.duration_ms, collector=collector
            )
        if info.has_video:
            frames, frames_with_text = _video_frames(
                source, info, collector, language=language
            )
    limitations: list[str] = []
    if not info.has_audio:
        limitations.append("no_audio_track")
    if info.has_video and language is None:
        limitations.append("frame_ocr_unavailable")
    if windows and not windows_with_speech:
        limitations.append("no_speech_detected")
    return ParsedSource(
        format=extension[1:],
        parser_key=PARSER_KEY,
        parser_version=PARSER_VERSION,
        processor_ref=PROCESSOR_REF,
        extraction_schema_version=2,
        coverage=coverage(
            windows + frames,
            windows=windows,
            windows_with_speech=windows_with_speech,
            sampled_frames=frames,
            frames_with_ocr_text=frames_with_text,
            duration_ms=info.duration_ms,
            audio_track=info.has_audio,
            video_track=info.has_video,
        ),
        processor_evidence=processor_evidence(list(uses.values())),
        fragments=tuple(collector.items),
        limitations=tuple(limitations),
    )


__all__ = [
    "AUDIO_EXTENSIONS",
    "PARSER_KEY",
    "PARSER_VERSION",
    "PROCESSOR_REF",
    "VIDEO_EXTENSIONS",
    "parse_media",
    "probe",
]
