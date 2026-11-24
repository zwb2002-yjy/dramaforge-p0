"""Original source locations, independent failure, and bounded local extraction."""

from __future__ import annotations

import io
import zipfile

import pytest
from app.assets.source_parser import SourceParseError, parse_source
from app.assets.source_processors import contracts, registry


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
    assert [item.text for item in parsed.fragments] == [
        "地方志", "  古桥始建年代待考。", "用户意见：保留原貌。",
    ]
    # Schema 2 is half-open and zero based; the one-based source line stays evidence.
    assert [item.locator for item in parsed.fragments] == [
        {"kind": "paragraph", "container_key": "text-lines", "paragraph_start": 0,
         "paragraph_end": 1, "char_start": 0, "char_end": 3},
        {"kind": "paragraph", "container_key": "text-lines", "paragraph_start": 2,
         "paragraph_end": 3, "char_start": 0, "char_end": len("  古桥始建年代待考。")},
        {"kind": "paragraph", "container_key": "text-lines", "paragraph_start": 3,
         "paragraph_end": 4, "char_start": 0, "char_end": len("用户意见：保留原貌。")},
    ]
    assert [item.locator_kind for item in parsed.fragments] == ["paragraph"] * 3
    assert [item.evidence_meta["original_location"] for item in parsed.fragments] == [
        {"line": 1}, {"line": 3}, {"line": 4},
    ]
    assert data == original.encode(encoding)


def test_character_ranges_count_code_points_not_bytes_or_utf16_units():
    text = "🎭古桥"
    parsed = parse_source(filename="emoji.txt", data=text.encode())
    fragment = parsed.fragments[0]
    assert fragment.locator["char_end"] == 3 == len(text)


def test_csv_quotes_multiline_cells_and_blank_columns_preserve_locations():
    parsed = parse_source(
        filename="资料.csv", data='人物,地点,说明\n张某,,"第一行\n第二行"'.encode(),
    )
    last = parsed.fragments[-1]
    assert last.text == "第一行\n第二行"
    assert last.locator == {
        "kind": "table_cells", "sheet": "data",
        "row_start": 1, "row_end": 2, "column_start": 2, "column_end": 3,
    }
    assert last.locator_kind == "table_cells"
    assert last.evidence_meta["original_location"] == {
        "row": 2, "column": 3, "line_start": 2, "line_end": 3,
    }
    assert parsed.fragments[-2].text == "张某"
    assert len(parsed.fragments) == 5
    assert parsed.coverage["units_total"] == 2 and parsed.coverage["units_processed"] == 2
    assert parsed.coverage["complete"] is True


def test_tsv_keeps_commas_as_content():
    parsed = parse_source(filename="资料.tsv", data="古桥\t东,西两岸".encode())
    assert parsed.fragments[1].text == "东,西两岸"
    assert parsed.fragments[1].locator["column_start"] == 1
    assert parsed.fragments[1].locator["column_end"] == 2


def test_docx_paragraph_runs_and_table_cells_are_separately_addressable():
    parsed = parse_source(filename="报告.docx", data=docx(
        '<w:p/><w:p><w:r><w:t>古桥</w:t><w:tab/><w:t>现状</w:t><w:br/>'
        '<w:t>待核实</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r>'
        '<w:t>石拱</w:t></w:r></w:p></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>'
    ))
    assert parsed.fragments[0].text == "古桥\t现状\n待核实"
    assert parsed.fragments[0].locator == {
        "kind": "paragraph", "part_path": "word/document.xml", "container_key": "body",
        "paragraph_start": 1, "paragraph_end": 2, "char_start": 0,
        "char_end": len("古桥\t现状\n待核实"),
    }
    assert parsed.fragments[1].locator == {
        "kind": "table_cells", "part_path": "word/document.xml", "container_key": "table:0",
        "cell_paragraph": 0, "row_start": 0, "row_end": 1, "column_start": 0, "column_end": 1,
    }
    assert parsed.fragments[1].evidence_meta["original_location"] == {
        "part": "word/document.xml", "container": "body",
        "table": 1, "row": 1, "column": 1, "paragraph": 1,
    }


def test_processor_evidence_declares_a_real_local_processor_and_zero_base():
    parsed = parse_source(filename="来源.txt", data=b"evidence")
    assert parsed.extraction_schema_version == 2
    assert parsed.parser_key == "native-text-v1"
    evidence = parsed.processor_evidence
    assert evidence["coordinate_system"] == {"index_base": 0, "bbox_origin": "top_left"}
    processor = evidence["processors"][0]
    assert processor["ref"] == "native-text-v1" and processor["network_mode"] == "local"
    assert len(processor["settings_hash"]) == 64


