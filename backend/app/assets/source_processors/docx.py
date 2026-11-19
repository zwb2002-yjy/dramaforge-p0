"""Bounded DOCX body/table/footnote/endnote/header/footer extraction.

Only whitelisted package parts are read. Macros, external relationships, embedded
objects, content controls and alternate content are never executed: unsupported
structure is an explicit failure instead of silently missing prose.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

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

PARSER_KEY = "native-text-v1"
PARSER_VERSION = "native-docx-v1"
PROCESSOR_REF = "native-text-v1"
CONVERSION = "native-text-v1-to-schema2"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_STRUCTURE = {
    "document": {"body"},
    "body": {"p", "tbl", "sectPr"},
    "hdr": {"p", "tbl", "sectPr"},
    "ftr": {"p", "tbl", "sectPr"},
    "footnotes": {"footnote"},
    "endnotes": {"endnote"},
    "footnote": {"p", "tbl"},
    "endnote": {"p", "tbl"},
    "p": {"pPr", "r", "hyperlink", "bookmarkStart", "bookmarkEnd", "proofErr"},
    "hyperlink": {"r", "bookmarkStart", "bookmarkEnd", "proofErr"},
    "r": {
        "rPr", "t", "tab", "br", "cr", "lastRenderedPageBreak",
        "footnoteReference", "endnoteReference",
    },
    "tbl": {"tblPr", "tblGrid", "tr"},
    "tr": {"trPr", "tc"},
    "tc": {"tcPr", "p"},
}
_PROPERTIES = {"pPr", "rPr", "tblPr", "tblGrid", "trPr", "tcPr", "sectPr"}
_SKIPPED_NOTE_TYPES = {"separator", "continuationSeparator", "continuationNotice"}


def _paragraph(element: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in element.iter():
        if node.tag == _W + "t":
            parts.append(node.text or "")
        elif node.tag == _W + "tab":
            parts.append("\t")
        elif node.tag in {_W + "br", _W + "cr"}:
            parts.append("\n")
    return "".join(parts)


def _validate(root: ElementTree.Element) -> None:
    """Accept only structures for which extraction preserves the source location."""

    def visit(node: ElementTree.Element) -> None:
        name = node.tag.removeprefix(_W)
        if name in _PROPERTIES:
            return  # Formatting metadata is not source prose.
        allowed = {_W + child for child in _STRUCTURE.get(name, set())}
        for child in node:
            if child.tag not in allowed:
                raise SourceParseError("source_docx_structure_unsupported")
            visit(child)

    visit(root)


def _read_part(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise SourceParseError("source_docx_invalid") from exc
    if info.file_size > contracts.MAX_DOCUMENT_XML_BYTES or info.flag_bits & 1:
        raise SourceParseError("source_content_limit")
    with archive.open(info) as stream:
        xml = stream.read(contracts.MAX_DOCUMENT_XML_BYTES + 1)
    if len(xml) > contracts.MAX_DOCUMENT_XML_BYTES:
        raise SourceParseError("source_content_limit")
    # XML entity expansion and external declarations are not part of accepted DOCX.
    # Reject UTF-16 XML too: normal Office XML is UTF-8, and byte checks must not be
    # bypassed with interleaved NULs. This does not restrict Unicode document text.
    if b"\x00" in xml or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise SourceParseError("source_docx_unsafe_xml")
    return xml


def _parse_xml(xml: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise SourceParseError("source_docx_invalid") from exc


def _archive(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise SourceParseError("source_docx_invalid") from exc
    infos = archive.infolist()
    if len(infos) > contracts.MAX_ARCHIVE_PARTS:
        raise SourceParseError("source_content_limit")
    uncompressed = sum(item.file_size for item in infos)
    compressed = sum(item.compress_size for item in infos) or 1
    if (
        uncompressed > contracts.MAX_ARCHIVE_UNCOMPRESSED_BYTES
        or uncompressed // compressed > contracts.MAX_ARCHIVE_RATIO
    ):
        raise SourceParseError("source_content_limit")
    if any(item.flag_bits & 1 for item in infos):
        raise SourceParseError("source_docx_invalid")
    names = [item.filename for item in infos]
    if len(names) != len(set(names)):
        # Duplicate parts make the read ambiguous; never pick one silently.
        raise SourceParseError("source_docx_invalid")
    return archive


def _body_units(
    container: ElementTree.Element,
    *,
    part_path: str,
    container_key: str,
    collector: Collector,
) -> int:
    paragraph = 0
    table = 0
    units = 0
    for element in container:
        if element.tag == _W + "p":
            paragraph += 1
            units += 1
            text = _paragraph(element)
            collector.add(
                text,
                locator_kind="paragraph",
                locator={
                    "kind": "paragraph",
                    "part_path": part_path,
                    "container_key": container_key,
                    "paragraph_start": paragraph - 1,
                    "paragraph_end": paragraph,
                    "char_start": 0,
                    "char_end": len(text),
                },
                evidence_meta={
                    "original_location": {"part": part_path, "container": container_key,
                                          "paragraph": paragraph},
                    "conversion": CONVERSION,
                },
                processor_ref=PROCESSOR_REF,
            )
        elif element.tag == _W + "tbl":
            table += 1
            table_key = f"table:{table - 1}"
            if container_key != "body":
                table_key = f"{container_key}/{table_key}"
            for row_index, row in enumerate(element.findall(_W + "tr"), 1):
                for column_index, cell in enumerate(row.findall(_W + "tc"), 1):
                    for cell_paragraph, content in enumerate(cell.findall(_W + "p"), 1):
                        units += 1
                        text = _paragraph(content)
                        collector.add(
                            text,
                            locator_kind="table_cells",
                            locator={
                                "kind": "table_cells",
                                "part_path": part_path,
                                "container_key": table_key,
                                "cell_paragraph": cell_paragraph - 1,
                                "row_start": row_index - 1,
                                "row_end": row_index,
                                "column_start": column_index - 1,
                                "column_end": column_index,
                            },
                            evidence_meta={
                                "original_location": {
                                    "part": part_path,
                                    "container": container_key,
                                    "table": table,
                                    "row": row_index,
                                    "column": column_index,
                                    "paragraph": cell_paragraph,
                                },
                                "conversion": CONVERSION,
                            },
                            processor_ref=PROCESSOR_REF,
                        )
        elif element.tag != _W + "sectPr":
            # Content controls/alternate content must not disappear without notice.
            raise SourceParseError("source_docx_structure_unsupported")
    return units


def _notes(
    root: ElementTree.Element,
    *,
    part_path: str,
    kind: str,
    collector: Collector,
) -> int:
    units = 0
    for note in root:
        if note.tag != _W + kind:
            raise SourceParseError("source_docx_structure_unsupported")
        note_type = note.get(_W + "type")
        if note_type in _SKIPPED_NOTE_TYPES:
            continue
        note_id = note.get(_W + "id") or "unknown"
        units += _body_units(
            note,
            part_path=part_path,
            container_key=f"{kind}:{note_id}",
            collector=collector,
        )
    return units


def _referenced_parts(root: ElementTree.Element) -> set[str]:
    """Which optional containers the body actually references, by fixed package name."""
    needed: set[str] = set()
    for node in root.iter():
        name = node.tag.removeprefix(_W)
        if name == "footnoteReference":
            needed.add("footnotes")
        elif name == "endnoteReference":
            needed.add("endnotes")
        elif name == "headerReference":
            needed.add("header")
        elif name == "footerReference":
            needed.add("footer")
    return needed


def _part_names(archive: zipfile.ZipFile, prefix: str) -> list[str]:
    names = [
        item.filename
        for item in archive.infolist()
        if item.filename.startswith(prefix)
        and item.filename.count("/") == 1
        and item.filename.endswith(".xml")
    ]
    return sorted(names)


def parse_docx(data: bytes) -> ParsedSource:
    archive = _archive(data)
    with archive:
        document_xml = _read_part(archive, "word/document.xml")
        root = _parse_xml(document_xml)
        body = root.find(_W + "body")
        if root.tag != _W + "document" or body is None:
            raise SourceParseError("source_docx_invalid")
        _validate(root)
        collector = Collector()
        units = _body_units(
            body, part_path="word/document.xml", container_key="body", collector=collector
        )
        parts_used = ["word/document.xml"]
        needed = _referenced_parts(root)
        if "footnotes" in needed:
            notes_root = _parse_xml(_read_part(archive, "word/footnotes.xml"))
            _validate(notes_root)
            units += _notes(
                notes_root,
                part_path="word/footnotes.xml",
                kind="footnote",
                collector=collector,
            )
            parts_used.append("word/footnotes.xml")
        if "endnotes" in needed:
            notes_root = _parse_xml(_read_part(archive, "word/endnotes.xml"))
            _validate(notes_root)
            units += _notes(
                notes_root,
                part_path="word/endnotes.xml",
                kind="endnote",
                collector=collector,
            )
            parts_used.append("word/endnotes.xml")
        for family in ("header", "footer"):
            if family not in needed:
                continue
            names = _part_names(archive, f"word/{family}")
            if not names:
                # A dangling reference would lose the referenced prose.
                raise SourceParseError("source_docx_structure_unsupported")
            for name in names:
                part_root = _parse_xml(_read_part(archive, name))
                _validate(part_root)
                units += _body_units(
                    part_root,
                    part_path=name,
                    container_key=f"{family}:{name.rsplit('/', 1)[-1].removesuffix('.xml')}",
                    collector=collector,
                )
                parts_used.append(name)
    if not collector.items:
        raise SourceParseError("source_no_text")
    use = ProcessorUse(
        ref=PROCESSOR_REF,
        engine="python-stdlib",
        version=PARSER_VERSION,
        settings_hash=processor_settings_hash({
            "format_family": "docx",
            "index_base": 0,
            "max_document_xml_bytes": contracts.MAX_DOCUMENT_XML_BYTES,
        }),
    )
    return ParsedSource(
        format="docx",
        parser_key=PARSER_KEY,
        parser_version=PARSER_VERSION,
        processor_ref=PROCESSOR_REF,
        extraction_schema_version=2,
        coverage=coverage(units, parts=parts_used),
        processor_evidence=processor_evidence([use]),
        fragments=tuple(collector.items),
    )


__all__ = ["PARSER_KEY", "PARSER_VERSION", "PROCESSOR_REF", "parse_docx"]
