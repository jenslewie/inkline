from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TableRow:
    cells: list[str]


@dataclass(frozen=True)
class TableView:
    html_fragment: str | None
    rows: list[TableRow]
    cell_alignments: Any
    notes: list[str]
