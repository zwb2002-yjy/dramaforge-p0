"""Read-only XLSX extraction with sheet/cell coordinates and honest formula handling.

The workbook is never calculated, no macro runs and no external link is opened.
A formula cell exposes the formula as source text and the cached value only as
evidence; a missing cache is unknown, never "current truth". A declared dimension
that hides cells does not silently truncate the sheet.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, time
from xml.etree import ElementTree

from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.utils.exceptions import InvalidFileException  # type: ignore[import-untyped]

from app.assets.source_processors import contracts
from app.assets.source_processors.contracts import (
    Collector,
    ParsedSource,
    ProcessorUse,
    SourceParseError,
    coverage,
    processor_evidence,
    processor_settings_hash,
)

PARSER_KEY = "openpyxl-xlsx-v1"
PARSER_VERSION = "openpyxl-xlsx-v1"
PROCESSOR_REF = "openpyxl"
CONVERSION = "xlsx-native-v1-to-schema2"

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _checked_archive(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise SourceParseError("source_xlsx_invalid") from exc
    infos = archive.infolist()
    if len(infos) > contracts.MAX_ARCHIVE_PARTS:
        raise SourceParseError("source_content_limit")
    uncompressed = sum(item.file_size for item in infos)
    compressed = sum(item.compress_size for item in infos) or 1
    if (
        uncompressed > contracts.MAX_ARCHIVE_UNCOMPRESSED_BYTES
        or uncompressed // compressed > contracts.MAX_ARCHIVE_RATIO
        or any(item.flag_bits & 1 for item in infos)
    ):
        raise SourceParseError("source_xlsx_invalid")
    names = [item.filename for item in infos]
    if len(names) != len(set(names)):
        raise SourceParseError("source_xlsx_invalid")
    return archive


def _read_part(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise SourceParseError("source_xlsx_invalid") from exc
    if info.file_size > contracts.MAX_DOCUMENT_XML_BYTES:
        raise SourceParseError("source_content_limit")
    with archive.open(info) as stream:
        payload = stream.read(contracts.MAX_DOCUMENT_XML_BYTES + 1)
    if len(payload) > contracts.MAX_DOCUMENT_XML_BYTES:
        raise SourceParseError("source_content_limit")
    if b"\x00" in payload or b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise SourceParseError("source_xlsx_unsafe_xml")
    return payload


def _sheet_parts(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Ordered (sheet name, package part) pairs from the workbook's own metadata."""
    workbook = ElementTree.fromstring(_read_part(archive, "xl/workbook.xml"))
    rels = ElementTree.fromstring(_read_part(archive, "xl/_rels/workbook.xml.rels"))
    targets = {
        rel.get("Id"): rel.get("Target", "")
        for rel in rels.findall(f"{_PKG_REL}Relationship")
    }
    pairs: list[tuple[str, str]] = []
    sheets = workbook.find(f"{_MAIN}sheets")
    if sheets is None:
        raise SourceParseError("source_xlsx_invalid")
    for sheet in sheets.findall(f"{_MAIN}sheet"):
        name = sheet.get("name") or ""
        rel_id = sheet.get(f"{_REL}id") or ""
        target = targets.get(rel_id, "")
        if not name or not target:
            raise SourceParseError("source_xlsx_invalid")
        part = target.lstrip("/")
        if not part.startswith("xl/"):
            part = f"xl/{part}"
        pairs.append((name, part.replace("/./", "/")))
    return pairs


def _merged_ranges(archive: zipfile.ZipFile, part: str) -> list[str]:
    """Merge ranges straight from the sheet XML; read-only mode does not expose them."""
    try:
        root = ElementTree.fromstring(_read_part(archive, part))
    except ElementTree.ParseError as exc:
        raise SourceParseError("source_xlsx_invalid") from exc
    merged = root.find(f"{_MAIN}mergeCells")
    if merged is None:
        return []
    cells = merged.findall(f"{_MAIN}mergeCell")
    return [item.get("ref") or "" for item in cells if item.get("ref")]


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _json_value(value: object) -> object:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def parse_xlsx(data: bytes) -> ParsedSource:
    archive = _checked_archive(data)
    with archive:
        parts = _sheet_parts(archive)
        merged = {name: _merged_ranges(archive, part) for name, part in parts}
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
        cached = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise SourceParseError("source_xlsx_invalid") from exc
    collector = Collector()
    cells = 0
    try:
        for name in workbook.sheetnames:
            sheet = workbook[name]
            sheet_cached = cached[name] if name in cached.sheetnames else None
            # Ignore the declared dimension so hidden cells are not silently dropped.
            sheet.reset_dimensions()
            if sheet_cached is not None:
                sheet_cached.reset_dimensions()
            cached_rows = (
                sheet_cached.iter_rows(values_only=True) if sheet_cached is not None else None
            )
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                cached_row = next(cached_rows, ()) if cached_rows is not None else ()
                for column_index, value in enumerate(row):
                    if value is None:
                        continue
                    cells += 1
                    if cells > contracts.MAX_TABLE_CELLS:
                        raise SourceParseError("source_content_limit")
                    cached_value = (
                        cached_row[column_index] if column_index < len(cached_row) else None
                    )
                    is_formula = isinstance(value, str) and value.startswith("=")
                    evidence: dict[str, object] = {
                        "original_location": {
                            "sheet": name,
                            "row": row_index + 1,
                            "column": column_index + 1,
                        },
                        "conversion": CONVERSION,
                    }
                    if is_formula:
                        evidence["formula"] = value
                        evidence["cached_known"] = cached_value is not None
                        evidence["cached_value"] = _json_value(cached_value)
                    collector.add(
                        _cell_text(value),
                        locator_kind="table_cells",
                        locator={
                            "kind": "table_cells",
                            "sheet": name,
                            "row_start": row_index,
                            "row_end": row_index + 1,
                            "column_start": column_index,
                            "column_end": column_index + 1,
                        },
                        evidence_meta=evidence,
                        processor_ref=PROCESSOR_REF,
                    )
    finally:
        workbook.close()
        cached.close()
    if not collector.items:
        raise SourceParseError("source_no_text")
    merged_total = sum(len(items) for items in merged.values())
    use = ProcessorUse(
        ref=PROCESSOR_REF,
        engine="openpyxl",
        version=_version(),
        settings_hash=processor_settings_hash({
            "format_family": "xlsx",
            "read_only": True,
            "data_only": "two_pass",
            "index_base": 0,
        }),
    )
    return ParsedSource(
        format="xlsx",
        parser_key=PARSER_KEY,
        parser_version=PARSER_VERSION,
        processor_ref=PROCESSOR_REF,
        extraction_schema_version=2,
        coverage=coverage(
            len(parts),
            cells_total=cells,
            merged_ranges=merged_total,
            sheets=[name for name, _part in parts],
        ),
        processor_evidence=processor_evidence([use]),
        fragments=tuple(collector.items),
    )


def _version() -> str:
    from importlib.metadata import version

    try:
        return version("openpyxl")
    except Exception:  # pragma: no cover - metadata always present in the image
        return "unknown"


__all__ = ["PARSER_KEY", "PARSER_VERSION", "PROCESSOR_REF", "parse_xlsx"]
