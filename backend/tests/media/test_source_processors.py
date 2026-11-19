"""Real local processor evidence: PDF OCR, image OCR, audio ASR and video sampling.

These cases run inside the quality backend image (Tesseract with Chinese data, Poppler,
FFmpeg and a fixed whisper.cpp build plus the verified multilingual model). Nothing is
stubbed: a missing component fails the case instead of being replaced by a cloud call.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest
from app.assets.source_parser import SourceParseError, parse_source
from app.assets.source_processors import asr
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)
CHINESE_SAMPLE = "古桥始建于明代"


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    raise AssertionError("the quality image must ship a CJK font for OCR evidence")


def _text_image(text: str = CHINESE_SAMPLE, size: tuple[int, int] = (720, 180)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 40), text, fill="black", font=_font(56))
    return image


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    _text_image().save(buffer, format="PNG")
    return buffer.getvalue()


def _scanned_pdf() -> bytes:
    """An image-only PDF: no text layer, so only local OCR can read it."""
    buffer = io.BytesIO()
    _text_image().save(buffer, format="PDF", resolution=150)
    return buffer.getvalue()


def _run(args: list[str]) -> None:
    completed = subprocess.run(args, capture_output=True, check=False, timeout=120)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", "replace"))


def _speech_wav(
    tmp_path: Path, text: str = "The ancient stone bridge was built in the Ming dynasty."
) -> Path:
    path = tmp_path / "speech.wav"
    _run(["espeak-ng", "-v", "en", "-w", str(path), text])
    return path


def _silence_wav(tmp_path: Path, seconds: int = 2) -> Path:
    path = tmp_path / "silence.wav"
    _run(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            "anullsrc=r=16000:cl=mono", "-t", str(seconds), str(path),
        ]
    )
    return path


def _video(tmp_path: Path) -> Path:
    frame = tmp_path / "frame.png"
    _text_image().save(frame, format="PNG")
    speech = _speech_wav(tmp_path)
    path = tmp_path / "clip.mp4"
    _run(
        [
            "ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(frame),
            "-i", str(speech), "-t", "4", "-r", "10", "-pix_fmt", "yuv420p",
            "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest", str(path),
        ]
    )
    return path


def test_image_ocr_keeps_visual_input_and_positioned_lines():
    parsed = parse_source(filename="碑文.png", data=_png_bytes())
    assert parsed.format == "png"
    assert parsed.extraction_schema_version == 2
    visual = [item for item in parsed.fragments if item.extraction_method == "visual_input"]
    assert len(visual) == 1 and visual[0].text == ""
    assert visual[0].locator_kind == "image_region"
    assert visual[0].locator["bbox"] == {"x": 0, "y": 0, "width": 720, "height": 180}
    ocr_lines = [item for item in parsed.fragments if item.extraction_method == "ocr"]
    assert ocr_lines, "local Tesseract must read the rendered Chinese text"
    recognized = "".join(item.text for item in ocr_lines)
    assert any(character in recognized for character in "古桥明代"), recognized
    for line in ocr_lines:
        assert line.locator["bbox"]["width"] > 0
        assert line.evidence_meta["confidence"] >= 0
    processors = {item["ref"] for item in parsed.processor_evidence["processors"]}
    assert processors == {"pillow", "tesseract"}


def test_scanned_pdf_page_is_read_by_local_ocr_with_page_locator():
    parsed = parse_source(filename="扫描件.pdf", data=_scanned_pdf())
    assert parsed.format == "pdf"
    ocr_pages = [item for item in parsed.fragments if item.extraction_method == "ocr"]
    assert ocr_pages, "a scanned page must not be reported as an empty success"
    assert all(item.locator["page_start"] == 0 for item in ocr_pages)
    assert parsed.coverage["pages_ocr"] == 1
    processors = {item["ref"] for item in parsed.processor_evidence["processors"]}
    assert "pdftotext" in processors and "tesseract" in processors


def test_audio_transcript_uses_real_asr_with_time_ranges(tmp_path):
    wav = _speech_wav(tmp_path)
    parsed = parse_source(filename="访谈.wav", data=wav.read_bytes())
    assert parsed.format == "wav"
    transcripts = [item for item in parsed.fragments if item.extraction_method == "transcript"]
    assert transcripts, "a decodable speech track must produce a transcript"
    text = " ".join(item.text for item in transcripts).lower()
    assert "bridge" in text
    for item in transcripts:
        assert item.locator_kind == "time_range"
        assert item.locator["end_ms"] > item.locator["start_ms"]
        assert item.evidence_meta["machine_transcript"] is True
    assert parsed.coverage["windows"] >= 1
    model = next(
        item for item in parsed.processor_evidence["processors"] if item["ref"] == asr.PROCESSOR_REF
    )
    assert model["model_sha256"] == asr.DEFAULT_MODEL_SHA256


def test_silence_never_becomes_invented_dialogue(tmp_path):
    wav = _silence_wav(tmp_path)
    parsed = parse_source(filename="静音.wav", data=wav.read_bytes())
    assert [item for item in parsed.fragments if item.extraction_method == "transcript"] == []
    assert "no_speech_detected" in parsed.limitations
    assert parsed.coverage["complete"] is True


def test_video_keeps_time_base_samples_frames_and_transcribes_audio(tmp_path):
    clip = _video(tmp_path)
    parsed = parse_source(filename="记录片.mp4", data=clip.read_bytes())
    assert parsed.format == "mp4"
    transcripts = [item for item in parsed.fragments if item.extraction_method == "transcript"]
    frames = [item for item in parsed.fragments if item.extraction_method == "visual_input"]
    assert transcripts and "bridge" in " ".join(item.text for item in transcripts).lower()
    assert frames, "sampled frames are addressable visual input"
    for frame in frames:
        assert frame.locator_kind == "image_region"
        assert 0 <= frame.locator["time_ms"] <= 4000
    assert parsed.coverage["sampled_frames"] == len(frames)
    assert parsed.coverage["duration_ms"] >= 3000


def test_missing_asr_component_is_explicit(monkeypatch, tmp_path):
    wav = _speech_wav(tmp_path)
    monkeypatch.setattr(asr, "executable", lambda: None)
    with pytest.raises(SourceParseError) as failure:
        parse_source(filename="访谈.wav", data=wav.read_bytes())
    assert failure.value.code == "source_processor_unavailable"


def test_model_identity_mismatch_is_refused(monkeypatch, tmp_path):
    wav = _speech_wav(tmp_path)
    monkeypatch.setenv("DRAMAFORGE_WHISPER_MODEL_SHA256", "0" * 64)
    with pytest.raises(SourceParseError) as failure:
        parse_source(filename="访谈.wav", data=wav.read_bytes())
    assert failure.value.code == "source_model_identity_mismatch"
