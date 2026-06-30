"""Body-flow geometry helpers for display block reconciliation."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import PARAGRAPH
from ..block_access import block_bbox as _bbox
from ..block_access import block_page as _block_page
from ..block_access import block_pages as _block_pages
from ..layout_helpers import _page_coord_heights, _scaled_body_metrics


def block_bboxes_on_pages(block: Dict[str, Any], pages: set[int]) -> List[List[float]]:
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


def page_body_left_for_page(
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
        for bb in block_bboxes_on_pages(block, {page}):
            width = max(0.0, float(bb[2]) - float(bb[0]))
            if width >= scaled_body_width * 0.70:
                candidates.append(float(bb[0]))
    if not candidates:
        return scaled_body_left
    return min(candidates)


def has_cross_page_body_flow_spans(
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
        if not span_has_body_flow_layout(blocks, cur, int(page), bbox, layout, page_widths):
            return False
    return checked >= 2


def span_has_body_flow_layout(
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
    body_left = page_body_left_for_page(blocks, page, cur, layout, page_widths)
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


def is_page_top_large_block(
    blocks: List[Dict[str, Any]],
    block: Dict[str, Any],
    bbox: List[Any],
    page: int,
    layout: LayoutStats,
) -> bool:
    page_height = _page_coord_heights(blocks).get(page, layout.page_height)
    height = max(0.0, float(bbox[3]) - float(bbox[1]))
    return float(bbox[1]) <= page_height * 0.25 and height >= page_height * 0.45
