"""Local image extraction: verified decode, orientation, bounded pixels, local OCR.

An image without recognized text is still an addressable visual input (the later,
explicitly authorized Vision step may interpret it). It never fabricates OCR text and
never calls a cloud OCR service.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.assets.source_processors import ocr
from app.assets.source_processors.contracts import (
    MAX_IMAGE_FRAMES,
    MAX_IMAGE_PIXELS,
    Collector,
    ParsedSource,
    ProcessorUse,
    SourceParseError,
    coverage,
    processor_evidence,
    processor_settings_hash,
)

PARSER_KEY = "pillow-tesseract-v1"
PARSER_VERSION = "pillow-tesseract-v1"
PROCESSOR_REF = "pillow"
IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "TIFF"}


def _pillow_version() -> str:
    return getattr(Image, "__version__", "unknown")


def _prepared_frames(
    data: bytes,
) -> tuple[list[tuple[int, int, int, bytes, dict[str, object]]], str]:
    """Return (frame index, width, height, PNG bytes, transform evidence) per frame."""
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    frames: list[tuple[int, int, int, bytes, dict[str, object]]] = []
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise SourceParseError("source_image_invalid") from exc
    except Image.DecompressionBombError as exc:
        raise SourceParseError("source_content_limit") from exc
    fmt = image.format or ""
    if fmt not in IMAGE_FORMATS:
        raise SourceParseError("source_format_unsupported")
    count = int(getattr(image, "n_frames", 1) or 1)
    if count > MAX_IMAGE_FRAMES:
        raise SourceParseError("source_content_limit")
    try:
        for index in range(count):
            if count > 1:
                image.seek(index)
            oriented = ImageOps.exif_transpose(image)
            width, height = oriented.size
            if width * height > MAX_IMAGE_PIXELS:
                raise SourceParseError("source_content_limit")
            exif = image.getexif()
            orientation = int(exif.get(0x0112, 1)) if exif else 1
            if oriented.mode in {"RGBA", "LA", "P"}:
                # Transparent regions are white paper for OCR, never black holes.
                rgba = oriented.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.split()[-1])
                rgb = background
            else:
                rgb = oriented.convert("RGB")
            with tempfile.SpooledTemporaryFile() as buffer:
                rgb.save(buffer, format="PNG")
                buffer.seek(0)
                png = buffer.read()
            frames.append(
                (
                    index,
                    width,
                    height,
                    png,
                    {
                        "exif_orientation": orientation,
                        "orientation_applied": orientation != 1,
                        "pixel_size": [width, height],
                    },
                )
            )
    except SourceParseError:
        raise
    except (OSError, ValueError) as exc:
        raise SourceParseError("source_image_invalid") from exc
    finally:
        image.close()
    return frames, fmt


def parse_image(data: bytes) -> ParsedSource:
    if ocr.executable() is None:
        raise SourceParseError("source_processor_unavailable")
    language = ocr.selected_language()
    frames, fmt = _prepared_frames(data)
    collector = Collector()
    uses: dict[str, ProcessorUse] = {
        PROCESSOR_REF: ProcessorUse(
            ref=PROCESSOR_REF,
            engine="pillow",
            version=_pillow_version(),
            settings_hash=processor_settings_hash({
                "format_family": "image",
                "max_pixels": MAX_IMAGE_PIXELS,
                "index_base": 0,
            }),
        ),
        ocr.PROCESSOR_REF: ocr.processor_use(language),
    }
    lines_total = 0
    frames_with_text = 0
    for index, width, height, png, transform in frames:
        collector.add(
            "",
            locator_kind="image_region",
            locator={
                "kind": "image_region",
                "frame": index,
                "bbox": {"x": 0, "y": 0, "width": width, "height": height},
                "image_width": width,
                "image_height": height,
                "char_start": 0,
                "char_end": 0,
            },
            evidence_meta={"processor": PROCESSOR_REF, **transform},
            extraction_method="visual_input",
            processor_ref=PROCESSOR_REF,
            keep_empty=True,
        )
        with tempfile.TemporaryDirectory(prefix="df-image-") as work:
            path = Path(work) / "frame.png"
            path.write_bytes(png)
            lines, meta = ocr.ocr_image(path, language=language)
        if lines:
            frames_with_text += 1
        for line in lines:
            lines_total += 1
            collector.add(
                line.text,
                locator_kind="image_region",
                locator={
                    "kind": "image_region",
                    "frame": index,
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
                    **transform,
                },
                extraction_method="ocr",
                processor_ref=ocr.PROCESSOR_REF,
            )
    return ParsedSource(
        format=fmt.lower(),
        parser_key=PARSER_KEY,
        parser_version=PARSER_VERSION,
        processor_ref=PROCESSOR_REF,
        extraction_schema_version=2,
        coverage=coverage(
            len(frames),
            frames=len(frames),
            frames_with_ocr_text=frames_with_text,
            ocr_lines=lines_total,
        ),
        processor_evidence=processor_evidence(list(uses.values())),
        fragments=tuple(collector.items),
        limitations=() if lines_total else ("no_ocr_text",),
    )


__all__ = ["IMAGE_FORMATS", "PARSER_KEY", "PARSER_VERSION", "PROCESSOR_REF", "parse_image"]