@pytest.mark.parametrize("filename,data,code", [
    ("scan.pdf", b"%PDF", "source_pdf_invalid"),
    ("photo.png", b"image", "source_format_mismatch"),
    ("legacy.doc", b"\xd0\xcf\x11\xe0", "source_format_unsupported"),
    ("sheet.xls", b"\xd0\xcf\x11\xe0", "source_format_unsupported"),
    ("clip.gif", b"GIF89a", "source_format_unsupported"),
    ("legacy.txt", b"\xff", "source_encoding_unsupported"),
    ("binary.txt", b"a\x00b", "source_binary_content"),
    ("empty.txt", b" \n", "source_no_text"),
    ("bad.csv", b'"never closed', "source_table_invalid"),
    ("bad.docx", b"not a ZIP", "source_format_mismatch"),
    ("control.docx", docx("<w:sdt/>"), "source_docx_structure_unsupported"),
])
def test_failures_do_not_fabricate_success_or_prevent_next_file(filename, data, code):
    with pytest.raises(SourceParseError) as failure:
        parse_source(filename=filename, data=data)
    assert failure.value.code == code
    assert parse_source(filename="next.txt", data=b"next file").fragments[0].text == "next file"


@pytest.mark.parametrize("bound", ["MAX_SOURCE_BYTES", "MAX_TEXT_CHARACTERS", "MAX_LOCATIONS"])
def test_limits_fail_instead_of_silently_truncating(monkeypatch, bound):
    monkeypatch.setattr(contracts, bound, 1)
    with pytest.raises(SourceParseError):
        parse_source(filename="long.txt", data=b"first\nsecond")


def test_docx_xml_size_is_bounded_before_expansion(monkeypatch):
    monkeypatch.setattr(contracts, "MAX_DOCUMENT_XML_BYTES", 100)
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
])
def test_docx_mixed_supported_and_unsupported_content_never_reports_partial_success(unsupported):
    data = docx("<w:p><w:r><w:t>Valid body</w:t></w:r></w:p>" + unsupported)
    with pytest.raises(SourceParseError, match="source_docx_structure_unsupported"):
        parse_source(filename="mixed.docx", data=data)


