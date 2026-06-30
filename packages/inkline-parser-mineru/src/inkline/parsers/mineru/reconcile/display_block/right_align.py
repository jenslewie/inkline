"""Right-aligned terminal block detection. Promotes short, right-aligned blocks
at page/chapter endings (dates, colophons, signatures, place-names) to display_block
with alignment="right"."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class _RightAlignMetrics:
    bbox: List[Any]
    page: int
    body_left: float
    body_right: float
    body_width: float
    x0: float
    x2: float
    width: float


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
    if not _has_short_terminal_text(b):
        return False
    metrics = _right_align_metrics(b, layout, page_widths)
    if metrics is None:
        return False
    if not _is_right_aligned_compact(metrics):
        return False
    if not _has_terminal_position(b, blocks, idx, metrics, page_heights):
        return False
    return not _has_close_following_body_prose(blocks, idx, metrics)


def _has_short_terminal_text(block: Dict[str, Any]) -> bool:
    text = str(block.get("text", "")).strip()
    if not text:
        return False
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return bool(lines) and len(lines) <= 3 and max(len(line) for line in lines) <= 60


def _right_align_metrics(
    block: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
) -> _RightAlignMetrics | None:
    bbox = _bbox(block)
    page = _block_page(block)
    if not bbox or page is None:
        return None
    body_left, body_right, body_width = _scaled_body_metrics(
        layout, page_widths.get(page) if page_widths else None
    )
    x0 = float(bbox[0])
    x2 = float(bbox[2])
    return _RightAlignMetrics(
        bbox=bbox,
        page=page,
        body_left=body_left,
        body_right=body_right,
        body_width=body_width,
        x0=x0,
        x2=x2,
        width=max(0.0, x2 - x0),
    )


def _is_right_aligned_compact(metrics: _RightAlignMetrics) -> bool:
    right_near_edge = metrics.x2 >= metrics.body_right - max(80.0, metrics.body_width * 0.08)
    body_center = (metrics.body_left + metrics.body_right) / 2.0
    past_center = metrics.x0 >= body_center - max(40.0, metrics.body_width * 0.05)
    compact = metrics.width <= metrics.body_width * 0.55
    return right_near_edge and past_center and compact


def _has_terminal_position(
    block: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    idx: int,
    metrics: _RightAlignMetrics,
    page_heights: Dict[int, float],
) -> bool:
    return _is_near_page_bottom(block, page_heights) or _has_gap_from_previous_text(
        blocks, idx, metrics
    )


def _has_gap_from_previous_text(
    blocks: List[Dict[str, Any]], idx: int, metrics: _RightAlignMetrics
) -> bool:
    for j in range(idx - 1, -1, -1):
        prev = blocks[j]
        if prev.get("type") in FLOAT_LIKE_TYPES:
            continue
        if _block_page(prev) != metrics.page:
            return False
        return _has_terminal_gap(metrics.bbox, _bbox(prev))
    return False


def _has_terminal_gap(bbox: List[Any], previous_bbox: List[Any] | None) -> bool:
    if not previous_bbox:
        return False
    gap = float(bbox[1]) - float(previous_bbox[3])
    prev_height = float(previous_bbox[3]) - float(previous_bbox[1])
    return gap >= max(30.0, prev_height * 1.5)


def _has_close_following_body_prose(
    blocks: List[Dict[str, Any]], idx: int, metrics: _RightAlignMetrics
) -> bool:
    next_block = blocks[idx + 1] if idx + 1 < len(blocks) else None
    if next_block is None or _block_page(next_block) != metrics.page:
        return False
    next_bbox = _bbox(next_block)
    if not next_bbox or not _is_body_width_neighbor(next_bbox, metrics):
        return False
    gap = float(next_bbox[1]) - float(metrics.bbox[3])
    block_height = float(metrics.bbox[3]) - float(metrics.bbox[1])
    return gap < max(20.0, block_height * 0.5)


def _is_body_width_neighbor(bbox: List[Any], metrics: _RightAlignMetrics) -> bool:
    at_left = float(bbox[0]) <= metrics.body_left + max(48.0, metrics.body_width * 0.06)
    width = max(0.0, float(bbox[2]) - float(bbox[0]))
    return at_left and width >= metrics.body_width * 0.88
