"""Bounded PDF extraction: Poppler native text first, local OCR for scanned pages.

A page without a text layer is never reported as an empty success. Encrypted or
permission-restricted documents are rejected explicitly; an owner password is never
guessed. Page ranges are the resumable block unit (``PDF_PAGES_PER_BLOCK``).
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.assets.source_processors import ocr
from app.assets.source_processors.contracts import (
    MAX_PDF_RASTER_PAGES,
    PDF_PAGES_PER_BLOCK,
    Collector,
    FragmentDraft,
    ParsedSource,
    ProcessorUse,
    SourceParseError,
    coverage,
    processor_evidence,
    processor_settings_hash,
)

PARSER_KEY = "poppler-pdftotext-v1"
PARSER_VERSION = "poppler-pdftotext-v1"
PROCESSOR_REF = "pdftotext"
TIMEOUT_SECONDS = 30
RASTER_DPI = 150


@dataclass(frozen=True)
class PdfPart:
    """One page-range block result; merges into the immutable extraction snapshot."""

    page_start: int
    page_end: int
    fragments: tuple[FragmentDraft, ...]
    pages_with_text: int
    pages_ocr: int
    omitted_pages: int
    processors: tuple[ProcessorUse, ...]
    page_count: int


def _run(
    args: list[str], *, data: bytes | None = None, timeout: int = TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            args, input=data, capture_output=True, timeout=timeout, check=False,
        )
    except FileNotFoundError:
        raise SourceParseError("source_processor_unavailable") from None
    except (OSError, subprocess.SubprocessError):
        raise SourceParseError("source_processor_unavailable") from None


def _tool_version(args: list[str], prefix: str) -> str:
    completed = _run(args, timeout=15)
    text = (completed.stderr or completed.stdout or b"").decode("utf-8", "replace")
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        raise SourceParseError("source_processor_unavailable")
    return first.removeprefix(prefix).strip() or "unknown"


def pdftotext_version() -> str:
    return _tool_version(["pdftotext", "-v"], "pdftotext version ")


def pdftotext_use() -> ProcessorUse:
    return ProcessorUse(
        ref=PROCESSOR_REF,
        engine="poppler",
        version=pdftotext_version(),
        settings_hash=processor_settings_hash({
            "format_family": "pdf",
            "encoding": "UTF-8",
            "layout": "page",
            "index_base": 0,
            "pages_per_block": PDF_PAGES_PER_BLOCK,
        }),
    )


def document_info(data: bytes) -> dict[str, object]:
    """Page count and encryption flag without rendering anything."""
    completed = _run(["pdfinfo", "-"], data=data, timeout=20)
    if completed.returncode != 0:
        raise SourceParseError("source_pdf_invalid")
    pages = 0
    encrypted = False
    for line in (completed.stdout or b"").decode("utf-8", "replace").splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "Pages":
            try:
                pages = int(value.strip())
            except ValueError:
                raise SourceParseError("source_pdf_invalid") from None
        elif key.strip() == "Encrypted" and value.strip().lower().startswith("yes"):
            encrypted = True
    if encrypted:
        # The owner password is never used to bypass document permissions.
        raise SourceParseError("source_pdf_encrypted")
    if pages <= 0:
        raise SourceParseError("source_pdf_invalid")
    return {"pages": pages, "encrypted": encrypted}


def _rasterize_page(data: bytes, page_index: int) -> bytes:
    # A single trailing ``-`` is poppler's stdout prefix; PDF input comes from stdin.
    completed = _run(
        [
            "pdftoppm", "-f", str(page_index + 1), "-l", str(page_index + 1),
            "-r", str(RASTER_DPI), "-png", "-",
        ],
        data=data,
        timeout=60,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise SourceParseError("source_pdf_render_failed")
    return completed.stdout


def _add_native_page(page_index: int, text: str, collector: Collector) -> None:
    collector.add(
        text,
        locator_kind="page_region",
        locator={
            "kind": "page_region",
            "page_start": page_index,
            "page_end": page_index + 1,
            "char_start": 0,
            "char_end": len(text),
        },
        evidence_meta={"processor": PROCESSOR_REF},
        processor_ref=PROCESSOR_REF,
    )


def _add_ocr_page(
    data: bytes, page_index: int, *, language: str, collector: Collector
) -> int:
    """OCR one rasterized page; return the number of recognized lines."""
    png = _rasterize_page(data, page_index)
    with tempfile.TemporaryDirectory(prefix="df-pdf-ocr-") as work:
        path = Path(work) / "page.png"
        path.write_bytes(png)
        lines, meta = ocr.ocr_image(path, language=language)
    for line in lines:
        collector.add(
            line.text,
            locator_kind="page_region",
            locator={
                "kind": "page_region",
                "page_start": page_index,
                "page_end": page_index + 1,
                "char_start": 0,
                "char_end": len(line.text),
                "bbox": {
                    "x": line.left,
                    "y": line.top,
                    "width": line.width,
                    "height": line.height,
                },
                "raster_dpi": RASTER_DPI,
            },
            evidence_meta={
                "processor": ocr.PROCESSOR_REF,
                "ocr_language": meta["language"],
                "confidence": line.confidence,
                "page_ocr": True,
            },
            extraction_method="ocr",
            processor_ref=ocr.PROCESSOR_REF,
        )
    return len(lines)


def parse_pdf_part(data: bytes, *, page_start: int, page_end: int) -> PdfPart:
    """Extract one half-open page range; the caller persists the block receipt."""
    if page_start < 0 or page_end <= page_start:
        raise SourceParseError("source_pdf_invalid")
    pages = page_count(data)
    if page_end > pages:
        raise SourceParseError("source_pdf_invalid")
    completed = _run(
        [
            "pdftotext", "-enc", "UTF-8", "-q",
            "-f", str(page_start + 1), "-l", str(page_end), "-", "-",
        ],
        data=data,
    )
    if completed.returncode != 0:
        raise SourceParseError("source_pdf_invalid")
    text_pages = completed.stdout.decode("utf-8", "replace").split("\f")
    if text_pages and not text_pages[-1].strip():
        text_pages = text_pages[:-1]
    if len(text_pages) < page_end - page_start:
        # Poppler omits trailing empty pages; pad explicitly so page indices stay true.
        text_pages.extend([""] * (page_end - page_start - len(text_pages)))
    collector = Collector()
    uses: list[ProcessorUse] = [pdftotext_use()]
    language = ocr.selected_language() if ocr.executable() is not None else None
    if language is not None:
        uses.append(ocr.processor_use(language))
    native_pages = 0
    ocr_pages = 0
    omitted = 0
    rasterized = 0
    for offset, text in enumerate(text_pages[: page_end - page_start]):
        page_index = page_start + offset
        if text.strip():
            _add_native_page(page_index, text, collector)
            native_pages += 1
            continue
        if language is None or rasterized >= MAX_PDF_RASTER_PAGES:
            omitted += 1
            continue
        rasterized += 1
        if _add_ocr_page(data, page_index, language=language, collector=collector):
            ocr_pages += 1
        else:
            omitted += 1
    if not collector.items:
        raise SourceParseError(
            "source_processor_unavailable" if language is None else "source_pdf_no_text_layer"
        )
    return PdfPart(
        page_start=page_start,
        page_end=page_end,
        fragments=tuple(collector.items),
        pages_with_text=native_pages,
        pages_ocr=ocr_pages,
        omitted_pages=omitted,
        processors=tuple(uses),
        page_count=pages,
    )


def merge_parts(parts: list[PdfPart], page_count: int) -> ParsedSource:
    collector = Collector()
    uses: dict[str, ProcessorUse] = {}
    native = 0
    ocr_pages = 0
    omitted = 0
    for part in parts:
        collector.extend(list(part.fragments))
        native += part.pages_with_text
        ocr_pages += part.pages_ocr
        omitted += part.omitted_pages
        for use in part.processors:
            uses.setdefault(use.ref, use)
    reasons = ["page_without_text_layer"] if omitted else []
    return ParsedSource(
        format="pdf",
        parser_key=PARSER_KEY,
        parser_version=PARSER_VERSION,
        processor_ref=PROCESSOR_REF,
        extraction_schema_version=2,
        coverage=coverage(
            page_count,
            units_processed=native + ocr_pages,
            omitted=omitted,
            omitted_reasons=reasons,
            pages_with_native_text=native,
            pages_ocr=ocr_pages,
        ),
        processor_evidence=processor_evidence(list(uses.values())),
        fragments=tuple(collector.items),
        limitations=("some pages had no text layer and were not recognized",) if omitted else (),
    )


def page_count(data: bytes) -> int:
    value = document_info(data)["pages"]
    if not isinstance(value, int):
        raise SourceParseError("source_pdf_invalid")
    return value


def page_spans(data: bytes) -> list[tuple[int, int]]:
    pages = page_count(data)
    return [
        (start, min(start + PDF_PAGES_PER_BLOCK, pages))
        for start in range(0, pages, PDF_PAGES_PER_BLOCK)
    ]


def parse_pdf(data: bytes) -> ParsedSource:
    pages = page_count(data)
    parts = [
        parse_pdf_part(data, page_start=start, page_end=min(start + PDF_PAGES_PER_BLOCK, pages))
        for start in range(0, pages, PDF_PAGES_PER_BLOCK)
    ]
    return merge_parts(parts, pages)


__all__ = [
    "PARSER_KEY",
    "PARSER_VERSION",
    "PROCESSOR_REF",
    "PdfPart",
    "document_info",
    "merge_parts",
    "page_spans",
    "parse_pdf",
    "parse_pdf_part",
    "pdftotext_use",
]
