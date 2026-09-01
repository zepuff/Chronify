# Chronify — a macOS menu bar work tracker.
# Copyright (C) 2026 Zepuff
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import re
import tempfile
import xml.dom.minidom
import zipfile
from html import unescape
from pathlib import Path

from chronify import invoice

BUNDLED = Path(__file__).resolve().parent.parent / "chronify" / "templates" / "Invoice_Template_TOKENS.docx"


def _fill(config, breakdown):
    mapping = invoice.build_invoice_context(2026, 9, 10, config)
    rows, total = invoice.build_project_rows(breakdown, config, "period")
    if rows:
        mapping["TOTAL_AMOUNT"] = invoice._format_number(total)

    out = Path(tempfile.mkdtemp()) / "invoice.docx"
    report = invoice.fill_invoice_docx(BUNDLED, out, mapping, None, rows)
    raw = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    return report, raw, re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", raw)))


def test_ampersands_and_angle_brackets_do_not_break_the_document():
    config = {"invoice": {
        "hourly_rate": 30,
        "supplier_full_name": "PE Test & Co <Ltd>",
        "requisites": {"acquirer_name": 'Client "A" & Co'},
    }}
    _report, raw, text = _fill(
        config, [{"name": "R&D <core>", "hours": 10, "rate": 30}]
    )

    xml.dom.minidom.parseString(raw)
    assert "PE Test & Co <Ltd>" in text
    assert "R&D <core>" in text
    assert 'Client "A" & Co' in text


def test_one_row_is_written_per_project():
    config = {"invoice": {"hourly_rate": 30, "client_code": "XY"}}
    report, _raw, text = _fill(config, [
        {"name": "Alpha", "hours": 10, "rate": 30, "dates": "1.09 — 15.09"},
        {"name": "Beta", "hours": 5, "rate": 40, "dates": "16.09 — 30.09"},
    ])

    assert report["row_token_found"]
    assert "Alpha" in text and "Beta" in text
    assert "1.09 — 15.09" in text and "16.09 — 30.09" in text


def test_the_invoice_number_follows_the_client_code_and_month():
    config = {"invoice": {"hourly_rate": 1, "client_code": "XY"}}
    _report, _raw, text = _fill(config, [])

    assert "XY092026" in text


def test_empty_requisites_stay_as_visible_tokens():
    config = {"invoice": {"hourly_rate": 1, "requisites": {"iban": "UA12"}}}
    report, _raw, _text = _fill(config, [])

    assert "{{IBAN}}" not in report["missing_tokens"]
    assert "{{NIP}}" in report["missing_tokens"]


def test_totals_come_from_the_project_rows():
    config = {"invoice": {"hourly_rate": 30}}
    _report, _raw, text = _fill(config, [
        {"name": "Alpha", "hours": 10, "rate": 30},
        {"name": "Beta", "hours": 5, "rate": 40},
    ])

    assert "500" in text


def test_a_field_added_by_hand_in_word_becomes_a_real_field():
    party = invoice.party_tokens(BUNDLED)

    assert "IBAN" in party
    assert "NIP" in party
    assert not set(party) & invoice.COMPUTED_TOKENS


def test_any_requisite_key_reaches_the_document():
    config = {"invoice": {"hourly_rate": 1, "requisites": {
        "iban": "UA12", "regon": "123456789",
    }}}
    context = invoice.build_invoice_context(2026, 9, 1, config)

    assert context["IBAN"] == "UA12"
    assert context["REGON"] == "123456789"


_GRID = ('<w:tblPr/><w:tblGrid><w:gridCol w:w="4000"/>'
         '<w:gridCol w:w="4000"/></w:tblGrid>')


def _run(text=None, raw=""):
    inner = f'<w:t xml:space="preserve">{text}</w:t>' if text is not None else raw
    return f"<w:r><w:rPr/>{inner}</w:r>"


def _template(tmp_path, body_xml):
    contents = {n: zipfile.ZipFile(BUNDLED).read(n)
                for n in zipfile.ZipFile(BUNDLED).namelist()}
    document = contents["word/document.xml"].decode()
    head = document[:document.index("<w:body>") + len("<w:body>")]

    path = tmp_path / "template.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in contents.items():
            if name == "word/document.xml":
                data = (head + body_xml + "</w:body></w:document>").encode()
            out.writestr(name, data)
    return path


def _render(tmp_path, body_xml, mapping=None, rows=None):
    template = _template(tmp_path, body_xml)
    output = tmp_path / "invoice.docx"
    report = invoice.fill_invoice_docx(
        template, output, mapping or {"IBAN": "UA12"}, None, rows or []
    )
    raw = zipfile.ZipFile(output).read("word/document.xml").decode()
    xml.dom.minidom.parseString(raw)
    return report, raw


