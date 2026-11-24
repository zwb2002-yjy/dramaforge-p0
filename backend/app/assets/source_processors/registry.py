"""Format registry: one capability table, real component probing, one parse entry.

The registry is the only place that decides which local processor handles a file and
what the current bounded processing profile is. Capability answers come from the actual
installed components, never from the file extension alone, and a missing component is
reported instead of being replaced by a cloud service.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TypedDict

from app.assets.source_processors import (
    asr,
    contracts,
    docx,
    images,
    media,
    native_text,
    ocr,
    pdf,
    tables,
)
from app.assets.source_processors.contracts import (
    EXTRACTION_SCHEMA_VERSION,
    ParsedSource,
    SourceParseError,
)

PROFILE_SCHEMA_VERSION = 1

TEXT_EXTENSIONS = (".txt",)
DELIMITED_EXTENSIONS = (".csv", ".tsv")
DOCX_EXTENSIONS = (".docx",)
PDF_EXTENSIONS = (".pdf",)
XLSX_EXTENSIONS = (".xlsx",)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")
AUDIO_EXTENSIONS = tuple(sorted(media.AUDIO_EXTENSIONS))
VIDEO_EXTENSIONS = tuple(sorted(media.VIDEO_EXTENSIONS))
REFUSED_EXTENSIONS = (".doc", ".xls", ".ppt", ".rtf", ".gif", ".bmp")


@dataclass(frozen=True)
class FormatProfile:
    format: str
    extensions: tuple[str, ...]
    supported_processing: tuple[str, ...]
    limitations: tuple[str, ...]
    max_bytes: int = contracts.MAX_SOURCE_BYTES
    max_duration_ms: int | None = None
    max_pixels: int | None = None


class CapabilityFormat(TypedDict):
    """Read-only capability answer for one format family."""

    format: str
    extensions: list[str]
    available: bool
    max_bytes: int
    max_duration_ms: int | None
    max_pixels: int | None
    supported_processing: list[str]
    limitations: list[str]


class Capabilities(TypedDict):
    profile_revision: str
    formats: list[CapabilityFormat]
    components: dict[str, bool]
    auto_analysis: dict[str, object]


FORMATS: tuple[FormatProfile, ...] = (
    FormatProfile(
        format="txt",
        extensions=TEXT_EXTENSIONS,
        supported_processing=("native_text",),
        limitations=("utf-8_or_utf-16_only",),
    ),
    FormatProfile(
        format="csv",
        extensions=(".csv",),
        supported_processing=("native_text",),
        limitations=("utf-8_or_utf-16_only", "single_sheet"),
    ),
    FormatProfile(
        format="tsv",
        extensions=(".tsv",),
        supported_processing=("native_text",),
        limitations=("utf-8_or_utf-16_only", "single_sheet"),
    ),
    FormatProfile(
        format="docx",
        extensions=DOCX_EXTENSIONS,
        supported_processing=("native_text",),
        limitations=("macros_and_embedded_objects_unsupported",),
    ),
    FormatProfile(
        format="pdf",
        extensions=PDF_EXTENSIONS,
        supported_processing=("native_text", "ocr"),
        limitations=("page_block_processing", "no_owner_password_bypass"),
    ),
    FormatProfile(
        format="xlsx",
        extensions=XLSX_EXTENSIONS,
        supported_processing=("native_text",),
        limitations=("formula_cache_not_recalculated", "no_macro_execution"),
    ),
    FormatProfile(
        format="image",
        extensions=IMAGE_EXTENSIONS,
        supported_processing=("ocr", "visual_input"),
        limitations=("sampled_pixels_not_full_semantics",),
        max_pixels=contracts.MAX_IMAGE_PIXELS,
    ),
    FormatProfile(
        format="audio",
        extensions=AUDIO_EXTENSIONS,
        supported_processing=("transcript",),
        limitations=("machine_transcript_not_verbatim", "windowed_asr"),
        max_duration_ms=contracts.MAX_MEDIA_DURATION_MS,
    ),
    FormatProfile(
        format="video",
        extensions=VIDEO_EXTENSIONS,
        supported_processing=("transcript", "ocr", "visual_input"),
        limitations=("sampled_frames_not_frame_by_frame", "windowed_asr"),
        max_duration_ms=contracts.MAX_MEDIA_DURATION_MS,
    ),
)

_EXTENSION_INDEX = {extension: profile for profile in FORMATS for extension in profile.extensions}

_MAGIC = {
    "pdf": (b"%PDF",),
    "docx": (b"PK\x03\x04",),
    "xlsx": (b"PK\x03\x04",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "tif": (b"II*\x00", b"MM\x00*"),
    "tiff": (b"II*\x00", b"MM\x00*"),
}


def _components() -> dict[str, bool]:
    """Actual component availability; a false answer is never silently upgraded."""
    pdf_ready = shutil.which("pdftotext") is not None and shutil.which("pdfinfo") is not None
    ocr_ready = ocr.executable() is not None
    if ocr_ready:
        try:
            ocr.selected_language()
        except SourceParseError:
            ocr_ready = False
    media_ready = (
        shutil.which("ffmpeg") is not None
        and shutil.which("ffprobe") is not None
        and asr.executable() is not None
        and asr.model_path() is not None
    )
    return {
        "native_text": True,
        "docx": True,
        "pdf_text": pdf_ready,
        "pdf_ocr": pdf_ready and ocr_ready,
        "xlsx": importlib.util.find_spec("openpyxl") is not None,
        "image_ocr": ocr_ready,
        "audio_transcript": media_ready,
        "video_transcript": media_ready,
        "video_frames": ocr_ready,
    }


def _format_available(profile: FormatProfile, components: dict[str, bool]) -> bool:
    if profile.format in {"txt", "csv", "tsv", "docx"}:
        return True
    if profile.format == "pdf":
        return components["pdf_text"]
    if profile.format == "xlsx":
        return components["xlsx"]
    if profile.format == "image":
        return components["image_ocr"]
    if profile.format == "audio":
        return components["audio_transcript"]
    if profile.format == "video":
        return components["audio_transcript"] or components["video_frames"]
    return False


def _profile_payload() -> dict[str, object]:
    """Stable configuration identity: limits, formats and processor refs, no probing."""
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "extraction_schema_version": EXTRACTION_SCHEMA_VERSION,
        "limits": {
            "max_source_bytes": contracts.MAX_SOURCE_BYTES,
            "max_text_characters": contracts.MAX_TEXT_CHARACTERS,
            "max_locations": contracts.MAX_LOCATIONS,
            "max_image_pixels": contracts.MAX_IMAGE_PIXELS,
            "max_media_duration_ms": contracts.MAX_MEDIA_DURATION_MS,
            "audio_window_ms": contracts.AUDIO_WINDOW_MS,
            "pdf_pages_per_block": contracts.PDF_PAGES_PER_BLOCK,
        },
        "formats": [
            {
                "format": profile.format,
                "extensions": list(profile.extensions),
                "supported_processing": list(profile.supported_processing),
                "limitations": list(profile.limitations),
            }
            for profile in FORMATS
        ],
        "processors": {
            "native_text": native_text.PARSER_VERSION,
            "docx": docx.PARSER_VERSION,
            "pdf": pdf.PARSER_VERSION,
            "xlsx": tables.PARSER_VERSION,
            "image": images.PARSER_VERSION,
            "media": media.PARSER_VERSION,
            "ocr": ocr.PROCESSOR_REF,
            "asr": asr.PROCESSOR_REF,
        },
    }


def processor_profile_revision() -> str:
    """64-char lowercase hex identity of the current processor contract."""
    payload = json.dumps(
        _profile_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def source_capabilities() -> Capabilities:
    """Read-only capability answer: zero parsing, zero model calls, no fabricated tools."""
    components = _components()
    formats: list[CapabilityFormat] = []
    for profile in FORMATS:
        formats.append(
            CapabilityFormat(
                format=profile.format,
                extensions=list(profile.extensions),
                available=_format_available(profile, components),
                max_bytes=profile.max_bytes,
                max_duration_ms=profile.max_duration_ms,
                max_pixels=profile.max_pixels,
                supported_processing=list(profile.supported_processing),
                limitations=list(profile.limitations),
            )
        )
    return Capabilities(
        profile_revision=processor_profile_revision(),
        formats=formats,
        components=components,
        auto_analysis={
            "enabled": False,
            "requires_confirmation": True,
            "blockers": ["research_analysis_not_wired"],
        },
    )


def detect_format(filename: str, data: bytes) -> str:
    """Extension plus magic check; a disguised file never reaches the wrong parser."""
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if extension in REFUSED_EXTENSIONS:
        raise SourceParseError("source_format_unsupported")
    profile = _EXTENSION_INDEX.get(extension)
    if profile is None:
        raise SourceParseError("source_format_unsupported")
    expected = _MAGIC.get(extension.removeprefix("."))
    if expected is not None and not data.startswith(expected):
        raise SourceParseError("source_format_mismatch")
    if extension in (".webp",) and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise SourceParseError("source_format_mismatch")
    return profile.format


def parse_source(*, filename: str, data: bytes) -> ParsedSource:
    """Single local parse entry used by the worker and the read path."""
    if len(data) > contracts.MAX_SOURCE_BYTES:
        raise SourceParseError("source_size_limit")
    fmt = detect_format(filename, data)
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if fmt in {"txt", "csv", "tsv"}:
        return native_text.parse_native(extension, data)
    if fmt == "docx":
        return docx.parse_docx(data)
    if fmt == "pdf":
        return pdf.parse_pdf(data)
    if fmt == "xlsx":
        return tables.parse_xlsx(data)
    if fmt == "image":
        return images.parse_image(data)
    if fmt in {"audio", "video"}:
        return media.parse_media(data, extension=extension)
    raise SourceParseError("source_format_unsupported")


__all__ = [
    "FORMATS",
    "FormatProfile",
    "REFUSED_EXTENSIONS",
    "detect_format",
    "parse_source",
    "processor_profile_revision",
    "source_capabilities",
]
