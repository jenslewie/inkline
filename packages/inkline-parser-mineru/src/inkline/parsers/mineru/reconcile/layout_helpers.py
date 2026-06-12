"""Layout and text helpers for reconciliation passes."""

from __future__ import annotations

from typing import Any, Dict, List

from ..analysis.layout import LayoutStats
from ..analysis.page_geometry import PageGeometry
from ..extraction.text import normalize_ws, strip_trailing_text_note
from .block_access import block_bbox as _bbox
from .block_access import block_page as _block_page
from .block_merge import _join_text
from .constants import TERMINAL_PUNCT, _DEFAULT_PAGE_HEIGHT, _NEAR_PAGE_BOTTOM_RATIO, _NEAR_PAGE_TOP_RATIO, _DISPLAY_MIN_LEFT_MARGIN, _DISPLAY_MIN_WIDTH_RATIO


def _display_block_layout(b: Dict[str, Any], layout: LayoutStats) -> bool:
    bb = _bbox(b)
    if not bb:
        return False
    width = max(0.0, float(bb[2]) - float(bb[0]))
    return float(bb[0]) >= layout.body_left + _DISPLAY_MIN_LEFT_MARGIN or width <= layout.body_width * _DISPLAY_MIN_WIDTH_RATIO


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


def _ends_with_terminal(text: str) -> bool:
    t = normalize_ws(text or "")
    t, _ = strip_trailing_text_note(t)
    t = t.rstrip()
    return bool(t and t[-1] in TERMINAL_PUNCT)
