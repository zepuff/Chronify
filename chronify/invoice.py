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

import calendar
import datetime as dt
import re
import io
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, TypedDict

import jinja2
from docxtpl import DocxTemplate

from chronify import config as config_module
from chronify import db
from chronify.config import MONTH_NAMES

PROJECT_DIR = Path(__file__).parent
STATE_PATH = Path(os.path.expanduser("~/.work_tracker/invoice_reminder_state.txt"))


def _resolve_template(raw: str) -> Path:
    candidate = Path(os.path.expanduser(str(raw)))
    if candidate.is_absolute():
        return candidate
    for base in (config_module.BASE_DIR, config_module.TEMPLATES_DIR):
        path = base / candidate
        if path.exists():
            return path
    return config_module.TEMPLATES_DIR / candidate

COMPUTED_TOKENS = frozenset({
    "INVOICE_NUMBER", "INVOICE_DATE", "PERIOD_START", "PERIOD_END",
    "TOTAL_HOURS", "RATE", "TOTAL_AMOUNT", "MONTH_NAME", "YEAR", "CURRENCY",
    "SUPPLIER_FULL_NAME",
    "ROW_DATES", "ROW_PROJECT", "ROW_HOURS", "ROW_RATE", "ROW_AMOUNT",
})


def last_working_day_of_month(year: int, month: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def month_bounds(year: int, month: int) -> tuple:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def is_today_last_working_day(today: Optional[date] = None) -> bool:
    today = today or date.today()
    return today == last_working_day_of_month(today.year, today.month)


def should_show_reminder_now(morning_start_hour: int = 7) -> bool:
    today = date.today()
    if not is_today_last_working_day(today):
        return False
    if dt.datetime.now().hour < morning_start_hour:
        return False

    last_reminded = ""
    if STATE_PATH.exists():
        last_reminded = STATE_PATH.read_text(encoding="utf-8").strip()

    return last_reminded != f"{today.year}-{today.month:02d}"


def mark_reminder_shown(today: Optional[date] = None) -> None:
    today = today or date.today()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(f"{today.year}-{today.month:02d}", encoding="utf-8")


def compute_suggested_hours(
    year: int,
    month: int,
    config: Optional[dict] = None,
    on_error: Optional[callable] = None,
) -> float:
    if config and (config.get("peopleforce") or {}).get("use_for_invoice_hours"):
        try:
            from chronify import peopleforce
            if peopleforce.is_configured(config):
                return peopleforce.fetch_total_hours_for_month(year, month, config)
        except Exception as e:
            if on_error is not None:
                on_error(e)

    start, end = month_bounds(year, month)
    daily_totals = db.get_daily_totals_for_range(start, min(end, date.today()))
    return round(sum(daily_totals.values()) / 3600, 1)


def _format_number(value: float) -> str:
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        text = str(int(rounded))
    else:
        text = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _format_date(d: date) -> str:
    return f"{d.day}.{d.month:02d}.{d.year}"


def build_project_rows(breakdown: list, config: dict, period_label: str) -> tuple:
    invoice_cfg = config.get("invoice", {}) or {}
    default_rate = invoice_cfg.get("hourly_rate", 0) or 0

    rows, total = [], 0.0
    for item in breakdown:
        hours = round(float(item.get("hours") or 0), 2)
        if hours <= 0:
            continue

        rate = item.get("rate")
        rate = default_rate if rate in (None, "", 0) else float(rate)
        amount = round(hours * rate, 2)
        total += amount

        rows.append({
            "ROW_DATES": item.get("dates") or period_label,
            "ROW_PROJECT": item.get("name", ""),
            "ROW_HOURS": _format_number(hours),
            "ROW_RATE": _format_number(rate),
            "ROW_AMOUNT": _format_number(amount),
        })

    return rows, round(total, 2)


def build_invoice_context(year: int, month: int, hours: float, config: dict) -> dict:
    invoice_cfg = config.get("invoice", {}) or {}
    rate = invoice_cfg.get("hourly_rate", 0) or 0
    client_code = invoice_cfg.get("client_code", "CODE")

    start, _ = month_bounds(year, month)
    today = date.today()

    month_in_progress = (
        year == today.year and month == today.month
        and today < last_working_day_of_month(year, month)
    )
    period_end = today if month_in_progress else last_working_day_of_month(year, month)

    context = {
        "INVOICE_NUMBER": f"{client_code}{month:02d}{year}",
        "INVOICE_DATE": _format_date(period_end),
        "PERIOD_START": _format_date(start),
        "PERIOD_END": _format_date(period_end),
        "TOTAL_HOURS": _format_number(hours),
        "RATE": _format_number(rate),
        "TOTAL_AMOUNT": _format_number(round(hours * rate, 2)),
        "MONTH_NAME": calendar.month_name[month],
        "CURRENCY": invoice_cfg.get("currency", "USD") or "USD",
        "YEAR": str(year),
        "SUPPLIER_FULL_NAME": invoice_cfg.get(
            "supplier_full_name",
            invoice_cfg.get("supplier_name", "Supplier").replace("_", " "),
        ),
    }

    requisites = invoice_cfg.get("requisites", {}) or {}
    for key, raw in requisites.items():
        value = str(raw or "").strip()
        if value:
            context[key.upper()] = value

    return context


def build_invoice_filename(year: int, month: int, config: dict) -> str:
    invoice_cfg = config.get("invoice", {}) or {}
    supplier = invoice_cfg.get("supplier_name", "Supplier")
    client = invoice_cfg.get("client_name", "Client")
    return f"Invoice_{supplier}_{client}_{calendar.month_name[month]}_{year}.docx"


_ROW_TOKEN = "{{ROW_PROJECT}}"


_TOKEN_RE = re.compile(r"\{\{[A-Z_][A-Z0-9_]*\}\}")
_TR_RE = re.compile(r"<w:tr[ >]|</w:tr>")


class TemplateSyntaxError(ValueError):
    pass


def _row_span(xml: str, needle: str):
    stack, spans = [], []
    for match in _TR_RE.finditer(xml):
        if match.group(0).startswith("</"):
            if stack:
                spans.append((stack.pop(), match.end()))
        else:
            stack.append(match.start())

    hits = [(end - start, start, end)
            for start, end in spans if needle in xml[start:end]]
    if not hits:
        return None
    _, start, end = min(hits)
    return start, end


def _rows_to_jinja(xml: str) -> tuple:
    span = _row_span(xml, _ROW_TOKEN)
    if span is None:
        return xml, False

    start, end = span
    row = xml[start:end]
    row = re.sub(r"\{\{(ROW_[A-Z0-9_]*)\}\}", r"{{ _row.\1 }}", row)

    return (
        xml[:start]
        + "{% for _row in _rows %}" + row + "{% endfor %}"
        + xml[end:]
    ), True


class _Template(DocxTemplate):

    def __init__(self, template_path, rows=()):
        super().__init__(str(template_path))
        self._rows = list(rows or [])
        self.tokens = set()
        self.row_token_found = False

    def patch_xml(self, src_xml: str) -> str:
        xml = super().patch_xml(src_xml)
        self.tokens.update(t[2:-2] for t in _TOKEN_RE.findall(xml))
        xml, found = _rows_to_jinja(xml)
        self.row_token_found = self.row_token_found or found
        return xml


def _build_context(tokens, mapping: dict, rows: list) -> tuple:
    context = {"_rows": list(rows or [])}
    missing = []

    for name in sorted(tokens):
        value = mapping.get(name)
        if value is None or not str(value).strip():
            context[name] = "{{" + name + "}}"
            missing.append("{{" + name + "}}")
        else:
            context[name] = str(value)

    return context, missing


def _assert_well_formed(docx_path: Path) -> None:
    with zipfile.ZipFile(docx_path) as zin:
        parts = [n for n in zin.namelist()
                 if n.endswith(".xml") or n.endswith(".rels")]
        for name in parts:
            try:
                ET.fromstring(zin.read(name))
            except ET.ParseError as e:
                raise RuntimeError(
                    f"The finished document came out corrupted ({name}: {e}). "
                    f"It has not been saved. The likeliest cause is a "
                    f"construct in the template the substitution cannot read."
                )


_DOCPR_RE = re.compile(r"<wp:docPr\b[^>]*>", re.S)
_BLIP_RE = re.compile(r'<a:blip[^>]*r:embed="([^"]+)"')
_REL_RE = re.compile(r'<Relationship\b[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"')

_IMAGE_FORMATS = {
    ".png": ("PNG", "RGBA"),
    ".jpg": ("JPEG", "RGB"),
    ".jpeg": ("JPEG", "RGB"),
    ".gif": ("GIF", "P"),
    ".bmp": ("BMP", "RGB"),
    ".tiff": ("TIFF", "RGB"),
}


def _media_files(contents: dict) -> list:
    return sorted(n for n in contents if n.startswith("word/media/"))


def _signature_target(contents: dict, preferred_name: str = "") -> Optional[str]:
    media = _media_files(contents)
    if not media:
        return None

    if preferred_name:
        wanted = f"word/media/{preferred_name}"
        if wanted in contents:
            return wanted
        raise FileNotFoundError(
            f"invoice.signature_image_name points at '{preferred_name}', which "
            f"is not in the template. Images available: "
            f"{', '.join(Path(m).name for m in media)}"
        )

    document_xml = contents.get("word/document.xml", b"").decode("utf-8", "replace")
    rels_xml = contents.get("word/_rels/document.xml.rels", b"").decode("utf-8", "replace")
    rels = dict(_REL_RE.findall(rels_xml))

    for drawing in re.finditer(r"<w:drawing>.*?</w:drawing>", document_xml, re.S):
        block = drawing.group(0)
        descriptor = " ".join(_DOCPR_RE.findall(block)).lower()
        if "sign" not in descriptor and "podpis" not in descriptor:
            continue
        embed = _BLIP_RE.search(block)
        if not embed:
            continue
        target = rels.get(embed.group(1), "")
        candidate = "word/" + target.lstrip("/")
        if candidate in contents:
            return candidate

    if len(media) == 1:
        return media[0]

    raise ValueError(
        f"The template contains {len(media)} images and none of them is marked "
        f"as a signature, so replacing one automatically would be a guess. Set "
        f"invoice.signature_image_name in config.yaml to one of: "
        f"{', '.join(Path(m).name for m in media)} — or name the picture "
        f"'signature' in Word (right-click the image, Edit Alt Text)."
    )


def _apply_signature_image(docx_path: Path, signature_path: Optional[str],
                           preferred_name: str = "") -> None:
    if not signature_path:
        return

    path = Path(os.path.expanduser(signature_path))
    if not path.exists():
        raise FileNotFoundError(
            f"Signature file not found: {path}. "
            f"Check invoice.signature_image_path in config.yaml."
        )

    with zipfile.ZipFile(docx_path, "r") as zin:
        contents = {name: zin.read(name) for name in zin.namelist()}

    target = _signature_target(contents, preferred_name)
    if target is None:
        return

    from PIL import Image

    fmt, mode = _IMAGE_FORMATS.get(Path(target).suffix.lower(), ("PNG", "RGBA"))
    buffer = io.BytesIO()
    Image.open(path).convert(mode).save(buffer, format=fmt)
    contents[target] = buffer.getvalue()

    with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in contents.items():
            zout.writestr(name, data)


_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _renumber_bookmarks(doc) -> None:
    import itertools

    counter = itertools.count(9000)
    seen_names, pending = {}, {}

    for element in doc.docx.element.iter():
        if element.tag == _W_NS + "bookmarkStart":
            old_id = element.get(_W_NS + "id")
            new_id = str(next(counter))
            pending.setdefault(old_id, []).append(new_id)
            element.set(_W_NS + "id", new_id)

            name = element.get(_W_NS + "name")
            if name:
                seen = seen_names.get(name, 0)
                if seen:
                    element.set(_W_NS + "name", f"{name}_{seen}")
                seen_names[name] = seen + 1

        elif element.tag == _W_NS + "bookmarkEnd":
            waiting = pending.get(element.get(_W_NS + "id"))
            if waiting:
                element.set(_W_NS + "id", waiting.pop(0))


def fill_invoice_docx(
    template_path: Path,
    output_path: Path,
    mapping: dict,
    signature_path: Optional[str] = None,
    rows: Optional[list] = None,
    signature_image_name: str = "",
) -> dict:
    doc = _Template(template_path, rows)

    try:
        tokens = doc.get_undeclared_template_variables() | doc.tokens
    except jinja2.TemplateError as e:
        raise TemplateSyntaxError(_syntax_hint(e))

    tokens.discard("_rows")
    context, missing = _build_context(tokens, mapping, rows)

    if doc.row_token_found:
        missing = [name for name in missing if not name.startswith("{{ROW_")]

    try:
        doc.render(context, autoescape=True)
    except jinja2.TemplateError as e:
        raise TemplateSyntaxError(_syntax_hint(e))

    _renumber_bookmarks(doc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))

    _apply_signature_image(output_path, signature_path, signature_image_name)
    _assert_well_formed(output_path)

    return {"missing_tokens": missing, "row_token_found": doc.row_token_found}


