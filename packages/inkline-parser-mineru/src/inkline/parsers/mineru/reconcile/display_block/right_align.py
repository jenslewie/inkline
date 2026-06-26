"""Right-aligned terminal block detection. Promotes short, right-aligned blocks
at page/chapter endings (dates, colophons, signatures, place-names) to display_block
with alignment="right"."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, HEADING, PARAGRAPH
from ..block_access import block_bbox as _bbox
from ..block_access import block_page as _block_page
from ..block_merge import _refresh_display_block_attrs
from ..block_nav import _prev_text_non_float
from ..constants import FLOAT_LIKE_TYPES
from ..layout_helpers import (
    _is_near_page_bottom,
    _page_coord_heights,
    _page_coord_widths,
    _scaled_body_metrics,
)


def reconcile_right_aligned_terminal_blocks(
    blocks: List[Dict[str, Any]], layout: LayoutStats
) -> None:
    """Promote right-aligned terminal blocks (dates, colophons, signatures) to
    display_block with alignment="right".

    Detection criteria (all must hold):
      1. Block is short text (1-3 lines, max line <= 60 chars).
      2. Block right edge is near body_right (right-aligned).
      3. Block left edge is past body center (not just indented).
      4. Block is near page bottom OR has significant gap from preceding text.
      5. Following block (if any) is on a different page or is also right-aligned.
    """
    page_heights = _page_coord_heights(blocks)
    page_widths = _page_coord_widths(blocks)

    for idx, b in enumerate(blocks):
        if b.get("type") not in {PARAGRAPH, HEADING}:
            continue
        if not _is_right_aligned_terminal_candidate(
            b, blocks, idx, layout, page_heights, page_widths
        ):
            continue

        # Promote to display_block
        b["type"] = DISPLAY_BLOCK
        b.pop("level", None)
        _refresh_display_block_attrs(b, prev_text=_prev_text_non_float(blocks, idx))
        attrs = b.setdefault("attrs", {})
        attrs["layout_form"] = "short_line_group"
        attrs["alignment"] = "right"
        sh = attrs.setdefault("style_hints", {})
        sh["text_align"] = "right"
        ev = attrs.setdefault("classification_evidence", [])
        if "right_aligned_terminal_block" not in ev:
            ev.append("right_aligned_terminal_block")


def _is_right_aligned_terminal_candidate(
    b: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_heights: Dict[int, float],
    page_widths: Dict[int, float] | None = None,
) -> bool:
    text = str(b.get("text", "")).strip()
    if not text:
        return False
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return False
    # Must be short: few lines, short line lengths
    if len(lines) > 3:
        return False
    if max(len(ln) for ln in lines) > 60:
        return False

    bb = _bbox(b)
    if not bb:
        return False
    x0 = float(bb[0])
    x2 = float(bb[2])
    width = max(0.0, x2 - x0)

    page = _block_page(b)
    if page is None:
        return False
    body_left, body_right, body_width = _scaled_body_metrics(
        layout, page_widths.get(page) if page_widths else None
    )

    # Must be right-aligned: right edge near body_right
    right_near_edge = x2 >= body_right - max(80.0, body_width * 0.08)
    if not right_near_edge:
        return False

    # Left edge must be past body center (not just mildly indented)
    body_center = (body_left + body_right) / 2.0
    past_center = x0 >= body_center - max(40.0, body_width * 0.05)
    # Width must be compact (not a full-width block at right margin)
    compact = width <= body_width * 0.55
    if not past_center or not compact:
        return False

    # Position: near bottom of page OR significant gap from previous block
    at_page_end = _is_near_page_bottom(b, page_heights)

    # Gap from previous non-float block
    gap_from_prev = False
    for j in range(idx - 1, -1, -1):
        prev = blocks[j]
        if prev.get("type") in FLOAT_LIKE_TYPES:
            continue
        if _block_page(prev) != page:
            break
        pbb = _bbox(prev)
        if pbb:
            gap = float(bb[1]) - float(pbb[3])
            prev_height = float(pbb[3]) - float(pbb[1])
            min_gap = max(30.0, prev_height * 1.5)
            gap_from_prev = gap >= min_gap
        break

    if not (at_page_end or gap_from_prev):
        return False

    # Check following block: if same-page, neighbouring body prose should not
    # be too close
    nxt = blocks[idx + 1] if idx + 1 < len(blocks) else None
    if nxt is not None:
        nxt_page = _block_page(nxt)
        if nxt_page == page:
            nbb = _bbox(nxt)
            if nbb:
                nxt_at_left = float(nbb[0]) <= body_left + max(48.0, body_width * 0.06)
                nxt_width = max(0.0, float(nbb[2]) - float(nbb[0]))
                nxt_full_width = nxt_width >= body_width * 0.88
                if nxt_at_left and nxt_full_width:
                    gap = float(nbb[1]) - float(bb[3])
                    block_height = float(bb[3]) - float(bb[1])
                    if gap < max(20.0, block_height * 0.5):
                        return False

    return True
