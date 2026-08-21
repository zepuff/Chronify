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
import zipfile
from html import unescape
from pathlib import Path

_TEXT_RUN_RE = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_TOKEN_RE = re.compile(r"\{\{[A-Z_]+\}\}")

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){10,32}")
_SWIFT_RE = re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
_LONG_DIGITS_RE = re.compile(r"\b\d{8,12}\b")
_VAT_RE = re.compile(r"\b[A-Z]{0,2}\d{8,13}\b")
_MONEY_RE = re.compile(r"\d+(?:[.,]\d{1,2})?")

FIELDS = [
    (["invoice", "supplier_full_name"], "Your full name",
     ["supplier", "beneficiary", "seller", "from"], None),
    (["invoice", "requisites", "tax_number"], "Tax number",
     ["tax number", "tax id", "taxpayer", "tin"], _LONG_DIGITS_RE),
    (["invoice", "requisites", "iban"], "IBAN",
     ["iban", "account number", "account no"], _IBAN_RE),
    (["invoice", "requisites", "swift_code"], "SWIFT / BIC",
     ["swift", "bic"], _SWIFT_RE),
    (["invoice", "requisites", "address"], "Your address",
     ["address", "registered office"], None),
    (["invoice", "requisites", "acquirer_name"], "Client legal name",
     ["acquirer", "buyer", "bill to", "customer", "client"], None),
    (["invoice", "requisites", "acquirer_address"], "Client address",
     ["acquirer address", "buyer address", "client address"], None),
    (["invoice", "requisites", "vat_number"], "Client VAT number",
     ["vat number", "vat id", "vat"], _VAT_RE),
    (["invoice", "requisites", "nip"], "Client NIP",
     ["nip"], _LONG_DIGITS_RE),
    (["invoice", "requisites", "krs"], "Client KRS",
     ["krs"], _LONG_DIGITS_RE),
    (["invoice", "hourly_rate"], "Hourly rate",
     ["rate", "hourly rate", "price per hour"], _MONEY_RE),
]

_STOP_WORDS = sorted(
    {alias for _p, _l, aliases, _r in FIELDS for alias in aliases}
    | {"nip", "krs", "vat", "swift", "bic", "iban", "regon", "total",
       "invoice", "rate", "hours", "amount", "date", "phone", "email"},
    key=len, reverse=True,
)


def _truncate_at_next_label(value: str, used_alias: str) -> str:
    lowered = value.lower()
    cut = len(value)
    for word in _STOP_WORDS:
        if word == used_alias:
            continue
        position = lowered.find(word)
        if 0 < position < cut:
            cut = position
    return value[:cut].strip(" ,;:-–—")


def read_lines(path) -> list:
    with zipfile.ZipFile(Path(path), "r") as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")

    lines = []
    for chunk in re.split(r"</w:p>", xml):
        text = "".join(_TEXT_RUN_RE.findall(chunk))
        text = unescape(_TAG_RE.sub("", text)).strip()
        text = " ".join(text.split())
        if text:
            lines.append(text)
    return lines


BLANK_TEMPLATE_MIN_TOKENS = 5


def count_tokens(lines: list) -> int:
    return sum(len(_TOKEN_RE.findall(line)) for line in lines)


def is_blank_template(lines: list) -> bool:
    return count_tokens(lines) >= BLANK_TEMPLATE_MIN_TOKENS


def _value_after_label(line: str, alias: str):
    lowered = line.lower()
    position = lowered.find(alias)
    if position < 0:
        return None

    tail = line[position + len(alias):].lstrip()
    tail = re.sub(r"^(?:number|no|id|code)\b", "", tail, flags=re.IGNORECASE)
    tail = tail.lstrip(":;-–—").strip()
    return tail or None


def _match_field(lines: list, aliases: list, pattern):
    ordered = sorted(aliases, key=len, reverse=True)

    for index, line in enumerate(lines):
        for alias in ordered:
            if alias not in line.lower():
                continue

            candidates = []
            tail = _value_after_label(line, alias)
            if tail:
                candidates.append(tail)
            if index + 1 < len(lines):
                candidates.append(lines[index + 1])

            for candidate in candidates:
                if _TOKEN_RE.search(candidate):
                    continue
                if pattern is None:
                    trimmed = _truncate_at_next_label(candidate, alias)
                    if trimmed:
                        return trimmed
                else:
                    found = pattern.search(candidate.upper() if pattern is not _MONEY_RE
                                           else candidate)
                    if found:
                        return " ".join(found.group(0).split())
    return None


_ADDRESS_HINT_RE = re.compile(
    r"\b(?:st|str|street|ul|ave|avenue|road|rd|blvd|apt|suite|"
    r"\d{2}-\d{3}|\d{5})\b|\d+[a-zA-Z]?\s*,",
    re.IGNORECASE,
)


def _looks_like_label(line: str) -> bool:
    lowered = line.lower()
    return any(lowered.startswith(word) for word in _STOP_WORDS)


def _collect_address(lines: list, aliases: list, exclude: list) -> str:
    ordered = sorted(aliases, key=len, reverse=True)

    for index, line in enumerate(lines):
        lowered = line.lower()
        if any(word in lowered for word in exclude):
            continue

        for alias in ordered:
            if alias not in lowered:
                continue

            parts = []
            tail = _value_after_label(line, alias)
            if tail and not _TOKEN_RE.search(tail):
                parts.append(_truncate_at_next_label(tail, alias))

            cursor = index + 1
            while cursor < len(lines) and len(parts) < 4:
                nxt = lines[cursor]
                if _TOKEN_RE.search(nxt) or _looks_like_label(nxt):
                    break
                parts.append(nxt)
                cursor += 1
                if not _ADDRESS_HINT_RE.search(nxt):
                    break

            joined = ", ".join(p for p in parts if p).strip(" ,;")
            if joined:
                return joined
    return ""


def extract_fields(lines: list) -> dict:
    found = {}
    for path, _label, aliases, pattern in FIELDS:
        key = tuple(path)

        if key == ("invoice", "requisites", "address"):
            value = _collect_address(
                lines, aliases, ["acquirer", "buyer", "client", "customer", "bill to"]
            )
        elif key == ("invoice", "requisites", "acquirer_address"):
            value = _collect_address(lines, aliases, [])
        else:
            value = _match_field(lines, aliases, pattern)

        if value:
            found[key] = value
    return found


def merge_with_config(found: dict, config: dict) -> list:
    rows = []
    for path, label, _aliases, _pattern in FIELDS:
        key = tuple(path)

        node = config
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        current = "" if node is None else str(node)

        imported = found.get(key, "")
        rows.append({
            "path": list(path),
            "label": label,
            "value": imported or current,
            "source": "invoice" if imported else ("config" if current else "empty"),
        })
    return rows


def rows_to_text(rows: list) -> str:
    return "\n".join(f"{row['label']}: {row['value']}" for row in rows)


def text_to_values(text: str, rows: list) -> dict:
    by_label = {row["label"].lower(): tuple(row["path"]) for row in rows}
    values = {}

    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        path = by_label.get(label.strip().lower())
        if path is not None:
            values[path] = value.strip()

    return values


def coerce(path, value):
    if tuple(path) == ("invoice", "hourly_rate"):
        try:
            return float(str(value).replace(",", "."))
        except ValueError:
            return None
    return value