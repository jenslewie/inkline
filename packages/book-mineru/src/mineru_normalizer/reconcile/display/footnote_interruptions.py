"""Display quotes across footnote interruptions. Merges display quote continuations that are split by page-bottom footnotes. Detects when a display block at page bottom and another at next page top share the same visual lane."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ..constants import QUOTE_TYPES, _DEFAULT_PAGE_HEIGHT
from ..block_access import block_bbox as _bbox, block_page as _block_page, block_pages as _block_pages
from ..block_merge import _merge_block_pair, _refresh_canonical_quote_attrs
from ..layout_helpers import (
    _canonical_quote_layout, _ends_with_terminal,
    _is_near_page_bottom, _is_near_page_top, _page_coord_heights,
)
from ..block_nav import _prev_text_non_float
from .helpers import (
    display_lanes_compatible,
    has_display_attribution_line,
    is_single_line_display_continuation_fragment,
)


def reconcile_display_quote_across_footnote_interruptions(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") not in QUOTE_TYPES:
            i += 1
            continue
        page_heights = _page_coord_heights(blocks)
        spans_multiple_pages = len(_block_pages(cur)) > 1
        bb = _bbox(cur)
        page = _block_page(cur)
        lower_page_display = bool(bb and page is not None and float(bb[3]) >= page_heights.get(page, _DEFAULT_PAGE_HEIGHT) * 0.65)
        if not spans_multiple_pages and not lower_page_display and not _is_near_page_bottom(cur, page_heights):
            i += 1
            continue
        cp = max(_block_pages(cur) or [_block_page(cur) or -1])
        j = i + 1
        skipped: List[Dict[str, Any]] = []
        while j < len(blocks) and blocks[j].get("type") == "footnote":
            skipped.append({
                "page": _block_page(blocks[j]),
                "bbox": _bbox(blocks[j]),
                "block_id": blocks[j].get("block_id"),
                "type": blocks[j].get("type"),
            })
            j += 1
        skipped_footnotes = j > i + 1
        merged = False
        while j < len(blocks):
            nxt = blocks[j]
            np = _block_page(nxt)
            if np is None or np > cp + 1:
                break
            if np == cp + 1 and not _is_near_page_top(nxt, page_heights):
                break
            if (cur.get("attrs") or {}).get("has_attribution_line") or has_display_attribution_line(str(cur.get("text", ""))):
                break
            if not skipped_footnotes and _ends_with_terminal(str(cur.get("text", ""))):
                break
            nxt_is_quote = nxt.get("type") in QUOTE_TYPES
            nxt_is_display_paragraph = nxt.get("type") == "paragraph" and _canonical_quote_layout(nxt, layout)
            if not nxt_is_quote and not nxt_is_display_paragraph:
                break
            if not display_lanes_compatible(cur, nxt, layout):
                break
            nbb = _bbox(nxt)
            nxt_body_indent = nbb and float(nbb[0]) <= layout.body_left + max(48.0, layout.body_width * 0.055)
            nxt_body_width = nbb and (float(nbb[2]) - float(nbb[0])) >= layout.body_width * 0.88
            if nxt_body_indent and nxt_body_width:
                cbb_guard = _bbox(cur)
                cur_body_indent = cbb_guard and float(cbb_guard[0]) <= layout.body_left + max(48.0, layout.body_width * 0.055)
                cur_body_width = cbb_guard and (float(cbb_guard[2]) - float(cbb_guard[0])) >= layout.body_width * 0.88
                if not (cur_body_indent and cur_body_width):
                    break
            joiner = None if is_single_line_display_continuation_fragment(nxt, layout) else "newline"
            _merge_block_pair(
                cur,
                nxt,
                "display_quote_continuation_across_footnotes",
                {"footnote_interrupted_display_quote": True},
                skipped,
                joiner=joiner,
            )
            _refresh_canonical_quote_attrs(cur, prev_text=_prev_text_non_float(blocks, i))
            del blocks[j]
            cp = max(_block_pages(cur) or [cp])
            merged = True
        if not merged:
            i += 1