def _syntax_hint(error: Exception) -> str:
    return (
        f"The invoice template could not be parsed: {error}. "
        f"This is usually a stray pair of braces in the text: double "
        f"{{{{ }}}} are reserved for the fields Chronify fills in."
    )


def read_template_tokens(template_path: Path) -> list:
    doc = _Template(template_path)
    try:
        declared = doc.get_undeclared_template_variables()
    except jinja2.TemplateError as e:
        raise TemplateSyntaxError(_syntax_hint(e))
    return sorted((declared | doc.tokens) - {"_rows"})


def row_template_state(template_path: Path) -> str:
    doc = _Template(template_path)
    try:
        doc.get_undeclared_template_variables()
    except jinja2.TemplateError as e:
        raise TemplateSyntaxError(_syntax_hint(e))

    if doc.row_token_found:
        return "table"
    if "ROW_PROJECT" in doc.tokens:
        return "flattened"
    return "absent"


def party_tokens(template_path: Path) -> list:
    return [t for t in read_template_tokens(template_path)
            if t not in COMPUTED_TOKENS]


def convert_docx_to_pdf(docx_path: Path) -> Optional[Path]:
    candidates = ["soffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    soffice_bin = next(
        (c for c in candidates if shutil.which(c) or Path(c).exists()), None
    )
    if soffice_bin is None:
        return None

    try:
        subprocess.run(
            [soffice_bin, "--headless", "--convert-to", "pdf",
             "--outdir", str(docx_path.parent), str(docx_path)],
            check=True, capture_output=True, timeout=60,
        )
    except Exception:
        return None

    pdf_path = docx_path.with_suffix(".pdf")
    return pdf_path if pdf_path.exists() else None


