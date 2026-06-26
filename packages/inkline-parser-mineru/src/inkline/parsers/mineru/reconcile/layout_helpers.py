"""Layout helpers for reconciliation passes."""

from __future__ import annotations

from typing import Any, Dict, List

from ..analysis.layout import LayoutStats
from ..analysis.page_geometry import PageGeometry
from .block_access import block_bbox as _bbox
from .block_access import block_page as _block_page
from .constants import (
    _DEFAULT_PAGE_HEIGHT,
    _DISPLAY_MIN_LEFT_MARGIN,
    _DISPLAY_MIN_WIDTH_RATIO,
    _NEAR_PAGE_BOTTOM_RATIO,
    _NEAR_PAGE_TOP_RATIO,
)


def _scaled_body_metrics(
    layout: LayoutStats, coord_width: float | None
) -> tuple[float, float, float]:
    """Return body metrics in the coordinate space used by canonical bboxes."""
    if coord_width and layout.page_width and abs(coord_width - layout.page_width) > 1.0:
        scale = coord_width / layout.page_width
    else:
        scale = 1.0
    body_left = layout.body_left * scale
    body_right = layout.body_right * scale
    return body_left, body_right, max(1.0, body_right - body_left)


def _display_block_layout(
    b: Dict[str, Any], layout: LayoutStats, coord_width: float | None = None
) -> bool:
    bb = _bbox(b)
    if not bb:
        return False
    width = max(0.0, float(bb[2]) - float(bb[0]))
    body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    return (
        float(bb[0]) >= body_left + _DISPLAY_MIN_LEFT_MARGIN
        or width <= body_width * _DISPLAY_MIN_WIDTH_RATIO
    )


def _is_body_paragraph_layout(
    b: Dict[str, Any], layout: LayoutStats, coord_width: float | None = None
) -> bool:
    """Check if block has layout consistent with body prose (not display).

    A body paragraph typically sits at or near the body left margin and
    spans most of the body width.  Returns True when the block looks like
    normal narrative prose that should NOT be absorbed into a display run.
    """
    bb = _bbox(b)
    if not bb:
        return False
    x0 = float(bb[0])
    width = max(0.0, float(bb[2]) - x0)
    body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    near_body_left = x0 <= body_left + max(48.0, body_width * 0.06)
    near_body_width = width >= body_width * 0.88
    return near_body_left and near_body_width


def _page_coord_heights(blocks: List[Dict[str, Any]]) -> Dict[int, float]:
    return PageGeometry.from_canonical_blocks(blocks).coord_heights


def _page_coord_widths(blocks: List[Dict[str, Any]]) -> Dict[int, float]:
    return PageGeometry.from_canonical_blocks(blocks).coord_widths


def _is_near_page_bottom(b: Dict[str, Any], page_heights: Dict[int, float]) -> bool:
    p = _block_page(b)
    bb = _bbox(b)
    if p is None or not bb:
        return False
    h = page_heights.get(p, _DEFAULT_PAGE_HEIGHT)
    return float(bb[3]) >= h * _NEAR_PAGE_BOTTOM_RATIO


def _is_near_page_top(b: Dict[str, Any], page_heights: Dict[int, float]) -> bool:
    p = _block_page(b)
    bb = _bbox(b)
    if p is None or not bb:
        return False
    h = page_heights.get(p, _DEFAULT_PAGE_HEIGHT)
    return float(bb[1]) <= h * _NEAR_PAGE_TOP_RATIO
