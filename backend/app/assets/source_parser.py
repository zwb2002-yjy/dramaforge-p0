"""Public source-extraction façade over the same-domain local processors.

Callers (HTTP read path, extraction worker) keep using this module; the format work
lives in ``app.assets.source_processors``. No network, model, storage or persistence
access belongs to a processor: the caller retains the original bytes and binds the
returned fragments to an immutable ``SourceExtraction`` snapshot of one revision.

Locators are schema 2 (zero-based, half-open). Historical ``native-text-v1`` positions
were one-based; the conversion subtracts exactly one and keeps the original location as
evidence instead of reinterpreting the number.
"""

from __future__ import annotations

from app.assets.source_processors.contracts import (
    EXTRACTION_METHODS,
    LOCATOR_KINDS,
    MAX_DOCUMENT_XML_BYTES,
    MAX_LOCATIONS,
    MAX_SOURCE_BYTES,
    MAX_TEXT_CHARACTERS,
    FragmentDraft,
    ParsedSource,
    SourceParseError,
)
from app.assets.source_processors.registry import (
    FORMATS,
    detect_format,
    parse_source,
    processor_profile_revision,
    source_capabilities,
)

# Kept as module-level names for the existing HTTP/worker callers and their tests.
__all__ = [
    "EXTRACTION_METHODS",
    "FORMATS",
    "FragmentDraft",
    "LOCATOR_KINDS",
    "MAX_DOCUMENT_XML_BYTES",
    "MAX_LOCATIONS",
    "MAX_SOURCE_BYTES",
    "MAX_TEXT_CHARACTERS",
    "ParsedSource",
    "SourceParseError",
    "detect_format",
    "parse_source",
    "processor_profile_revision",
    "source_capabilities",
]