def get_invoice_docx_path(year: int, month: int, config: dict) -> Path:
    invoice_cfg = config.get("invoice", {}) or {}
    output_dir = Path(os.path.expanduser(invoice_cfg.get("output_dir", "~/Documents/Invoices")))
    return output_dir / build_invoice_filename(year, month, config)


class InvoiceResult(TypedDict):
    docx: Optional[Path]
    pdf: Optional[Path]
    missing_tokens: list
    row_token_found: bool


def _build_mapping_and_rows(year, month, hours, config, breakdown):
    mapping = build_invoice_context(year, month, hours, config)
    rows, rows_total = [], 0.0

    if breakdown:
        rows, rows_total = build_project_rows(
            breakdown, config, mapping["PERIOD_START"] + " — " + mapping["PERIOD_END"]
        )
        if rows:
            mapping["TOTAL_AMOUNT"] = _format_number(rows_total)
            mapping["TOTAL_HOURS"] = _format_number(
                sum(float(i.get("hours") or 0) for i in breakdown)
            )

    return mapping, rows


def get_invoice_pdf_path(year: int, month: int, config: dict) -> Path:
    return get_invoice_docx_path(year, month, config).with_suffix(".pdf")


def create_invoice(
    year: int,
    month: int,
    hours: float,
    config: dict,
    breakdown: Optional[list] = None,
) -> InvoiceResult:
    invoice_cfg = config.get("invoice", {}) or {}

    template_path = _resolve_template(
        invoice_cfg.get("template_path", "Invoice_Template_TOKENS.docx")
    )
    if not template_path.exists():
        raise FileNotFoundError(
            f"Invoice template not found: {template_path}. "
            f"Check invoice.template_path in config.yaml."
        )

    docx_path = get_invoice_docx_path(year, month, config)
    mapping, rows = _build_mapping_and_rows(year, month, hours, config, breakdown)

    report = fill_invoice_docx(
        template_path, docx_path, mapping,
        invoice_cfg.get("signature_image_path", ""), rows,
        invoice_cfg.get("signature_image_name", ""),
    )

    return {
        "docx": docx_path,
        "pdf": convert_docx_to_pdf(docx_path),
        "missing_tokens": report["missing_tokens"],
        "row_token_found": report["row_token_found"],
    }