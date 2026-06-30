from __future__ import annotations

import re
from html import escape
from typing import Any

from inkline.epub.markup import indent_lines
from inkline.epub.table.model import TableView

VALID_ALIGNMENTS = {"left", "center", "right"}


def render_table_html(table: TableView) -> str:
    table_part = table.html_fragment
    if table_part is None:
        rows = [
            "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row.cells) + "</tr>"
            for row in table.rows
        ]
        table_part = "\n".join(["<table>", *indent_lines(rows, "  "), "</table>"])

    table_part = apply_cell_alignments(table_part, table.cell_alignments)
    if table.notes:
        notes_html = [f'<p class="table-note">{escape(note)}</p>' for note in table.notes]
        table_notes_html = "\n".join(
            ['<div class="table-notes">', *indent_lines(notes_html, "  "), "</div>"]
        )
        return f"{table_part}\n{table_notes_html}"
    return table_part


def apply_cell_alignments(html: str, cell_alignments: Any) -> str:
    """Apply cell alignment classes to <td>/<th> elements.

    cell_alignments dict keys (all optional):
      "default": str — fallback alignment for all cells
      "rows": [[row_index, alignment], ...] — alignment for entire rows
      "cells": [[row, col, alignment], ...] — alignment for specific cells

    Returns the HTML unchanged when cell_alignments is None/empty.
    Alignment values: "center", "right", "left".
    """
    if not cell_alignments:
        return html

    default, rows_map, cells_map = _alignment_maps(cell_alignments)
    row = 0
    col = 0
    result: list[str] = []
    tag_pattern = re.compile(r"(<tr[^>]*>)|(<(t[dh])((?:\s[^>]*?)?)>)", re.I)
    pos = 0
    for m in tag_pattern.finditer(html):
        result.append(html[pos : m.start()])
        if m.group(1):
            # <tr> tag: advance row, reset column
            if row > 0 or col > 0:
                row += 1
                col = 0
            # First row starts at row 0 — only advance after processing row cells.
            # row is already 0 at the start, so the first <tr> leaves it at 0.
            result.append(m.group(1))
        elif m.group(2):
            # <td> or <th> tag: determine alignment
            tag = m.group(3)
            attrs_str = m.group(4) or ""
            alignment = cells_map.get((row, col)) or rows_map.get(row) or default
            col += 1
            result.append(_cell_tag_with_alignment(tag, attrs_str, alignment))
        pos = m.end()
    result.append(html[pos:])
    return "".join(result)


def _alignment_maps(
    cell_alignments: Any,
) -> tuple[str, dict[int, str], dict[tuple[int, int], str]]:
    default = cell_alignments.get("default", "")
    rows_map = {
        row_alignment[0]: row_alignment[1]
        for row_alignment in cell_alignments.get("rows") or []
        if isinstance(row_alignment, (list, tuple)) and len(row_alignment) >= 2
    }
    cells_map = {
        (cell_alignment[0], cell_alignment[1]): cell_alignment[2]
        for cell_alignment in cell_alignments.get("cells") or []
        if isinstance(cell_alignment, (list, tuple)) and len(cell_alignment) >= 3
    }
    return default, rows_map, cells_map


def _cell_tag_with_alignment(tag: str, attrs_str: str, alignment: str) -> str:
    if alignment not in VALID_ALIGNMENTS:
        return f"<{tag}{attrs_str}>"

    class_match = re.search(r'\bclass\s*=\s*(["\'])(.*?)\1', attrs_str)
    if not class_match:
        return f'<{tag}{attrs_str} class="td-align-{alignment}">'

    quote = class_match.group(1)
    existing = class_match.group(2)
    merged = f"{existing} td-align-{alignment}"
    full_class = f"class={quote}{merged}{quote}"
    new_attrs = attrs_str[: class_match.start()] + full_class + attrs_str[class_match.end() :]
    return f"<{tag}{new_attrs}>"
