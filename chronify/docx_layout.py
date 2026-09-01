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
import shutil
import subprocess
import zipfile
from html import unescape
from pathlib import Path

TWIPS = 1440.0

WT_RE = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)
RUN_RE = re.compile(r"<w:r(?:\s[^>]*)?>.*?</w:r>", re.S)
GRIDCOL_RE = re.compile(r'<w:gridCol w:w="(\d+)"')
SPAN_RE = re.compile(r'<w:gridSpan w:val="(\d+)"')
FILL_RE = re.compile(r'w:fill="([0-9A-Fa-f]{6})"')
HEIGHT_RE = re.compile(r"<w:trHeight\b[^>]*/?>")
MARGIN_RE = re.compile(r"<w:tcMar>.*?</w:tcMar>", re.S)

PANDOC_HINT = (
    "pandoc is needed to read the Word layout. Install it with:\n"
    "    brew install pandoc"
)


def _inches(twips):
    return f"{int(twips) / TWIPS:.3f}in"


def _blocks(xml, tag):
    depth, start, out = 0, None, []
    for m in re.finditer(rf"<w:{tag}[ >]|</w:{tag}>", xml):
        if m.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                out.append(xml[start:m.end()])
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return out


def _without_nested(xml):
    depth, start, spans = 0, None, []
    for m in re.finditer(r"<w:tbl>|</w:tbl>", xml):
        if m.group(0) == "</w:tbl>":
            depth -= 1
            if depth == 1:
                spans.append((start, m.end()))
        else:
            if depth == 1:
                start = m.start()
            depth += 1
    for a, b in reversed(spans):
        xml = xml[:a] + xml[b:]
    return xml


def _marked(run_xml):
    text = unescape("".join(WT_RE.findall(run_xml)))
    if not text.strip():
        return text

    props = re.search(r"<w:rPr>.*?</w:rPr>", run_xml, re.S)
    props = props.group(0) if props else ""
    core = text.strip()
    if re.search(r'<w:u w:val="(?!none)', props):
        core = f"__{core}__"
    if re.search(r'<w:b w:val="(?!0|false)', props) or "<w:b/>" in props:
        core = f"**{core}**"

    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return lead + core + trail


def _lines(cell_xml):
    body = re.sub(r"<w:br\b[^>]*/?>", "</w:p><w:p>", _without_nested(cell_xml))
    out = []
    for chunk in re.split(r"</w:p>", body):
        marked = "".join(_marked(r) for r in RUN_RE.findall(chunk))
        marked = re.sub(r"\*\*(\s*)\*\*", r"\1", marked)
        marked = re.sub(r"\*\*([^*]+)\*\* \*\*([^*]+)\*\*", r"**\1 \2**", marked)
        text = " ".join(marked.split())
        if text:
            out.append(text)
    return out


def _borders(xml):
    block = re.search(r"<w:tblBorders>.*?</w:tblBorders>", xml, re.S)
    if not block:
        return "none declared"

    sides, weight, colour = [], None, None
    for element in re.finditer(r"<w:(\w+)\b([^>]*)/>", block.group(0)):
        side, attrs = element.group(1), element.group(2)
        if re.search(r'w:val="(?:nil|none)"', attrs):
            continue
        sides.append(side)
        size = re.search(r'w:sz="(\d+)"', attrs)
        hue = re.search(r'w:color="(\w+)"', attrs)
        weight = weight or (size.group(1) if size else None)
        colour = colour or (hue.group(1) if hue else None)

    if not sides:
        return "none declared"
    thickness = f"{int(weight) / 8:g}pt" if weight else "?pt"
    return f"{thickness} #{colour or '000000'} on {', '.join(sides)}"


def _padding(xml):
    block = MARGIN_RE.search(xml)
    if not block:
        return None
    values = {}
    for side in ("top", "left", "bottom", "right"):
        found = re.search(rf'<w:{side} w:w="([\d.]+)"', block.group(0))
        if found:
            values[side] = float(found.group(1))
    if not values:
        return None
    unique = set(values.values())
    if len(unique) == 1:
        return f"{unique.pop() / 20:g}pt on all sides"
    return ", ".join(f"{k} {v / 20:g}pt" for k, v in values.items())


