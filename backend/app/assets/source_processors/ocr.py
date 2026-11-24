"""Local Tesseract CLI adapter: bounded, offline, with real identity and positions.

The adapter never downloads language data and never calls a cloud OCR service. A
missing binary or language pack is an explicit ``source_processor_unavailable``.
Confidence is recorded for review only; it is not a historical-accuracy score.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.assets.source_processors.contracts import (
    OCR_TIMEOUT_SECONDS,
    ProcessorUse,
    SourceParseError,
    processor_settings_hash,
)

PROCESSOR_REF = "tesseract"
_LANGUAGE_PREFERENCE = ("chi_sim+eng", "chi_sim", "eng")


def processor_use(language: str) -> ProcessorUse:
    """The actual Tesseract identity used for one extraction."""
    return ProcessorUse(
        ref=PROCESSOR_REF,
        engine="tesseract",
        version=version(),
        settings_hash=processor_settings_hash({
            "language": language,
            "psm": 3,
            "index_base": 0,
            "timeout_seconds": OCR_TIMEOUT_SECONDS,
        }),
    )


@dataclass(frozen=True)
class OcrLine:
    """One recognized text line with pixel geometry in the oriented image."""

    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float
    block: int
    paragraph: int
    line: int


def _run(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except FileNotFoundError:
        raise SourceParseError("source_processor_unavailable") from None
    except (OSError, subprocess.SubprocessError):
        raise SourceParseError("source_processor_unavailable") from None


def version() -> str:
    completed = _run(["tesseract", "--version"], timeout=15)
    text = (completed.stdout or completed.stderr or b"").decode("utf-8", "replace")
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        raise SourceParseError("source_processor_unavailable")
    return first.removeprefix("tesseract ").strip()


def available_languages() -> set[str]:
    completed = _run(["tesseract", "--list-langs"], timeout=20)
    text = (completed.stdout or completed.stderr or b"").decode("utf-8", "replace")
    return {line.strip() for line in text.splitlines()[1:] if line.strip()}


def selected_language() -> str:
    installed = available_languages()
    for candidate in _LANGUAGE_PREFERENCE:
        parts = candidate.split("+")
        if all(part in installed for part in parts):
            return candidate
    raise SourceParseError("source_processor_unavailable")


def _join_words(words: list[str]) -> str:
    """Join TSV words without inventing spaces inside CJK runs."""
    text = ""
    for word in words:
        if not word:
            continue
        if text and text[-1].isascii() and text[-1].isalnum() and word[0].isascii() and (
            word[0].isalnum()
        ):
            text += " "
        text += word
    return text


def ocr_image(image_path: Path, *, language: str) -> tuple[list[OcrLine], dict[str, object]]:
    """Recognize one prepared PNG file and return lines plus processor evidence."""
    with tempfile.TemporaryDirectory(prefix="df-ocr-") as work:
        out_base = Path(work) / "out"
        completed = _run(
            [
                "tesseract",
                str(image_path),
                str(out_base),
                "-l",
                language,
                "--psm",
                "3",
                "tsv",
            ],
            timeout=OCR_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise SourceParseError("source_ocr_failed")
        tsv = Path(f"{out_base}.tsv")
        if not tsv.exists():
            raise SourceParseError("source_ocr_failed")
        raw = tsv.read_text(encoding="utf-8", errors="replace")
    lines: list[OcrLine] = []
    grouped: dict[tuple[int, int, int, int], list[list[str]]] = {}
    for row in raw.splitlines()[1:]:
        fields = row.split("\t")
        if len(fields) < 12 or fields[0] != "5":
            continue
        key = (int(fields[1]), int(fields[2]), int(fields[3]), int(fields[4]))
        grouped.setdefault(key, []).append(fields)
    for (_page, block, paragraph, line), words in grouped.items():
        text = _join_words([fields[11] for fields in words])
        if not text.strip():
            continue
        left = min(int(fields[6]) for fields in words)
        top = min(int(fields[7]) for fields in words)
        right = max(int(fields[6]) + int(fields[8]) for fields in words)
        bottom = max(int(fields[7]) + int(fields[9]) for fields in words)
        confidences = [float(fields[10]) for fields in words if fields[10] not in {"-1", ""}]
        confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
        lines.append(
            OcrLine(
                text=text,
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
                confidence=confidence,
                block=block,
                paragraph=paragraph,
                line=line,
            )
        )
    return lines, {"language": language, "psm": 3, "page": 1}


def executable() -> str | None:
    return shutil.which("tesseract")


__all__ = [
    "OcrLine",
    "PROCESSOR_REF",
    "available_languages",
    "executable",
    "ocr_image",
    "processor_use",
    "selected_language",
    "version",
]
