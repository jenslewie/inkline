from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

from inkline.epub.table.model import TableRow, TableView


def resolve_table_view(block: dict[str, Any]) -> TableView | None:
    attrs = block.get("attrs") or {}
    html = attrs.get("html", "")
    html_fragment: str | None = None
    rows: list[TableRow] = []

    if html and isinstance(html, str) and html.strip():
        html_fragment = _sanitize_html_fragment(html)

    if html_fragment is None:
        rows = _table_rows_from_text(block.get("text", ""))

    if html_fragment is None and not rows:
        return None

    table_notes = attrs.get("table_notes") or attrs.get("footnotes") or []
    notes = [str(n) for n in table_notes if n and not _is_continuation_marker_text(str(n))]
    return TableView(
        html_fragment=html_fragment,
        rows=rows,
        cell_alignments=attrs.get("cell_alignments"),
        notes=notes,
    )


def _table_rows_from_text(text: str) -> list[TableRow]:
    if not text.strip():
        return []
    rows: list[TableRow] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or set(line) <= {"|", "-", ":", " "}:
            continue
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c]
        if cells:
            rows.append(TableRow(cells=cells))
    return rows


def _is_continuation_marker_text(text: str) -> bool:
    """Check whether a note string is a table continuation marker.

    Handles parenthesized/bracketed forms like "(接上页)", "（续表）", "【接下页】"
    by stripping surrounding delimiters before matching the core keyword.
    """
    t = text.strip()
    t = t.strip("()（）[]【】")
    return t in {"接上页", "接下页", "续表", "续上表"}


_XML_ENTITIES = {"amp", "lt", "gt", "apos", "quot"}


_HTML_NAMED_ENTITIES: dict[str, str] = {
    "nbsp": " ",
    "copy": "©",
    "reg": "®",
    "trade": "™",
    "mdash": "—",
    "ndash": "–",
    "lsquo": "‘",
    "rsquo": "’",
    "ldquo": "“",
    "rdquo": "”",
    "bull": "•",
    "hellip": "…",
    "laquo": "«",
    "raquo": "»",
    "middot": "·",
    "times": "×",
    "divide": "÷",
    "deg": "°",
    "plusmn": "±",
    "para": "¶",
    "sect": "§",
    "euro": "€",
    "pound": "£",
    "yen": "¥",
    "cent": "¢",
    "rarr": "→",
    "larr": "←",
    "uarr": "↑",
    "darr": "↓",
    "infin": "∞",
    "ne": "≠",
    "le": "≤",
    "ge": "≥",
    "micro": "µ",
}


def _sanitize_html_fragment(html: str) -> str | None:
    try:
        ET.fromstring(html)
        return html
    except ET.ParseError:
        pass
    fixed = re.sub(
        r"&([a-zA-Z][a-zA-Z0-9]*);",
        lambda m: (
            f"&{m.group(1)};"
            if m.group(1) in _XML_ENTITIES
            else _escape_html_named_entity(m.group(1))
        ),
        html,
    )
    fixed = re.sub(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#x[0-9a-fA-F]+);)", "&amp;", fixed)
    fixed = re.sub(
        r"<(br|hr|img|input|meta|link)(\s[^>]*)?>",
        lambda m: f"<{m.group(1)}{m.group(2) or ''}/>",
        fixed,
    )
    try:
        ET.fromstring(fixed)
        return fixed
    except ET.ParseError:
        return None


def _escape_html_named_entity(name: str) -> str:
    from html import escape

    return escape(_HTML_NAMED_ENTITIES.get(name, f"&{name};"))
