#!/usr/bin/env python3
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

import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from chronify import config as config_module
from chronify import invoice


SAMPLE_BREAKDOWN = [
    {"name": "Sample project A", "hours": 10, "rate": 30, "dates": "1.09 — 15.09"},
    {"name": "Sample project B", "hours": 5, "rate": 40, "dates": "16.09 — 30.09"},
]


def resolve(argument):
    if argument:
        return Path(argument).expanduser()

    config = config_module.load_config()
    configured = (config.get("invoice") or {}).get("template_path", "")
    if configured:
        return invoice._resolve_template(configured)
    return invoice._resolve_template("Invoice_Template_TOKENS.docx")


def report_parts(path):
    with zipfile.ZipFile(path) as archive:
        broken = []
        for name in archive.namelist():
            if not (name.endswith(".xml") or name.endswith(".rels")):
                continue
            try:
                ET.fromstring(archive.read(name))
            except ET.ParseError as error:
                broken.append(f"{name}: {error}")
    return broken


def describe_tables(path):
    import re

    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")

    stack, spans = [], []
    for match in re.finditer(r"<w:tbl>|</w:tbl>", xml):
        if match.group(0) == "<w:tbl>":
            stack.append(match.start())
        elif stack:
            spans.append((stack.pop(), match.end()))
    spans.sort()

    print(f"  tables: {len(spans)}")
    for start, end in spans:
        body = xml[start:end]
        nested = any(a < start and b > end for a, b in spans)
        rows = len(re.findall(r"<w:tr[ >]", body))
        cells = len(re.findall(r"<w:tc[ >]", body))
        kind = "nested" if nested else "top level"
        borders = "borders" if "<w:tblBorders>" in body else "no borders"
        print(f"    {kind}: {rows} rows, {cells} cells, {borders}")

    row_span = invoice._row_span(xml, invoice._ROW_TOKEN)
    if row_span is None:
        if invoice._ROW_TOKEN in xml:
            print("    {{ROW_PROJECT}} is present but NOT inside a table row")
        else:
            print("    {{ROW_PROJECT}} is missing entirely")
    else:
        row = xml[row_span[0]:row_span[1]]
        print(f"    row template: {len(re.findall(r'<w:tc[ >]', row))} cells")


def main():
    template = resolve(sys.argv[1] if len(sys.argv) > 1 else "")
    print(f"Template: {template}")

    if not template.exists():
        print("  the file does not exist")
        return 1

    print(f"  parts with broken XML: {report_parts(template) or 'none'}")
    describe_tables(template)

    try:
        tokens = invoice.read_template_tokens(template)
    except invoice.TemplateSyntaxError as error:
        print(f"\nThe template cannot be read:\n  {error}")
        return 1

    print(f"  tokens found ({len(tokens)}): {', '.join(tokens) or 'none'}")
    print(f"  fields for Payment details: {', '.join(invoice.party_tokens(template)) or 'none'}")

    config = config_module.load_config()
    mapping, rows = invoice._build_mapping_and_rows(
        2026, 9, 15, config, SAMPLE_BREAKDOWN
    )

    output = Path(tempfile.mkdtemp()) / "check_invoice.docx"
    try:
        result = invoice.fill_invoice_docx(
            template, output, mapping,
            (config.get("invoice") or {}).get("signature_image_path", ""),
            rows,
            (config.get("invoice") or {}).get("signature_image_name", ""),
        )
    except Exception as error:
        print(f"\nFilling failed: {type(error).__name__}: {error}")
        return 1

    print("\nFilled a sample invoice with two projects.")
    print(f"  row template found: {result['row_token_found']}")
    print(f"  still empty ({len(result['missing_tokens'])}): "
          f"{', '.join(result['missing_tokens']) or 'nothing'}")

    text = zipfile.ZipFile(output).read("word/document.xml").decode("utf-8", "replace")
    for expected in ("Sample project A", "Sample project B"):
        print(f"  {expected} in the document: {expected in text}")

    pdf = invoice.convert_docx_to_pdf(output)
    print(f"  PDF: {pdf or 'not created (LibreOffice missing)'}")

    print(f"\nOpen it and compare with your own invoice:\n  open {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())