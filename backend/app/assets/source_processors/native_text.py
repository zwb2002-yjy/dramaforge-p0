"""Native text and delimited-table processors (TXT/CSV/TSV), stdlib only."""

from __future__ import annotations

import csv
import io

from app.assets.source_processors import contracts
from app.assets.source_processors.contracts import (
    Collector,
    FragmentDraft,
    ParsedSource,
    ProcessorUse,
    SourceParseError,
    coverage,
    processor_evidence,
    processor_settings_hash,
)

PARSER_KEY = "native-text-v1"
PARSER_VERSION = "native-text-v1"
PROCESSOR_REF = "native-text-v1"
TABLE_SHEET = "data"
CONVERSION = "native-text-v1-to-schema2"


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    except UnicodeError as exc:
        raise SourceParseError("source_encoding_unsupported") from exc
    if "\x00" in text:
        raise SourceParseError("source_binary_content")
    return text


def text_lines(text: str, collector: Collector) -> int:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        collector.add(
            line,
            locator_kind="paragraph",
            locator={
                "kind": "paragraph",
                "container_key": "text-lines",
                "paragraph_start": index,
                "paragraph_end": index + 1,
                "char_start": 0,
                "char_end": len(line),
            },
            evidence_meta={"original_location": {"line": index + 1}, "conversion": CONVERSION},
            processor_ref=PROCESSOR_REF,
        )
    return len(lines)


def table_rows(text: str, delimiter: str, collector: Collector) -> int:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        previous_line = 0
        row_index = 0
        for row in reader:
            for column_index, value in enumerate(row, 1):
                collector.add(
                    value,
                    locator_kind="table_cells",
                    locator={
                        "kind": "table_cells",
                        "sheet": TABLE_SHEET,
                        "row_start": row_index,
                        "row_end": row_index + 1,
                        "column_start": column_index - 1,
                        "column_end": column_index,
                    },
                    evidence_meta={
                        "original_location": {
                            "row": row_index + 1,
                            "column": column_index,
                            "line_start": previous_line + 1,
                            "line_end": reader.line_num,
                        },
                        "conversion": CONVERSION,
                    },
                    processor_ref=PROCESSOR_REF,
                )
            previous_line = reader.line_num
            row_index += 1
    except csv.Error as exc:
        raise SourceParseError("source_table_invalid") from exc
    return row_index


def _evidence(use: ProcessorUse) -> dict[str, object]:
    return processor_evidence([use])


def parse_native(filename_extension: str, data: bytes) -> ParsedSource:
    """Extract native text without OCR, model calls or any external service."""
    collector = Collector()
    use = ProcessorUse(
        ref=PROCESSOR_REF,
        engine="python-stdlib",
        version=PARSER_VERSION,
        settings_hash=processor_settings_hash({
            "format_family": "native-text",
            "encoding": "utf-8-or-utf-16",
            "index_base": 0,
            "max_text_characters": contracts.MAX_TEXT_CHARACTERS,
            "max_locations": contracts.MAX_LOCATIONS,
        }),
    )
    text = _decode(data)
    if filename_extension == ".txt":
        units = text_lines(text, collector)
    else:
        units = table_rows(text, "\t" if filename_extension == ".tsv" else ",", collector)
    if not collector.items:
        raise SourceParseError("source_no_text")
    return ParsedSource(
        format=filename_extension[1:],
        parser_key=PARSER_KEY,
        parser_version=PARSER_VERSION,
        processor_ref=PROCESSOR_REF,
        extraction_schema_version=2,
        coverage=coverage(units),
        processor_evidence=_evidence(use),
        fragments=tuple(collector.items),
    )


def fragments_of(collector: Collector) -> tuple[FragmentDraft, ...]:
    return tuple(collector.items)


__all__ = [
    "CONVERSION",
    "PARSER_KEY",
    "PARSER_VERSION",
    "PROCESSOR_REF",
    "TABLE_SHEET",
    "fragments_of",
    "parse_native",
    "table_rows",
    "text_lines",
]
