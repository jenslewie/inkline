"""Record-style display quote merging. Merges compact record/receipt-style display excerpts across adjacent pages. Only repairs page-break splits; same-page entries are assumed to be separate dated records."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ..constants import FLOAT_LIKE_TYPES
from ..block_access import block_page as _block_page, block_pages as _block_pages
from ..layout_helpers import _is_near_page_bottom, _is_near_page_top, _page_coord_heights
from ..block_nav import _prev_text_non_float
from .helpers import is_era_month_header, looks_like_record_display_text, merge_quote_run


def reconcile_record_style_display_quote_runs(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    page_heights = _page_coord_heights(blocks)
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") != "display_block" or not looks_like_record_display_text(cur.get("text", "")):
            i += 1
            continue
        end = i + 1
        while end < len(blocks):
            nxt = blocks[end]
            if nxt.get("type") in FLOAT_LIKE_TYPES:
                break
            if nxt.get("type") not in {"paragraph", "display_block"}:
                break
            if not looks_like_record_display_text(nxt.get("text", "")):
                break
            if is_era_month_header(nxt, layout):
                break
            cp = max(_block_pages(blocks[end - 1]) or [_block_page(blocks[end - 1]) or -1])
            np = _block_page(nxt)
            if cp is None or np is None or np != cp + 1:
                break
            if not (_is_near_page_bottom(blocks[end - 1], page_heights) or _is_near_page_top(nxt, page_heights)):
                break
            end += 1
        if end > i + 1:
            merge_quote_run(
                blocks,
                i,
                end,
                prev_text=_prev_text_non_float(blocks, i),
                reason="record_style_display_block_continuation_layout",
            )
            continue
        i += 1
