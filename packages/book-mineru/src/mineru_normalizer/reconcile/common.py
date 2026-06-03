"""Compatibility re-export hub for legacy reconciliation imports.

New code should import directly from the real module:
  - block_access: block_page, block_bbox, block_id, block_pages
  - block_merge: _merge_block_pair, _merge_inline_runs, _refresh_canonical_quote_attrs
  - notes.keys: leading_note_marker, note_ref_key, chinese_to_int

This module also owns shared constants (QUOTE_TYPES, MERGEABLE_TEXT_TYPES,
FLOAT_LIKE_TYPES, TERMINAL_PUNCT) and a few layout/text helpers that have
not yet been relocated to their final module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..analysis.layout import LayoutStats
from ..analysis.page_geometry import PageGeometry
from ..extraction.text import normalize_ws, strip_trailing_text_note

_DEFAULT_PAGE_HEIGHT = 1000.0
_NEAR_PAGE_BOTTOM_RATIO = 0.82
_NEAR_PAGE_TOP_RATIO = 0.22
_QUOTE_MIN_LEFT_MARGIN = 18
_QUOTE_MIN_WIDTH_RATIO = 0.95

TERMINAL_PUNCT = set("。？！!?；;：:.”’\"'）】》」』")
FLOAT_LIKE_TYPES = {"figure", "caption", "table_continuation"}
MERGEABLE_TEXT_TYPES = {"paragraph", "list_item", "blockquote"}
QUOTE_TYPES = {"blockquote", "epigraph"}

from .block_access import block_id as _block_id
from .block_access import block_page as _block_page
from .block_access import block_pages as _block_pages
from .block_access import block_bbox as _bbox

from .block_merge import _merge_block_pair, _merge_inline_runs, _refresh_canonical_quote_attrs
from .block_merge import _join_text

from .notes.keys import chinese_to_int as _chinese_to_int
from .notes.keys import leading_note_marker as _leading_note_marker
from .notes.keys import note_ref_key as _note_ref_key


def _canonical_quote_layout(b: Dict[str, Any], layout: LayoutStats) -> bool:
    bb = _bbox(b)
    if not bb:
        return False
    width = max(0.0, float(bb[2]) - float(bb[0]))
    return float(bb[0]) >= layout.body_left + _QUOTE_MIN_LEFT_MARGIN or width <= layout.body_width * _QUOTE_MIN_WIDTH_RATIO


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


def _prev_text_non_float(blocks: List[Dict[str, Any]], idx: int) -> str:
    k = idx - 1
    while k >= 0:
        if blocks[k].get("type") not in FLOAT_LIKE_TYPES:
            return str(blocks[k].get("text", ""))
        k -= 1
    return ""


def _prev_text_non_float_idx(blocks: List[Dict[str, Any]], idx: int) -> Optional[int]:
    k = idx - 1
    while k >= 0:
        if blocks[k].get("type") not in FLOAT_LIKE_TYPES:
            return k
        k -= 1
    return None


def _next_text_non_float_idx(blocks: List[Dict[str, Any]], idx: int) -> Optional[int]:
    k = idx + 1
    while k < len(blocks):
        if blocks[k].get("type") not in FLOAT_LIKE_TYPES:
            return k
        k += 1
    return None
