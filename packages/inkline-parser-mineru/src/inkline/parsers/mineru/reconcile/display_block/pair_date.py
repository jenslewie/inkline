"""Pair and date structure reconciliation. Detects and reconciles paired display structures (e.g. label: value) and date-stamped entries that MinerU split across blocks."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, PARAGRAPH
from ...schema.patterns import ATTR_RE
from ..constants import FLOAT_LIKE_TYPES
from ..block_access import block_bbox as _bbox, block_page as _block_page
from ..block_nav import _prev_text_non_float
from ..layout_helpers import _display_block_layout
from .helpers import _is_era_month_header, _is_lunar_day_entry, merge_display_block_run

def _reconcile_attribution_display_blocks(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    """Merge a display block line followed by an attribution line.

    This is layout-based, not ID-based. Typical shape: a short/indented
    display block followed by a right-shifted attribution beginning with an em dash.
    """
    i = 0
    while i + 1 < len(blocks):
        cur = blocks[i]
        nxt = blocks[i + 1]
        if cur.get("type") in FLOAT_LIKE_TYPES or nxt.get("type") in FLOAT_LIKE_TYPES:
            i += 1
            continue
        cur_text = str(cur.get("text", "")).strip()
        nxt_text = str(nxt.get("text", "")).strip()
        if not cur_text or not ATTR_RE.match(nxt_text):
            i += 1
            continue
        cp = _block_page(cur)
        np = _block_page(nxt)
        if cp is None or np is None or np != cp:
            i += 1
            continue
        cbb = _bbox(cur)
        nbb = _bbox(nxt)
        cur_display = _display_block_layout(cur, layout) or len(cur_text) <= 90
        attribution_position = bool(cbb and nbb and float(nbb[0]) >= float(cbb[0]) - 5)
        if cur.get("type") in {PARAGRAPH, DISPLAY_BLOCK} and cur_display and attribution_position:
            merge_display_block_run(
                blocks,
                i,
                i + 2,
                prev_text=_prev_text_non_float(blocks, i),
                reason="display_block_with_attribution_layout",
            )
            continue
        i += 1


def _reconcile_diary_date_display_block_runs(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    """Merge dated diary/extract runs such as '癸巳年五月' + dated entries.

    These are source excerpts laid out as display text. Detection uses
    the calendar heading/date-entry structure and local layout, not block IDs.
    """
    i = 0
    while i < len(blocks):
        if blocks[i].get("type") in FLOAT_LIKE_TYPES:
            i += 1
            continue
        text = str(blocks[i].get("text", "")).strip()
        if not _is_era_month_header(blocks[i], layout):
            i += 1
            continue
        # Require the following textual block to be a dated entry; otherwise this
        # could be a normal short paragraph.
        j = i + 1
        while j < len(blocks) and blocks[j].get("type") in FLOAT_LIKE_TYPES:
            j += 1
        if j >= len(blocks) or not _is_lunar_day_entry(blocks[j], layout):
            i += 1
            continue
        # Keep one month section per display block. Stop at the next month header
        # or at the first non-date-entry prose paragraph.
        end = j + 1
        while end < len(blocks):
            if blocks[end].get("type") in FLOAT_LIKE_TYPES:
                end += 1
                continue
            t = str(blocks[end].get("text", "")).strip()
            if _is_era_month_header(blocks[end], layout):
                break
            if _is_lunar_day_entry(blocks[end], layout):
                end += 1
                continue
            break
        i = merge_display_block_run(
            blocks,
            i,
            end,
            prev_text=_prev_text_non_float(blocks, i),
            reason="diary_date_display_block_layout",
        )


def reconcile_display_block_pair_and_date_structures(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    _reconcile_attribution_display_blocks(blocks, layout)
    _reconcile_diary_date_display_block_runs(blocks, layout)
