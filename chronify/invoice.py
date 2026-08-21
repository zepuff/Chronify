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
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, TypedDict

from chronify import config as config_module
from chronify import db
from chronify.config import MONTH_NAMES

PROJECT_DIR = Path(__file__).parent
STATE_PATH = Path(os.path.expanduser("~/.work_tracker/invoice_reminder_state.txt"))


def _resolve_template(raw: str) -> Path:
    """Own template first, bundled one as the fallback.

    A relative path is looked up in ~/.work_tracker/ first, so a user template
    survives upgrades; the shipped one is used when nothing else matches.
    """
    candidate = Path(os.path.expanduser(str(raw)))
    if candidate.is_absolute():
        return candidate
    for base in (config_module.BASE_DIR, config_module.TEMPLATES_DIR):
        path = base / candidate
        if path.exists():
            return path
    return config_module.TEMPLATES_DIR / candidate

_REQUISITE_TOKENS = {
    "tax_number": "TAX_NUMBER",
    "iban": "IBAN",
    "address": "ADDRESS",
    "swift_code": "SWIFT_CODE",
    "acquirer_name": "ACQUIRER_NAME",
    "acquirer_address": "ACQUIRER_ADDRESS",
    "vat_number": "VAT_NUMBER",
    "nip": "NIP",
    "krs": "KRS",
}


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
        "YEAR": str(year),
        "SUPPLIER_FULL_NAME": invoice_cfg.get(
            "supplier_full_name",
            invoice_cfg.get("supplier_name", "Supplier").replace("_", " "),
        ),
    }

    requisites = invoice_cfg.get("requisites", {}) or {}
    for key, token in _REQUISITE_TOKENS.items():
        value = (requisites.get(key) or "").strip()
        if value:
            context[token] = value

    return context


def build_invoice_filename(year: int, month: int, config: dict) -> str:
    invoice_cfg = config.get("invoice", {}) or {}
    supplier = invoice_cfg.get("supplier_name", "Supplier")
    client = invoice_cfg.get("client_name", "Client")
    return f"Invoice_{supplier}_{client}_{calendar.month_name[month]}_{year}.docx"


_ROW_TOKEN = "{{ROW_PROJECT}}"

_TOKEN_RE = re.compile(r"\{\{[A-Z_]+\}\}")
_PARAGRAPH_RE = re.compile(r"<w:p[ >].*?</w:p>", re.S)
_RUN_RE = re.compile(r"<w:r(?:\s[^>]*)?>.*?</w:r>", re.S)
_WT_RE = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)


def _run_text(run_xml: str) -> str:
    return "".join(_WT_RE.findall(run_xml))


def _merge_runs_in_paragraph(paragraph_xml: str) -> str:
    runs = list(_RUN_RE.finditer(paragraph_xml))
    if len(runs) < 2:
        return paragraph_xml

    texts = [_run_text(run.group(0)) for run in runs]
    combined = "".join(texts)
    if "{{" not in combined:
        return paragraph_xml

    owner = []
    for index, text in enumerate(texts):
        owner.extend([index] * len(text))

    merges = []
    for match in _TOKEN_RE.finditer(combined):
        first = owner[match.start()]
        last = owner[match.end() - 1]
        if last > first:
            merges.append((first, last))

    if not merges:
        return paragraph_xml

    spans = []
    for first, last in sorted(merges):
        if spans and first <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], last))
        else:
            spans.append((first, last))

    result = paragraph_xml
    for first, last in reversed(spans):
        head = runs[first].group(0)
        if not _WT_RE.search(head):
            continue

        merged_text = "".join(texts[first:last + 1])

        state = {"used": False}

        def _rewrite(_match, _text=merged_text, _state=state):
            if _state["used"]:
                return ""
            _state["used"] = True
            return f'<w:t xml:space="preserve">{_text}</w:t>'

        new_head = _WT_RE.sub(_rewrite, head)

        start = runs[first].start()
        end = runs[last].end()
        result = result[:start] + new_head + result[end:]

    return result


def normalise_tokens(document_xml: str) -> str:
    return _PARAGRAPH_RE.sub(
        lambda m: _merge_runs_in_paragraph(m.group(0)), document_xml
    )


def _expand_project_rows(document_xml: str, rows: list) -> tuple:
    template_row = None
    for candidate in re.finditer(r"<w:tr[ >](?:(?!</w:tr>).)*?</w:tr>", document_xml, re.S):
        if _ROW_TOKEN in candidate.group(0):
            template_row = candidate
            break

    if template_row is None:
        return document_xml, False

    original = template_row.group(0)
    if not rows:
        return document_xml.replace(original, "", 1), True

    built = []
    for row in rows:
        chunk = original
        for token, value in row.items():
            chunk = chunk.replace("{{" + token + "}}", str(value))
        built.append(chunk)

    return document_xml.replace(original, "".join(built), 1), True


_DOCPR_RE = re.compile(r"<wp:docPr\b[^>]*>", re.S)
_BLIP_RE = re.compile(r'<a:blip[^>]*r:embed="([^"]+)"')
_REL_RE = re.compile(r'<Relationship\b[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"')


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


def _apply_signature_image(contents: dict, signature_path: str,
                           preferred_name: str = "") -> None:
    if not signature_path:
        return

    path = Path(os.path.expanduser(signature_path))
    if not path.exists():
        raise FileNotFoundError(
            f"Signature file not found: {path}. "
            f"Check invoice.signature_image_path in config.yaml."
        )

    target = _signature_target(contents, preferred_name)
    if target is None:
        return

    from PIL import Image

    buffer = io.BytesIO()
    Image.open(path).convert("RGBA").save(buffer, format="PNG")
    contents[target] = buffer.getvalue()


def fill_invoice_docx(
    template_path: Path,
    output_path: Path,
    mapping: dict,
    signature_path: Optional[str] = None,
    rows: Optional[list] = None,
    signature_image_name: str = "",
) -> dict:
    with zipfile.ZipFile(template_path, "r") as zin:
        contents = {name: zin.read(name) for name in zin.namelist()}

    document_xml = contents["word/document.xml"].decode("utf-8")
    document_xml = normalise_tokens(document_xml)
    document_xml, row_token_found = _expand_project_rows(document_xml, rows or [])

    for token, value in mapping.items():
        document_xml = document_xml.replace("{{" + token + "}}", str(value))

    leftover = sorted(set(_TOKEN_RE.findall(document_xml)))
    contents["word/document.xml"] = document_xml.encode("utf-8")

    _apply_signature_image(contents, signature_path, signature_image_name)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in contents.items():
            zout.writestr(name, data)

    return {"missing_tokens": leftover, "row_token_found": row_token_found}


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
    docx: Path
    pdf: Optional[Path]
    missing_tokens: list
    row_token_found: bool


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