"""Bounded local source extraction; excerpts are evidence, never inferred facts.

No network, model, storage or persistence access belongs to a parser. The caller
retains original bytes and binds these locations to a project file revision.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from xml.etree import ElementTree

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_DOCUMENT_XML_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARACTERS = 1_000_000
MAX_LOCATIONS = 20_000
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class SourceParseError(ValueError):
    """Stable, safe error for one file; callers may retry that file independently."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SourceExcerpt:
    text: str
    # One-based positions in the original file, not in a flattened text copy.
    location: dict[str, int | str]


@dataclass(frozen=True)
class ParsedSource:
    format: str
    parser_version: str
    excerpts: tuple[SourceExcerpt, ...]


class _Collector:
    def __init__(self) -> None:
        self.items: list[SourceExcerpt] = []
        self.characters = 0

    def add(self, text: str, **location: int | str) -> None:
        if not text.strip():
            return
        self.characters += len(text)
        if self.characters > MAX_TEXT_CHARACTERS or len(self.items) >= MAX_LOCATIONS:
            # Never silently drop evidence and present an incomplete file as parsed.
            raise SourceParseError("source_content_limit")
        self.items.append(SourceExcerpt(text=text, location=location))


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    except UnicodeError as exc:
        raise SourceParseError("source_encoding_unsupported") from exc
    if "\x00" in text:
        raise SourceParseError("source_binary_content")
    return text


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


def _validate_document(root: ElementTree.Element) -> None:
    """Accept only structures for which extraction preserves the source location."""
    children = {
        "document": {"body"},
        "body": {"p", "tbl", "sectPr"},
        "p": {"pPr", "r", "hyperlink", "bookmarkStart", "bookmarkEnd", "proofErr"},
        "hyperlink": {"r", "bookmarkStart", "bookmarkEnd", "proofErr"},
        "r": {"rPr", "t", "tab", "br", "cr", "lastRenderedPageBreak"},
        "tbl": {"tblPr", "tblGrid", "tr"},
        "tr": {"trPr", "tc"},
        "tc": {"tcPr", "p"},
    }
    properties = {"pPr", "rPr", "tblPr", "tblGrid", "trPr", "tcPr", "sectPr"}
    references = {"headerReference", "footerReference", "footnoteReference", "endnoteReference"}
    if any(node.tag in {_W + name for name in references} for node in root.iter()):
        raise SourceParseError("source_docx_structure_unsupported")

    def visit(node: ElementTree.Element) -> None:
        name = node.tag.removeprefix(_W)
        if name in properties:
            return  # Formatting metadata is not source prose.
        allowed = {_W + child for child in children.get(name, set())}
        for child in node:
            if child.tag not in allowed:
                raise SourceParseError("source_docx_structure_unsupported")
            visit(child)

    visit(root)


def _docx(data: bytes, collector: _Collector) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            # Read only the document part, never extract paths or resolve relationships.
            parts = [item for item in archive.infolist() if item.filename == "word/document.xml"]
            if len(parts) != 1:
                raise SourceParseError("source_docx_invalid")
            part = parts[0]
            if part.file_size > MAX_DOCUMENT_XML_BYTES or part.flag_bits & 1:
                raise SourceParseError("source_content_limit")
            with archive.open(part) as stream:
                xml = stream.read(MAX_DOCUMENT_XML_BYTES + 1)
            if len(xml) > MAX_DOCUMENT_XML_BYTES:
                raise SourceParseError("source_content_limit")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise SourceParseError("source_docx_invalid") from exc
    # XML entity expansion and external declarations are not part of accepted DOCX.
    # Reject UTF-16 XML too: normal Office XML is UTF-8, and byte checks must not
    # be bypassed with interleaved NULs. This does not restrict Unicode document text.
    if b"\x00" in xml or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise SourceParseError("source_docx_unsafe_xml")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise SourceParseError("source_docx_invalid") from exc
    body = root.find(_W + "body")
    if root.tag != _W + "document" or body is None:
        raise SourceParseError("source_docx_invalid")
    _validate_document(root)
    paragraph = 0
    table = 0
    for element in body:
        if element.tag == _W + "p":
            paragraph += 1
            collector.add(_paragraph(element), part="word/document.xml", paragraph=paragraph)
        elif element.tag == _W + "tbl":
            table += 1
            for row_index, row in enumerate(element.findall(_W + "tr"), 1):
                for column_index, cell in enumerate(row.findall(_W + "tc"), 1):
                    for cell_paragraph, content in enumerate(cell.findall(_W + "p"), 1):
                        collector.add(
                            _paragraph(content), part="word/document.xml", table=table,
                            row=row_index, column=column_index, paragraph=cell_paragraph,
                        )
        elif element.tag != _W + "sectPr":
            # Content controls/alternate content must not disappear without notice.
            raise SourceParseError("source_docx_structure_unsupported")


def parse_source(*, filename: str, data: bytes) -> ParsedSource:
    """Extract supported native text without invoking OCR or any external service."""
    if len(data) > MAX_SOURCE_BYTES:
        raise SourceParseError("source_size_limit")
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if extension not in {".txt", ".csv", ".tsv", ".docx"}:
        raise SourceParseError("source_format_unsupported")
    collector = _Collector()
    if extension == ".docx":
        _docx(data, collector)
    else:
        text = _decode(data)
        if extension == ".txt":
            for index, line in enumerate(text.splitlines(), 1):
                collector.add(line, line=index)
        else:
            reader = csv.reader(
                io.StringIO(text, newline=""), delimiter="\t" if extension == ".tsv" else ",",
                strict=True,
            )
            try:
                previous_line = 0
                for row_index, row in enumerate(reader, 1):
                    for column_index, value in enumerate(row, 1):
                        collector.add(
                            value, row=row_index, column=column_index,
                            line_start=previous_line + 1, line_end=reader.line_num,
                        )
                    previous_line = reader.line_num
            except csv.Error as exc:
                raise SourceParseError("source_table_invalid") from exc
    if not collector.items:
        raise SourceParseError("source_no_text")
    return ParsedSource(extension[1:], "native-text-v1", tuple(collector.items))