def _describe_table(xml, label, out, depth=0):
    pad = "  " * depth
    own = _without_nested(xml)
    grid = GRIDCOL_RE.findall(own)

    used = 0
    for row in _blocks(xml, "tr"):
        width = sum(
            int(SPAN_RE.search(c).group(1)) if SPAN_RE.search(c) else 1
            for c in _blocks(row, "tc")
        )
        used = max(used, width)

    out.append(f"\n{pad}=== TABLE {label} ===")
    if used and used < len(grid):
        out.append(f"{pad}columns {used} (Word declares {len(grid)}, only the "
                   f"first {used} are used): "
                   + ", ".join(_inches(g) for g in grid[:used]))
    else:
        out.append(f"{pad}columns {len(grid)}: "
                   + ", ".join(_inches(g) for g in grid))
    out.append(f"{pad}borders {_borders(own)}")
    padding = _padding(own)
    if padding:
        out.append(f"{pad}cell padding {padding}")

    nested = []
    for number, row in enumerate(_blocks(xml, "tr")):
        height = HEIGHT_RE.search(row)
        note = ""
        if height:
            value = re.search(r'w:val="(\d+)"', height.group(0))
            rule = re.search(r'w:hRule="(\w+)"', height.group(0))
            kind = "exactly" if rule and rule.group(1) == "exact" else "at least"
            if value:
                note = f", height {kind} {_inches(value.group(1))}"

        cells = _blocks(row, "tc")
        out.append(f"\n{pad}  row {number}: {len(cells)} cell(s){note}")

        for position, cell in enumerate(cells):
            span = SPAN_RE.search(cell)
            fill = FILL_RE.search(cell)
            inner = _blocks(cell, "tbl")

            flags = []
            if span:
                flags.append(f"spans {span.group(1)} columns")
            if fill and fill.group(1).lower() != "ffffff":
                flags.append(f"fill #{fill.group(1)}")
            if inner:
                child = f"{label}.{len(nested)}"
                nested.extend((child, t) for t in inner)
                flags.append(f"contains TABLE {child}")

            head = f"{pad}    cell {position}"
            if flags:
                head += f" ({'; '.join(flags)})"
            out.append(head + ":")

            text = _lines(cell)
            if not text and not inner:
                out.append(f"{pad}      (empty)")
            for line in text:
                out.append(f"{pad}      | {line}")

    for child_label, child in nested:
        _describe_table(child, child_label, out, depth + 1)


def measure(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        document = archive.read("word/document.xml").decode("utf-8", "replace")
        try:
            styles = archive.read("word/styles.xml").decode("utf-8", "replace")
        except KeyError:
            styles = ""
        media = [n for n in archive.namelist() if n.startswith("word/media/")]

    out = ["=== PAGE ==="]
    page = re.search(r"<w:pgSz[^>]*/>", document)
    if page:
        width = re.search(r'w:w="(\d+)"', page.group(0))
        height = re.search(r'w:h="(\d+)"', page.group(0))
        if width and height:
            out.append(f"size   {_inches(width.group(1))} x {_inches(height.group(1))}")

    margins = re.search(r"<w:pgMar[^>]*/>", document)
    if margins:
        for side in ("top", "right", "bottom", "left"):
            found = re.search(rf'w:{side}="(-?\d+)"', margins.group(0))
            if found:
                out.append(f"margin {side:<7}{_inches(abs(int(found.group(1))))}")

    defaults = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S)
    if defaults:
        fonts = re.findall(r'w:ascii="([^"]+)"', defaults.group(0))
        sizes = re.findall(r'<w:sz w:val="(\d+)"', defaults.group(0))
        out.append(f"font   {fonts[0] if fonts else '?'} "
                   f"{int(sizes[0]) / 2:g}pt" if sizes else "font   ?")

    out.append(f"images embedded: {len(media)}")

    for index, table in enumerate(_blocks(document, "tbl")):
        _describe_table(table, str(index), out)

    return "\n".join(out)


def skeleton(source: Path, target_dir: Path) -> Path:
    if shutil.which("pandoc") is None:
        raise RuntimeError(PANDOC_HINT)

    target_dir.mkdir(parents=True, exist_ok=True)
    finished = subprocess.run(
        ["pandoc", str(source.resolve()), "--extract-media=.", "-o", "skeleton.typ"],
        cwd=target_dir, capture_output=True, text=True, timeout=60,
    )
    if finished.returncode != 0:
        raise RuntimeError(
            "pandoc could not read that file:\n\n"
            + (finished.stderr or "no output").strip()[:600]
        )
    return target_dir / "skeleton.typ"


def prepare(source: Path, target_dir: Path) -> dict:
    """Everything an AI needs, ready to paste in one go."""
    built = skeleton(source, target_dir)
    layout = measure(source)
    (target_dir / "layout.txt").write_text(layout, encoding="utf-8")

    media = target_dir / "media"
    images = sorted(media.glob("*")) if media.is_dir() else []

    return {
        "skeleton": built,
        "skeleton_text": built.read_text(encoding="utf-8", errors="replace"),
        "layout": layout,
        "images": images,
        "directory": target_dir,
    }
