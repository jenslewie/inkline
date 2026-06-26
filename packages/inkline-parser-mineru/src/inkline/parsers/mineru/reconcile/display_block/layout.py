"""Display block reconciliation."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, FOOTNOTE, PARAGRAPH
from ..block_access import block_bbox as _bbox
from ..block_access import block_page as _block_page
from ..block_access import block_pages as _block_pages
from ..block_merge import _merge_block_pair, _refresh_display_block_attrs
from ..block_nav import _prev_text_non_float
from ..constants import FLOAT_LIKE_TYPES
from ..layout_helpers import (
    _display_block_layout,
    _is_body_paragraph_layout,
    _is_near_page_bottom,
    _is_near_page_top,
    _page_coord_heights,
    _page_coord_widths,
    _scaled_body_metrics,
)


def reconcile_display_blocks(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    """Late display block reconciliation after cross-page paragraph merging.

    This pass fixes cases that cannot be solved page-locally:
      - a display run starts at the bottom of one page and the attribution is on the
        next page;
      - a visually set-off block is emitted as a normal paragraph because its
        bbox is only mildly indented;
      - a long display run spans multiple paragraph boxes on the same page.
    """
    page_heights = _page_coord_heights(blocks)
    page_widths = _page_coord_widths(blocks)

    # 1) Promote page-local set-off display paragraphs using geometry only.
    for idx, b in enumerate(blocks):
        if b.get("type") != PARAGRAPH:
            continue
        prev_text = _prev_text_non_float_or_footnote(blocks, idx)
        if (b.get("attrs") or {}).get("display_boundary_after_float_body_resume"):
            b["type"] = DISPLAY_BLOCK
            _refresh_display_block_attrs(b, prev_text=prev_text)
            attrs = b.setdefault("attrs", {})
            ev = attrs.setdefault("classification_evidence", [])
            if "promoted_after_float_body_resume_boundary" not in ev:
                ev.append("promoted_after_float_body_resume_boundary")
            continue
        if _is_indented_display_paragraph(blocks, idx, layout, page_widths, page_heights):
            b["type"] = DISPLAY_BLOCK
            attrs = b.setdefault("attrs", {})
            ev = attrs.setdefault("classification_evidence", [])
            if "promoted_by_page_local_indented_display_layout" not in ev:
                ev.append("promoted_by_page_local_indented_display_layout")
            _refresh_display_block_attrs(b, prev_text=prev_text)

    # 2) If a page-bottom paragraph is immediately followed by a page-top
    #    display block, the first paragraph belongs to the same display run.
    i = 0
    while i + 1 < len(blocks):
        left = blocks[i]
        right = blocks[i + 1]
        if left.get("type") == PARAGRAPH and right.get("type") == DISPLAY_BLOCK:
            lp = _block_page(left)
            rp = _block_page(right)
            if (
                lp is not None
                and rp is not None
                and rp == lp + 1
                and _is_near_page_bottom(left, page_heights)
                and _is_near_page_top(right, page_heights)
                and _display_block_layout(left, layout, page_widths.get(lp))
            ):
                left["type"] = DISPLAY_BLOCK
                _merge_block_pair(
                    left,
                    right,
                    "cross_page_display_block_continuation_with_attribution",
                    {"left_fragment_promoted_to_display_block": True},
                    [],
                )
                del blocks[i + 1]
                _refresh_display_block_attrs(left, prev_text=_prev_text_non_float(blocks, i))
                continue
        i += 1

    # 3) Absorb aligned same-page continuation paragraphs after a display block.
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") != DISPLAY_BLOCK:
            i += 1
            continue
        while i + 1 < len(blocks):
            nxt = blocks[i + 1]
            if nxt.get("type") not in {PARAGRAPH, DISPLAY_BLOCK}:
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
            if (nxt.get("attrs") or {}).get("display_boundary_before"):
                break
            if nxt.get("type") == PARAGRAPH and _is_narrow_bridge_between_display_blocks(
                blocks, i + 1, layout, page_widths
            ):
                break
            if nxt.get("type") == PARAGRAPH and _is_vertical_context_paragraph_after_display(
                blocks, i, i + 1, layout, page_widths
            ):
                break
            # Stop when the next block has body-paragraph layout — normal
            # prose has resumed.
            if nxt.get("type") == PARAGRAPH and _is_body_paragraph_layout(
                nxt, layout, page_widths.get(np)
            ):
                break
            _merge_block_pair(
                cur,
                nxt,
                "same_page_display_block_continuation",
                {"aligned_with_previous_display_block_bbox": True},
                [],
                joiner="newline",
            )
            del blocks[i + 1]
            _refresh_display_block_attrs(cur, prev_text=_prev_text_non_float(blocks, i))
        i += 1


def _is_vertical_context_paragraph_after_display(
    blocks: List[Dict[str, Any]],
    display_idx: int,
    paragraph_idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[display_idx]
    nxt = blocks[paragraph_idx]
    cbb = _bbox(cur)
    nbb = _bbox(nxt)
    page = _block_page(nxt)
    if not cbb or not nbb or page is None:
        return False
    lines = [line.strip() for line in str(nxt.get("text") or "").split("\n") if line.strip()]
    if len(lines) != 1:
        return False
    following = _next_same_page_text_block(blocks, paragraph_idx, page)
    if not following or following.get("type") != PARAGRAPH:
        return False
    fbb = _bbox(following)
    if not fbb:
        return False
    coord_width = page_widths.get(page) if page_widths else None
    _body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    height = max(1.0, float(nbb[3]) - float(nbb[1]))
    gap_from_display = float(nbb[1]) - float(cbb[3])
    gap_to_following = float(fbb[1]) - float(nbb[3])
    far_from_display = gap_from_display >= max(24.0, height * 1.5, body_width * 0.03)
    close_to_following = 0 <= gap_to_following <= max(18.0, height * 1.1, body_width * 0.025)
    return far_from_display and close_to_following


def _is_vertical_context_paragraph_after_previous_display(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    page = _block_page(blocks[idx])
    if page is None:
        return False
    prev_idx = idx - 1
    while prev_idx >= 0:
        prev = blocks[prev_idx]
        if prev.get("type") == FOOTNOTE or prev.get("type") in FLOAT_LIKE_TYPES:
            prev_idx -= 1
            continue
        if _block_page(prev) != page:
            return False
        if prev.get("type") != DISPLAY_BLOCK:
            return False
        return _is_vertical_context_paragraph_after_display(
            blocks, prev_idx, idx, layout, page_widths
        )
    return False


def _next_same_page_text_block(
    blocks: List[Dict[str, Any]], start: int, page: int
) -> Dict[str, Any] | None:
    for candidate in blocks[start + 1 :]:
        cp = _block_page(candidate)
        if cp is None:
            continue
        if cp != page:
            return None
        if candidate.get("type") == FOOTNOTE or candidate.get("type") in FLOAT_LIKE_TYPES:
            continue
        if str(candidate.get("text") or "").strip():
            return candidate
    return None


def _is_indented_display_paragraph(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
    page_heights: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    if cur.get("type") != PARAGRAPH:
        return False
    text = str(cur.get("text") or "").strip()
    if not text:
        return False
    bb = _bbox(cur)
    if not bb:
        return False
    page = _block_page(cur)
    source_pages = _block_pages(cur)
    spans_multiple_pages = len(source_pages) >= 2
    coord_width = page_widths.get(page) if page is not None and page_widths else None
    _scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    body_left = _page_body_left(blocks, cur, layout, page_widths)
    if body_left is None:
        return False
    if spans_multiple_pages and _has_cross_page_body_flow_spans(blocks, cur, layout, page_widths):
        return False
    page_top_after_prior_page_footnote = _is_page_top_set_off_after_prior_page_footnote(
        blocks, idx, layout, page_heights
    )
    x0 = float(bb[0])
    width = max(0.0, float(bb[2]) - x0)
    indent_threshold = (
        max(28.0, scaled_body_width * 0.04)
        if page_top_after_prior_page_footnote
        else max(34.0, scaled_body_width * 0.045)
    )
    indented = x0 >= body_left + indent_threshold
    long_enough = width >= scaled_body_width * 0.45
    max_width_ratio = 1.15 if spans_multiple_pages or page_top_after_prior_page_footnote else 0.98
    not_full_body_lane = width <= scaled_body_width * max_width_ratio and (
        not _is_body_paragraph_layout(cur, layout, coord_width)
        or x0 >= body_left + indent_threshold
    )
    if not (indented and long_enough and not_full_body_lane):
        return False
    if not spans_multiple_pages and _has_tight_body_flow_from_previous_paragraph(
        blocks, idx, layout, page_widths, page_heights
    ):
        return False
    if _is_vertical_context_paragraph_after_previous_display(blocks, idx, layout, page_widths):
        return False

    before_footnote = _is_page_end_set_off_before_footnote(blocks, idx, layout, page_widths)
    bounded_group = _is_bounded_set_off_group_member(blocks, idx, layout, page_widths)
    page_top_before_body = _is_page_top_set_off_before_body(
        blocks, idx, layout, page_widths, page_heights
    )
    between_body_boundaries = _is_single_set_off_between_body_boundaries(
        blocks, idx, layout, page_widths
    )
    after_narrow_bridge = _is_set_off_after_narrow_bridge_before_body(
        blocks, idx, layout, page_widths
    )
    has_set_off_boundary = (
        before_footnote
        or bounded_group
        or page_top_before_body
        or page_top_after_prior_page_footnote
        or between_body_boundaries
        or after_narrow_bridge
    )
    if _is_long_body_lane_paragraph(blocks, idx, layout, page_widths) and not has_set_off_boundary:
        return False
    return (
        spans_multiple_pages
        or before_footnote
        or bounded_group
        or page_top_before_body
        or page_top_after_prior_page_footnote
        or between_body_boundaries
        or after_narrow_bridge
    )


def _prev_text_non_float_or_footnote(blocks: List[Dict[str, Any]], idx: int) -> str:
    k = idx - 1
    while k >= 0:
        if blocks[k].get("type") == FOOTNOTE or blocks[k].get("type") in FLOAT_LIKE_TYPES:
            k -= 1
            continue
        return str(blocks[k].get("text", ""))
    return ""


def _body_flow_resumes_after_float(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    if cur.get("type") != PARAGRAPH:
        return False
    page = _block_page(cur)
    if page is None or not _is_body_like_paragraph(cur, layout, page_widths):
        return False
    prev = _previous_content_block(blocks, idx)
    if prev is None or _block_page(prev) != page or prev.get("type") not in FLOAT_LIKE_TYPES:
        return False
    nxt = _next_same_page_paragraph(blocks, idx)
    return _is_body_like_paragraph(nxt, layout, page_widths)


def _previous_content_block(blocks: List[Dict[str, Any]], idx: int) -> Dict[str, Any] | None:
    for candidate in reversed(blocks[:idx]):
        if candidate.get("type") == FOOTNOTE:
            continue
        if candidate.get("text") or candidate.get("type") in FLOAT_LIKE_TYPES:
            return candidate
    return None


def _previous_same_page_paragraph(blocks: List[Dict[str, Any]], idx: int) -> Dict[str, Any] | None:
    page = _block_page(blocks[idx])
    for candidate in reversed(blocks[:idx]):
        if candidate.get("type") == FOOTNOTE:
            continue
        if _block_page(candidate) != page:
            return None
        if candidate.get("type") == PARAGRAPH:
            return candidate
        return None
    return None


def _next_same_page_paragraph(blocks: List[Dict[str, Any]], idx: int) -> Dict[str, Any] | None:
    page = _block_page(blocks[idx])
    for candidate in blocks[idx + 1 :]:
        if _block_page(candidate) != page:
            return None
        if candidate.get("type") == FOOTNOTE:
            continue
        if candidate.get("type") == PARAGRAPH:
            return candidate
        return None
    return None


def _has_tight_body_flow_from_previous_paragraph(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
    page_heights: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    page = _block_page(cur)
    if page is None or not _is_body_like_paragraph(cur, layout, page_widths):
        return False
    prev = _previous_same_page_paragraph(blocks, idx)
    if not _is_body_like_paragraph(prev, layout, page_widths):
        return False
    cur_bb = _bbox(cur)
    prev_bb = _bbox(prev) if prev else None
    if not cur_bb or not prev_bb:
        return False
    vertical_gap = float(cur_bb[1]) - float(prev_bb[3])
    if vertical_gap < 0:
        return False
    coord_height = page_heights.get(page) if page_heights else None
    if coord_height is None:
        return False
    tight_gap_limit = max(18.0, coord_height * 0.018)
    return vertical_gap <= tight_gap_limit


def _is_page_end_set_off_before_footnote(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    page = _block_page(cur)
    if page is None:
        return False
    next_block = blocks[idx + 1] if idx + 1 < len(blocks) else None
    if not next_block or next_block.get("type") != FOOTNOTE or _block_page(next_block) != page:
        return False
    prev_block = blocks[idx - 1] if idx > 0 else None
    if not prev_block or prev_block.get("type") != PARAGRAPH or _block_page(prev_block) != page:
        return False
    cur_bb = _bbox(cur)
    prev_bb = _bbox(prev_block)
    if not cur_bb or not prev_bb:
        return False
    coord_width = page_widths.get(page) if page_widths else None
    scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    prev_x0 = float(prev_bb[0])
    prev_width = max(0.0, float(prev_bb[2]) - prev_x0)
    prev_body_like = (
        prev_x0 <= scaled_body_left + max(45.0, scaled_body_width * 0.06)
        and prev_width >= scaled_body_width * 0.55
    )
    vertical_gap = float(cur_bb[1]) - float(prev_bb[3])
    return prev_body_like and vertical_gap >= max(14.0, scaled_body_width * 0.018)


def _is_bounded_set_off_group_member(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    page = _block_page(cur)
    if page is None:
        return False
    has_set_off_neighbor = any(
        _is_same_page_set_off_block(blocks, neighbor_idx, page, layout, page_widths)
        for neighbor_idx in (idx - 1, idx + 1)
    )
    if not has_set_off_neighbor:
        return False
    return _has_body_boundary(blocks, idx, -1, page, layout, page_widths) and _has_body_boundary(
        blocks, idx, 1, page, layout, page_widths
    )


def _is_set_off_after_narrow_bridge_before_body(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    page = _block_page(cur)
    if page is None or idx < 2:
        return False
    prev = blocks[idx - 1]
    before_prev = blocks[idx - 2]
    nxt = blocks[idx + 1] if idx + 1 < len(blocks) else None
    if _block_page(prev) != page or _block_page(before_prev) != page:
        return False
    if before_prev.get("type") != DISPLAY_BLOCK:
        return False
    if not _is_narrow_set_off_bridge(prev, blocks, page, layout, page_widths):
        return False
    if not _is_body_like_paragraph(nxt, layout, page_widths):
        return False
    cur_bb = _bbox(cur)
    prev_bb = _bbox(prev)
    before_bb = _bbox(before_prev)
    if not cur_bb or not prev_bb or not before_bb:
        return False
    coord_width = page_widths.get(page) if page_widths else None
    _scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    cur_width = _bbox_width(cur_bb)
    prev_width = _bbox_width(prev_bb)
    before_width = _bbox_width(before_bb)
    aligned_left = abs(float(cur_bb[0]) - float(prev_bb[0])) <= max(
        32.0, scaled_body_width * 0.05
    ) and abs(float(cur_bb[0]) - float(before_bb[0])) <= max(32.0, scaled_body_width * 0.05)
    wider_than_bridge = cur_width >= max(prev_width * 1.35, scaled_body_width * 0.45)
    follows_display_width = before_width >= max(prev_width * 1.35, scaled_body_width * 0.45)
    gap_from_bridge = float(cur_bb[1]) - float(prev_bb[3])
    gap_to_body = float((_bbox(nxt) or [0, 0, 0, 0])[1]) - float(cur_bb[3])
    gap_limit = max(58.0, scaled_body_width * 0.08)
    return (
        aligned_left
        and wider_than_bridge
        and follows_display_width
        and 0 <= gap_from_bridge <= gap_limit
        and 0 <= gap_to_body <= gap_limit
    )


def _is_narrow_bridge_between_display_blocks(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    if idx <= 0 or idx + 1 >= len(blocks):
        return False
    cur = blocks[idx]
    page = _block_page(cur)
    if page is None:
        return False
    prev = blocks[idx - 1]
    nxt = blocks[idx + 1]
    if (
        cur.get("type") != PARAGRAPH
        or prev.get("type") != DISPLAY_BLOCK
        or nxt.get("type") != DISPLAY_BLOCK
        or _block_page(prev) != page
        or _block_page(nxt) != page
    ):
        return False
    if not _is_narrow_set_off_bridge(cur, blocks, page, layout, page_widths):
        return False
    cur_bb = _bbox(cur)
    prev_bb = _bbox(prev)
    next_bb = _bbox(nxt)
    if not cur_bb or not prev_bb or not next_bb:
        return False
    coord_width = page_widths.get(page) if page_widths else None
    _scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    bridge_width = _bbox_width(cur_bb)
    prev_width = _bbox_width(prev_bb)
    next_width = _bbox_width(next_bb)
    aligned_left = abs(float(cur_bb[0]) - float(prev_bb[0])) <= max(
        32.0, scaled_body_width * 0.05
    ) and abs(float(cur_bb[0]) - float(next_bb[0])) <= max(32.0, scaled_body_width * 0.05)
    wide_neighbors = prev_width >= max(
        bridge_width * 1.35, scaled_body_width * 0.45
    ) and next_width >= max(bridge_width * 1.35, scaled_body_width * 0.45)
    prev_gap = float(cur_bb[1]) - float(prev_bb[3])
    next_gap = float(next_bb[1]) - float(cur_bb[3])
    gap_limit = max(58.0, scaled_body_width * 0.08)
    return (
        aligned_left
        and wide_neighbors
        and 0 <= prev_gap <= gap_limit
        and 0 <= next_gap <= gap_limit
    )


def _is_narrow_set_off_bridge(
    block: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    page: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    if block.get("type") != PARAGRAPH or _block_page(block) != page:
        return False
    bb = _bbox(block)
    if not bb:
        return False
    coord_width = page_widths.get(page) if page_widths else None
    _scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    body_left = _page_body_left(blocks, block, layout, page_widths)
    if body_left is None:
        return False
    x0 = float(bb[0])
    width = _bbox_width(bb)
    return (
        x0 >= body_left + max(34.0, scaled_body_width * 0.045)
        and width <= scaled_body_width * 0.58
        and not _is_body_like_paragraph(block, layout, page_widths)
    )


def _is_page_top_set_off_before_body(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
    page_heights: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    page = _block_page(cur)
    bb = _bbox(cur)
    if page is None or not bb:
        return False
    next_idx = idx + 1
    if not _is_body_like_paragraph(
        blocks[next_idx] if next_idx < len(blocks) else None, layout, page_widths
    ):
        return False
    coord_height = page_heights.get(page) if page_heights else None
    if coord_height is None:
        return False
    page_top_limit = max(220.0, coord_height * 0.14)
    return float(bb[1]) <= page_top_limit


def _is_page_top_set_off_after_prior_page_footnote(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_heights: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    page = _block_page(cur)
    bb = _bbox(cur)
    if page is None or not bb:
        return False
    prev = blocks[idx - 1] if idx > 0 else None
    if not prev or prev.get("type") != FOOTNOTE:
        return False
    prev_page = _block_page(prev)
    if prev_page is None or prev_page >= page:
        return False
    coord_height = page_heights.get(page) if page_heights else None
    if coord_height is None:
        return False
    page_top_limit = max(220.0, coord_height * 0.14)
    return float(bb[1]) <= page_top_limit


def _is_single_set_off_between_body_boundaries(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    page = _block_page(cur)
    if page is None:
        return False
    return _has_body_boundary(blocks, idx, -1, page, layout, page_widths) and _has_body_boundary(
        blocks, idx, 1, page, layout, page_widths
    )


def _has_body_boundary(
    blocks: List[Dict[str, Any]],
    idx: int,
    step: int,
    page: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    j = idx + step
    while 0 <= j < len(blocks):
        candidate = blocks[j]
        candidate_page = _block_page(candidate)
        if candidate.get("type") == FOOTNOTE:
            j += step
            continue
        if candidate_page != page:
            return False
        if _is_same_page_set_off_block(blocks, j, page, layout, page_widths):
            j += step
            continue
        return _is_body_like_paragraph(candidate, layout, page_widths)
    return False


def _is_same_page_set_off_block(
    blocks: List[Dict[str, Any]],
    idx: int,
    page: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    if idx < 0 or idx >= len(blocks):
        return False
    block = blocks[idx]
    if block.get("type") not in {PARAGRAPH, DISPLAY_BLOCK} or _block_page(block) != page:
        return False
    bb = _bbox(block)
    if not bb:
        return False
    coord_width = page_widths.get(page) if page_widths else None
    body_left = _page_body_left(blocks, block, layout, page_widths)
    _scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    x0 = float(bb[0])
    width = max(0.0, float(bb[2]) - x0)
    return (
        body_left is not None
        and x0 >= body_left + max(34.0, scaled_body_width * 0.045)
        and scaled_body_width * 0.45 <= width <= scaled_body_width * 0.98
    )


def _is_body_like_paragraph(
    block: Dict[str, Any] | None,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    if not block or block.get("type") != PARAGRAPH:
        return False
    bb = _bbox(block)
    page = _block_page(block)
    if not bb or page is None:
        return False
    coord_width = page_widths.get(page) if page_widths else None
    scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    x0 = float(bb[0])
    width = max(0.0, float(bb[2]) - x0)
    return (
        x0 <= scaled_body_left + max(48.0, scaled_body_width * 0.06)
        and width >= scaled_body_width * 0.70
    )


def _bbox_width(bbox: List[float]) -> float:
    return max(0.0, float(bbox[2]) - float(bbox[0]))


def _page_body_left(
    blocks: List[Dict[str, Any]],
    cur: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> float | None:
    pages = set(_block_pages(cur))
    page = _block_page(cur)
    if page is not None:
        pages.add(page)
    coord_width = page_widths.get(page) if page is not None and page_widths else None
    scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    candidates: List[float] = []
    for block in blocks:
        if block is cur or block.get("type") != PARAGRAPH:
            continue
        block_pages = set(_block_pages(block))
        block_page = _block_page(block)
        if block_page is not None:
            block_pages.add(block_page)
        if pages and not (pages & block_pages):
            continue
        for bb in _block_bboxes_on_pages(block, pages):
            width = max(0.0, float(bb[2]) - float(bb[0]))
            if width >= scaled_body_width * 0.70:
                candidates.append(float(bb[0]))
    if not candidates:
        return scaled_body_left
    return min([*candidates, scaled_body_left])


def _page_body_left_for_page(
    blocks: List[Dict[str, Any]],
    page: int,
    cur: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> float:
    coord_width = page_widths.get(page) if page_widths else None
    scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    candidates: List[float] = []
    for block in blocks:
        if block is cur or block.get("type") != PARAGRAPH:
            continue
        for bb in _block_bboxes_on_pages(block, {page}):
            width = max(0.0, float(bb[2]) - float(bb[0]))
            if width >= scaled_body_width * 0.70:
                candidates.append(float(bb[0]))
    if not candidates:
        return scaled_body_left
    return min([*candidates, scaled_body_left])


def _block_bboxes_on_pages(block: Dict[str, Any], pages: set[int]) -> List[List[float]]:
    source = block.get("source") or {}
    span_bboxes: List[List[float]] = []
    for span in source.get("spans") or []:
        span_page = span.get("page")
        span_bbox = span.get("bbox")
        if span_page in pages and isinstance(span_bbox, list) and len(span_bbox) >= 4:
            span_bboxes.append(span_bbox)
    if span_bboxes:
        return span_bboxes
    block_page = _block_page(block)
    bb = _bbox(block)
    if block_page in pages and bb:
        return [bb]
    return []


def _has_cross_page_body_flow_spans(
    blocks: List[Dict[str, Any]],
    cur: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    spans = [
        span for span in (cur.get("source") or {}).get("spans") or [] if isinstance(span, dict)
    ]
    pages = _block_pages(cur)
    if len(pages) < 2 or len(spans) < 2:
        return False
    checked = 0
    for span in spans:
        page = span.get("page")
        bbox = span.get("bbox")
        if page is None or not isinstance(bbox, list) or len(bbox) < 4:
            continue
        checked += 1
        if not _span_has_body_flow_layout(blocks, cur, int(page), bbox, layout, page_widths):
            return False
    return checked >= 2


def _span_has_body_flow_layout(
    blocks: List[Dict[str, Any]],
    cur: Dict[str, Any],
    page: int,
    bbox: List[float],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    coord_width = page_widths.get(page) if page_widths else None
    _scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    body_left = _page_body_left_for_page(blocks, page, cur, layout, page_widths)
    x0 = float(bbox[0])
    width = max(0.0, float(bbox[2]) - x0)
    if width < scaled_body_width * 0.65:
        return False
    near_body_left = x0 <= body_left + max(48.0, scaled_body_width * 0.06)
    indent = x0 - body_left
    first_line_indent = (
        max(34.0, scaled_body_width * 0.045) <= indent <= max(82.0, scaled_body_width * 0.11)
    )
    return near_body_left or first_line_indent


def _is_long_body_lane_paragraph(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    cur = blocks[idx]
    if cur.get("type") != PARAGRAPH:
        return False
    text = str(cur.get("text") or "").strip()
    if len(text) < 50:
        return False
    bb = _bbox(cur)
    page = _block_page(cur)
    if not bb or page is None:
        return False
    pages = _block_pages(cur)
    if len(pages) >= 2:
        page_height = _page_coord_heights(blocks).get(page, layout.page_height)
        height = max(0.0, float(bb[3]) - float(bb[1]))
        page_top_large_block = float(bb[1]) <= page_height * 0.25 and height >= page_height * 0.45
        if page_top_large_block:
            return False
    coord_width = page_widths.get(page) if page_widths else None
    _scaled_body_left, _scaled_body_right, scaled_body_width = _scaled_body_metrics(
        layout, coord_width
    )
    body_left = _page_body_left(blocks, cur, layout, page_widths)
    if body_left is None:
        return False
    x0 = float(bb[0])
    width = max(0.0, float(bb[2]) - x0)
    near_body_left = x0 <= body_left + max(55.0, scaled_body_width * 0.07)
    body_width = width >= scaled_body_width * 0.90
    return near_body_left and body_width
