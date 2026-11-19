"""Shared local processor contract: bounded output, schema-2 locators, real identity.

A processor never performs network, database, storage or model work. It receives the
immutable original bytes and returns addressable fragments plus the actual local tool
identity that produced them. A missing component is an explicit failure
(``source_processor_unavailable``); there is no cloud fallback and no fabricated hash.

Locators are schema 2: half-open, zero-based ranges in the original document's own
coordinate system (text lines, table rows/columns, package parts, page regions, image
regions, milliseconds). Human-facing one-based display is a UI concern and must not be
applied twice.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

# Current upload cap shared by HTTP admission and the worker. The larger target
# processing profile requires streaming storage admission first (ARCHITECTURE D4).
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_DOCUMENT_XML_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARACTERS = 2_000_000
MAX_LOCATIONS = 50_000

MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_FRAMES = 200
# Current CPU profile: bounded so one file stays inside the worker's local budget.
# The 60-minute target profile needs block-level ASR receipts first (ARCHITECTURE D4).
MAX_MEDIA_DURATION_MS = 10 * 60 * 1000
MAX_PDF_PAGES = 500
PDF_PAGES_PER_BLOCK = 25
MAX_PDF_RASTER_PAGES = 40
MAX_TABLE_CELLS = 200_000
MAX_ARCHIVE_PARTS = 2_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_RATIO = 200

AUDIO_WINDOW_MS = 30_000
AUDIO_WINDOW_OVERLAP_MS = 1_000
MAX_MEDIA_WINDOWS = 24
MAX_VIDEO_FRAMES = 12
OCR_MIN_CONFIDENCE = 30.0
OCR_TIMEOUT_SECONDS = 180
ASR_TIMEOUT_SECONDS = 600
MEDIA_TIMEOUT_SECONDS = 300

EXTRACTION_SCHEMA_VERSION = 2

# Locator kinds accepted by ``source_fragments.locator_kind``.
LOCATOR_KINDS = ("paragraph", "page_region", "image_region", "time_range", "table_cells")
# Extraction methods accepted by ``source_fragments.extraction_method``.
EXTRACTION_METHODS = ("native_text", "ocr", "transcript", "visual_input", "metadata")


class SourceParseError(ValueError):
    """Stable, safe error for one file; callers may retry that file independently."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FragmentDraft:
    """One addressable span; ``locator`` is schema 2 (zero-based, half-open)."""

    ordinal: int
    locator_kind: str
    locator: dict[str, object]
    text: str
    evidence_meta: dict[str, object]
    extraction_method: str = "native_text"
    processor_ref: str = "native-text-v1"


@dataclass(frozen=True)
class ProcessorUse:
    """The actual local tool/model used for one part of an extraction."""

    ref: str
    engine: str
    version: str
    network_mode: str = "local"
    settings_hash: str | None = None
    binary_sha256: str | None = None
    model_sha256: str | None = None
    invocation_id: str | None = None
    operation_id: str | None = None

    def evidence(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ref": self.ref,
            "engine": self.engine,
            "version": self.version,
            "network_mode": self.network_mode,
        }
        if self.settings_hash:
            payload["settings_hash"] = self.settings_hash
        if self.binary_sha256:
            payload["binary_sha256"] = self.binary_sha256
        if self.model_sha256:
            payload["model_sha256"] = self.model_sha256
        if self.invocation_id:
            payload["invocation_id"] = self.invocation_id
        if self.operation_id:
            payload["operation_id"] = self.operation_id
        return payload


def processor_settings_hash(payload: dict[str, object]) -> str:
    """Stable identity of one processor's settings; never a fabricated version."""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ParsedSource:
    format: str
    parser_key: str
    parser_version: str
    processor_ref: str
    extraction_schema_version: int
    coverage: dict[str, object]
    processor_evidence: dict[str, object]
    fragments: tuple[FragmentDraft, ...]
    limitations: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class BlockSpan:
    """One bounded unit of work that can be retried or resumed on its own."""

    index: int
    start: int
    end: int
    unit: str


def processor_evidence(
    uses: list[ProcessorUse], *, coordinate_system: dict[str, object] | None = None
) -> dict[str, object]:
    """Fixed processor-evidence shape; only processors actually used are listed."""
    return {
        "schema_version": 1,
        "processors": [use.evidence() for use in uses],
        "coordinate_system": coordinate_system
        or {"index_base": 0, "bbox_origin": "top_left"},
    }


def coverage(
    units_total: int,
    *,
    units_processed: int | None = None,
    omitted: int = 0,
    omitted_reasons: list[str] | None = None,
    **extra: object,
) -> dict[str, object]:
    """Every discovered unit is processed unless a reason is recorded explicitly."""
    processed = units_total if units_processed is None else units_processed
    complete = omitted == 0 and processed == units_total
    payload: dict[str, object] = {
        "schema_version": 1,
        "units_total": units_total,
        "units_processed": processed,
        "omitted_units": omitted,
        "omitted_reasons": list(omitted_reasons or []),
        "complete": complete,
    }
    payload.update(extra)
    return payload


class Collector:
    """Ordered fragments with hard output bounds; limits fail instead of truncating."""

    def __init__(self, *, allow_empty_text: bool = False) -> None:
        self.items: list[FragmentDraft] = []
        self.characters = 0
        self.allow_empty_text = allow_empty_text

    def add(
        self,
        text: str,
        *,
        locator_kind: str,
        locator: dict[str, object],
        evidence_meta: dict[str, object] | None = None,
        extraction_method: str = "native_text",
        processor_ref: str = "native-text-v1",
        keep_empty: bool = False,
    ) -> None:
        if not text.strip() and not (keep_empty or self.allow_empty_text):
            return
        if locator_kind not in LOCATOR_KINDS:
            raise ValueError(f"Unknown locator kind: {locator_kind}")
        if extraction_method not in EXTRACTION_METHODS:
            raise ValueError(f"Unknown extraction method: {extraction_method}")
        self.characters += len(text)
        if self.characters > MAX_TEXT_CHARACTERS or len(self.items) >= MAX_LOCATIONS:
            # Never silently drop evidence and present an incomplete file as parsed.
            raise SourceParseError("source_content_limit")
        self.items.append(
            FragmentDraft(
                ordinal=len(self.items),
                locator_kind=locator_kind,
                locator=locator,
                text=text,
                evidence_meta=evidence_meta or {},
                extraction_method=extraction_method,
                processor_ref=processor_ref,
            )
        )

    def extend(self, fragments: list[FragmentDraft]) -> None:
        for fragment in fragments:
            self.add(
                fragment.text,
                locator_kind=fragment.locator_kind,
                locator=fragment.locator,
                evidence_meta=fragment.evidence_meta,
                extraction_method=fragment.extraction_method,
                processor_ref=fragment.processor_ref,
                keep_empty=True,
            )

    def __bool__(self) -> bool:
        return bool(self.items)
