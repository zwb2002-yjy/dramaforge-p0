"""Original source locations, independent failure, and bounded local extraction."""

from __future__ import annotations

import io
import zipfile

import pytest
from app.assets import source_parser
from app.assets.source_parser import SourceParseError, parse_source


def docx(body: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body>' + body + "</w:body></w:document>",
        )
        archive.writestr("word/_rels/document.xml.rels", "https://never-follow.invalid/private")
    return stream.getvalue()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_text_retains_original_line_numbers_and_content(encoding):
    original = "地方志\r\n\r\n  古桥始建年代待考。\n用户意见：保留原貌。"
    data = original.encode(encoding)
    parsed = parse_source(filename="地方志.TXT", data=data)
    assert [item.text for item in parsed.excerpts] == [
        "地方志", "  古桥始建年代待考。", "用户意见：保留原貌。",
    ]
    assert [item.location for item in parsed.excerpts] == [{"line": 1}, {"line": 3}, {"line": 4}]
    assert data == original.encode(encoding)


def test_csv_quotes_multiline_cells_and_blank_columns_preserve_locations():
    parsed = parse_source(
        filename="资料.csv", data='人物,地点,说明\n张某,,"第一行\n第二行"'.encode(),
    )
    last = parsed.excerpts[-1]
    assert last.text == "第一行\n第二行"
    assert last.location == {"row": 2, "column": 3, "line_start": 2, "line_end": 3}
    assert parsed.excerpts[-2].text == "张某"
    assert len(parsed.excerpts) == 5


def test_tsv_keeps_commas_as_content():
    parsed = parse_source(filename="资料.tsv", data="古桥\t东,西两岸".encode())
    assert parsed.excerpts[1].text == "东,西两岸"
    assert parsed.excerpts[1].location["column"] == 2


def test_docx_paragraph_runs_and_table_cells_are_separately_addressable():
    parsed = parse_source(filename="报告.docx", data=docx(
        '<w:p/><w:p><w:r><w:t>古桥</w:t><w:tab/><w:t>现状</w:t><w:br/>'
        '<w:t>待核实</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r>'
        '<w:t>石拱</w:t></w:r></w:p></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>'
    ))
    assert parsed.excerpts[0].text == "古桥\t现状\n待核实"
    assert parsed.excerpts[0].location == {"part": "word/document.xml", "paragraph": 2}
    assert parsed.excerpts[1].location == {
        "part": "word/document.xml", "table": 1, "row": 1, "column": 1, "paragraph": 1,
    }


@pytest.mark.parametrize("filename,data,code", [
    ("scan.pdf", b"%PDF", "source_format_unsupported"),
    ("photo.png", b"image", "source_format_unsupported"),
    ("legacy.txt", b"\xff", "source_encoding_unsupported"),
    ("binary.txt", b"a\x00b", "source_binary_content"),
    ("empty.txt", b" \n", "source_no_text"),
    ("bad.csv", b'"never closed', "source_table_invalid"),
    ("bad.docx", b"not a ZIP", "source_docx_invalid"),
    ("control.docx", docx("<w:sdt/>"), "source_docx_structure_unsupported"),
])
def test_failures_do_not_fabricate_success_or_prevent_next_file(filename, data, code):
    with pytest.raises(SourceParseError) as failure:
        parse_source(filename=filename, data=data)
    assert failure.value.code == code
    assert parse_source(filename="next.txt", data=b"next file").excerpts[0].text == "next file"


@pytest.mark.parametrize("bound", ["MAX_SOURCE_BYTES", "MAX_TEXT_CHARACTERS", "MAX_LOCATIONS"])
def test_limits_fail_instead_of_silently_truncating(monkeypatch, bound):
    monkeypatch.setattr(source_parser, bound, 1)
    with pytest.raises(SourceParseError):
        parse_source(filename="long.txt", data=b"first\nsecond")


def test_docx_xml_size_is_bounded_before_expansion(monkeypatch):
    monkeypatch.setattr(source_parser, "MAX_DOCUMENT_XML_BYTES", 100)
    with pytest.raises(SourceParseError, match="source_content_limit"):
        parse_source(filename="big.docx", data=docx("<w:p>" + "a" * 10000 + "</w:p>"))


def test_docx_entities_and_duplicate_parts_are_rejected():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "secret">]><x>&a;</x>')
    with pytest.raises(SourceParseError, match="source_docx_unsafe_xml"):
        parse_source(filename="entities.docx", data=stream.getvalue())
    with pytest.warns(UserWarning), zipfile.ZipFile(stream, "a") as archive:
        archive.writestr("word/document.xml", "<x/>")
    with pytest.raises(SourceParseError, match="source_docx_invalid"):
        parse_source(filename="duplicate.docx", data=stream.getvalue())


@pytest.mark.parametrize("unsupported", [
    "<w:tbl><w:tr><w:tc><w:tbl/></w:tc></w:tr></w:tbl>",
    "<w:tbl><w:tr><w:tc><w:sdt/></w:tc></w:tr></w:tbl>",
    "<w:tbl><w:sdt><w:tr/></w:sdt></w:tbl>",
    '<w:p><mc:AlternateContent xmlns:mc="urn:compat"><mc:Choice><w:r><w:t>A</w:t>'
    '</w:r></mc:Choice><mc:Fallback><w:r><w:t>B</w:t></w:r></mc:Fallback>'
    '</mc:AlternateContent></w:p>',
    "<w:p><w:r><w:drawing><w:p><w:r><w:t>Textbox</w:t></w:r></w:p></w:drawing></w:r></w:p>",
    "<w:p><w:r><w:footnoteReference/></w:r></w:p>",
    "<w:p><w:r><w:endnoteReference/></w:r></w:p>",
    "<w:sectPr><w:headerReference/></w:sectPr>",
    "<w:sectPr><w:footerReference/></w:sectPr>",
])
def test_docx_mixed_supported_and_unsupported_content_never_reports_partial_success(unsupported):
    data = docx("<w:p><w:r><w:t>Valid body</w:t></w:r></w:p>" + unsupported)
    with pytest.raises(SourceParseError, match="source_docx_structure_unsupported"):
        parse_source(filename="mixed.docx", data=data)
