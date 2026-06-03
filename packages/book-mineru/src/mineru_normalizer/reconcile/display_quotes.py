"""Display quote reconciliation (single pass). Merges adjacent display/quote blocks where the introducer and body are split by MinerU, and reconciles inline display quotes with the surrounding prose context."""

from __future__ import annotations

from typing import Any, Dict, List

from ..analysis.layout import LayoutStats
from .common import (
    QUOTE_TYPES, _bbox, _block_page, _block_pages,
    _canonical_quote_layout, _is_near_page_bottom,
    _is_near_page_top, _merge_block_pair, _page_coord_heights,
    _prev_text_non_float, _refresh_canonical_quote_attrs,
)

def reconcile_display_quotes(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    """Late quote reconciliation after cross-page paragraph merging.

    This pass fixes cases that cannot be solved page-locally:
      - a quote starts at the bottom of one page and the attribution is on the
        next page;
      - an introduced display quote is emitted as a normal paragraph because its
        bbox is only mildly indented;
      - a long display quote spans multiple paragraph boxes on the same page.
    """
    page_heights = _page_coord_heights(blocks)

    def has_loose_intro(prev_text: str) -> bool:
        # The late reconciliation pass intentionally uses a loose bbox test,
        # so require an explicit colon to avoid promoting ordinary narrative
        # paragraphs that merely mention sources such as "实录".
        return prev_text.rstrip().endswith(("：", ":"))

    # 1) Promote colon/source-introduced display quote paragraphs.
    for idx, b in enumerate(blocks):
        if b.get("type") != "paragraph":
            continue
        prev_text = _prev_text_non_float(blocks, idx)
        if has_loose_intro(prev_text) and _canonical_quote_layout(b, layout):
            b["type"] = "blockquote"
            attrs = b.setdefault("attrs", {})
            ev = attrs.setdefault("classification_evidence", [])
            if "promoted_by_intro_trigger_and_display_quote_layout" not in ev:
                ev.append("promoted_by_intro_trigger_and_display_quote_layout")
            _refresh_canonical_quote_attrs(b, prev_text=prev_text)

    # 2) If a page-bottom paragraph is immediately followed by a page-top
    #    blockquote, the first paragraph is the beginning of the same quote.
    i = 0
    while i + 1 < len(blocks):
        left = blocks[i]
        right = blocks[i + 1]
        if left.get("type") == "paragraph" and right.get("type") in QUOTE_TYPES:
            lp = _block_page(left)
            rp = _block_page(right)
            if (
                lp is not None
                and rp is not None
                and rp == lp + 1
                and _is_near_page_bottom(left, page_heights)
                and _is_near_page_top(right, page_heights)
                and _canonical_quote_layout(left, layout)
            ):
                left["type"] = right.get("type")
                _merge_block_pair(
                    left,
                    right,
                    "cross_page_display_quote_continuation_with_attribution",
                    {"left_fragment_promoted_to_quote": True},
                    [],
                )
                del blocks[i + 1]
                _refresh_canonical_quote_attrs(left, prev_text=_prev_text_non_float(blocks, i))
                continue
        i += 1

    # 3) Absorb aligned same-page continuation paragraphs after a quote.
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") not in QUOTE_TYPES:
            i += 1
            continue
        while i + 1 < len(blocks):
            nxt = blocks[i + 1]
            if nxt.get("type") not in {"paragraph", "blockquote"}:
                break
            cur_pages = _block_pages(cur)
            cur_last_page = max(cur_pages) if cur_pages else _block_page(cur)
            np = _block_page(nxt)
            if np is None or cur_last_page is None or np != cur_last_page:
                break
            cbb = _bbox(cur)
            nbb = _bbox(nxt)
            if not cbb or not nbb:
                break
            aligned = float(nbb[0]) >= float(cbb[0]) - 5 and float(nbb[2]) <= float(cbb[2]) + 20
            if not aligned:
                break
            nxt_text = str(nxt.get("text", "")).strip()
            if nxt.get("type") == "paragraph" and nxt_text.endswith(("：", ":")):
                break
            if (nxt.get("attrs") or {}).get("display_boundary_before"):
                break
            _merge_block_pair(
                cur,
                nxt,
                "same_page_display_quote_continuation",
                {"aligned_with_previous_quote_bbox": True},
                [],
                joiner="newline",
            )
            del blocks[i + 1]
            _refresh_canonical_quote_attrs(cur, prev_text=_prev_text_non_float(blocks, i))
        i += 1