def _docx_parts(parts: dict[str, str]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return stream.getvalue()


def test_docx_footnotes_headers_and_footers_are_addressable_parts():
    body = (
        '<w:p><w:r><w:t>正文</w:t><w:footnoteReference w:id="1"/></w:r></w:p>'
        '<w:sectPr><w:headerReference w:type="default" r:id="rId4"/>'
        '<w:footerReference w:type="default" r:id="rId5"/></w:sectPr>'
    )
    data = _docx_parts({
        "word/document.xml": (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<w:body>" + body + "</w:body></w:document>"
        ),
        "word/footnotes.xml": (
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:footnote w:type="separator" w:id="-1"/>'
            '<w:footnote w:id="1"><w:p><w:r><w:t>脚注内容</w:t></w:r></w:p></w:footnote>'
            "</w:footnotes>"
        ),
        "word/header1.xml": (
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:p><w:r><w:t>页眉</w:t></w:r></w:p></w:hdr>'
        ),
        "word/footer1.xml": (
            '<w:ftr xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:p><w:r><w:t>页脚</w:t></w:r></w:p></w:ftr>'
        ),
    })
    parsed = parse_source(filename="报告.docx", data=data)
    assert [item.text for item in parsed.fragments] == ["正文", "脚注内容", "页眉", "页脚"]
    containers = [item.locator["container_key"] for item in parsed.fragments]
    assert containers == ["body", "footnote:1", "header:header1", "footer:footer1"]
    parts = {item.locator["part_path"] for item in parsed.fragments}
    assert parts == {
        "word/document.xml", "word/footnotes.xml", "word/header1.xml", "word/footer1.xml",
    }
    assert parsed.coverage["complete"] is True


def test_docx_dangling_reference_fails_instead_of_losing_referenced_prose():
    data = docx('<w:p><w:r><w:t>正文</w:t><w:footnoteReference w:id="1"/></w:r></w:p>')
    with pytest.raises(SourceParseError, match="source_docx_invalid"):
        parse_source(filename="dangling.docx", data=data)


def _pdf_bytes(text: str = "Hello PDF") -> bytes:
    """Minimal one-page PDF with a correct xref, so poppler reads real text."""
    stream = f"BT /F1 24 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_pdf_text_layer_is_extracted_with_page_locator_and_real_processor():
    parsed = parse_source(filename="报告.PDF", data=_pdf_bytes("Hello PDF"))
    assert parsed.format == "pdf"
    assert parsed.parser_key == "poppler-pdftotext-v1"
    assert parsed.extraction_schema_version == 2
    fragment = parsed.fragments[0]
    assert "Hello PDF" in fragment.text
    assert fragment.locator_kind == "page_region"
    assert fragment.locator["page_start"] == 0 and fragment.locator["page_end"] == 1
    assert fragment.locator["char_end"] == len(fragment.text)
    processor = parsed.processor_evidence["processors"][0]
    assert processor["ref"] == "pdftotext" and processor["engine"] == "poppler"
    assert processor["version"] not in {"", "unknown"}
    assert parsed.coverage["units_total"] == 1


@pytest.mark.parametrize("data,code", [
    (b"%PDF-1.4 not really a pdf", "source_pdf_invalid"),
])
def test_pdf_failures_are_explicit(data, code):
    with pytest.raises(SourceParseError) as failure:
        parse_source(filename="broken.pdf", data=data)
    assert failure.value.code == code


def _xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "人物"
    sheet["A1"] = "姓名"
    sheet["A2"] = "张某"
    sheet["B2"] = "=LEN(A2)"
    sheet["C3"] = 3.0
    sheet.merge_cells("A4:B4")
    sheet["A4"] = "合并格"
    other = workbook.create_sheet("地点")
    other["A1"] = "古桥"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_xlsx_keeps_sheet_cell_coordinates_and_formula_cache_state():
    parsed = parse_source(filename="资料.xlsx", data=_xlsx_bytes())
    assert parsed.format == "xlsx"
    assert parsed.parser_key == "openpyxl-xlsx-v1"
    texts = [item.text for item in parsed.fragments]
    assert {"姓名", "张某", "古桥", "合并格"} <= set(texts)
    formula = next(item for item in parsed.fragments if item.text == "=LEN(A2)")
    assert formula.locator["sheet"] == "人物"
    assert formula.locator["row_start"] == 1 and formula.locator["column_start"] == 1
    assert formula.evidence_meta["cached_known"] is False
    assert formula.evidence_meta["formula"] == "=LEN(A2)"
    merged = next(item for item in parsed.fragments if item.text == "合并格")
    assert merged.locator["row_start"] == 3
    assert parsed.coverage["merged_ranges"] == 1
    assert parsed.coverage["sheets"] == ["人物", "地点"]
    processor = parsed.processor_evidence["processors"][0]
    assert processor["ref"] == "openpyxl" and processor["engine"] == "openpyxl"


@pytest.mark.parametrize("filename,data", [
    ("a.pdf", b"PK\x03\x04"),
    ("a.docx", b"%PDF-1.4"),
    ("a.xlsx", b"not a zip"),
    ("a.png", b"\xff\xd8\xff\xe0"),
    ("a.webp", b"RIFFxxxxNOPE"),
])
def test_disguised_magic_is_rejected_before_the_wrong_processor(filename, data):
    with pytest.raises(SourceParseError) as failure:
        parse_source(filename=filename, data=data)
    assert failure.value.code == "source_format_mismatch"


def test_capabilities_reflect_actual_components_not_extensions(monkeypatch):
    payload = registry.source_capabilities()
    assert len(str(payload["profile_revision"])) == 64
    formats = {item["format"]: item for item in payload["formats"]}  # type: ignore[index]
    assert set(formats) == {
        "txt", "csv", "tsv", "docx", "pdf", "xlsx", "image", "audio", "video",
    }
    assert all(isinstance(item["available"], bool) for item in formats.values())
    assert payload["auto_analysis"]["enabled"] is False  # type: ignore[index]
    keys = list(registry._components())
    monkeypatch.setattr(registry, "_components", lambda: {key: False for key in keys})
    degraded = {
        item["format"]: item
        for item in registry.source_capabilities()["formats"]  # type: ignore[index]
    }
    assert degraded["image"]["available"] is False
    assert degraded["audio"]["available"] is False
    assert degraded["pdf"]["available"] is False
    assert degraded["txt"]["available"] is True


def test_processor_profile_revision_tracks_contract_limits(monkeypatch):
    first = registry.processor_profile_revision()
    monkeypatch.setattr(contracts, "MAX_SOURCE_BYTES", contracts.MAX_SOURCE_BYTES + 1)
    assert registry.processor_profile_revision() != first


def test_media_requires_a_real_decodable_stream(monkeypatch, tmp_path):
    monkeypatch.setattr(registry.asr, "executable", lambda: "/bin/true")
    monkeypatch.setattr(
        registry.asr, "require_model", lambda: (tmp_path / "model.bin", "0" * 64)
    )
    with pytest.raises(SourceParseError) as failure:
        parse_source(filename="clip.mp3", data=b"not audio")
    assert failure.value.code in {"source_media_invalid", "source_processor_unavailable"}