def test_a_token_split_by_word_is_still_filled(tmp_path):
    _report, raw = _render(
        tmp_path, "<w:p>" + _run("{{IB") + _run("AN}}") + "</w:p>"
    )

    assert "UA12" in raw


def test_tracked_changes_do_not_corrupt_the_document(tmp_path):
    _report, raw = _render(tmp_path, (
        "<w:p>" + _run("{{IB")
        + '<w:ins w:id="5" w:author="a" w:date="2026-01-01T00:00:00Z">'
        + _run("AN}}") + "</w:ins></w:p>"
    ))

    assert raw.count("<w:ins ") == raw.count("</w:ins>")
    assert "UA12" in raw


def test_a_hyperlink_around_a_token_does_not_corrupt_the_document(tmp_path):
    _report, raw = _render(tmp_path, (
        "<w:p>" + _run("{{IB") + '<w:hyperlink r:id="rId1">'
        + _run("AN}}") + "</w:hyperlink></w:p>"
    ))

    assert raw.count("<w:hyperlink") == raw.count("</w:hyperlink>")


def test_a_nested_table_inside_the_row_template_survives(tmp_path):
    body = (
        "<w:tbl>" + _GRID + "<w:tr>"
        "<w:tc><w:p>" + _run("{{ROW_PROJECT}}") + "</w:p>"
        "<w:tbl>" + _GRID + "<w:tr><w:tc><w:p>" + _run("inner")
        + "</w:p></w:tc></w:tr></w:tbl></w:tc>"
        "<w:tc><w:p>" + _run("{{ROW_HOURS}}") + "</w:p></w:tc>"
        "</w:tr></w:tbl>"
    )
    report, raw = _render(tmp_path, body, rows=[
        {"ROW_PROJECT": "Alpha", "ROW_HOURS": "10"},
        {"ROW_PROJECT": "Beta", "ROW_HOURS": "5"},
    ])

    assert report["row_token_found"]
    assert "Alpha" in raw and "Beta" in raw
    assert raw.count("inner") == 2


def test_cloned_rows_get_unique_bookmark_ids(tmp_path):
    body = (
        "<w:tbl>" + _GRID + '<w:tr><w:bookmarkStart w:id="7" w:name="row"/>'
        "<w:tc><w:p>" + _run("{{ROW_PROJECT}}") + "</w:p></w:tc>"
        '<w:bookmarkEnd w:id="7"/></w:tr></w:tbl>'
    )
    _report, raw = _render(tmp_path, body, rows=[
        {"ROW_PROJECT": "Alpha"}, {"ROW_PROJECT": "Beta"},
    ])

    ids = re.findall(r'bookmarkStart w:id="(\d+)"', raw)
    assert len(ids) == len(set(ids)) == 2


def test_an_empty_paragraph_in_a_cell_keeps_the_cells_apart(tmp_path):
    body = (
        "<w:tbl>" + _GRID + '<w:tr><w:tc><w:p w14:paraId="9" w:rsidR="00"/></w:tc>'
        "<w:tc><w:p>" + _run("{{IB") + _run("AN}}") + "</w:p></w:tc></w:tr></w:tbl>"
    )
    _report, raw = _render(tmp_path, body)

    assert raw.count("<w:tc>") == 2


def test_a_token_with_a_digit_is_a_real_field(tmp_path):
    _report, raw = _render(
        tmp_path, "<w:p>" + _run("{{ADDRESS2}}") + "</w:p>",
        mapping={"ADDRESS2": "Sobornaya 5"},
    )

    assert "Sobornaya 5" in raw


def test_stray_braces_raise_instead_of_writing_a_broken_file(tmp_path):
    import pytest

    with pytest.raises(invoice.TemplateSyntaxError):
        _render(tmp_path, "<w:p>" + _run("price {{ 2 + }} eur") + "</w:p>")


def test_a_template_still_holding_its_table_is_reported_as_such(tmp_path):
    body = (
        "<w:tbl>" + _GRID + "<w:tr>"
        "<w:tc><w:p>" + _run("{{ROW_PROJECT}}") + "</w:p></w:tc>"
        "<w:tc><w:p>" + _run("{{ROW_HOURS}}") + "</w:p></w:tc>"
        "</w:tr></w:tbl>"
    )

    assert invoice.row_template_state(_template(tmp_path, body)) == "table"


def test_a_table_flattened_into_paragraphs_is_detected(tmp_path):
    body = (
        "<w:p>" + _run("{{ROW_PROJECT}}") + _run("\t") + _run("{{ROW_HOURS}}")
        + "</w:p>"
    )

    assert invoice.row_template_state(_template(tmp_path, body)) == "flattened"


def test_a_template_without_project_rows_is_neither(tmp_path):
    body = "<w:p>" + _run("{{IBAN}}") + "</w:p>"

    assert invoice.row_template_state(_template(tmp_path, body)) == "absent"


def test_the_bundled_template_keeps_its_table():
    assert invoice.row_template_state(BUNDLED) == "table"