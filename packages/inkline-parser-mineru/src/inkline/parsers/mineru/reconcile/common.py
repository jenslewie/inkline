"""Compatibility re-export hub for legacy reconciliation imports.

New code should import directly from the real module:
  - constants: TERMINAL_PUNCT, FLOAT_LIKE_TYPES, MERGEABLE_TEXT_TYPES, QUOTE_TYPES, _DEFAULT_PAGE_HEIGHT, etc.
  - layout_helpers: _canonical_quote_layout, _page_coord_heights, _page_coord_widths, _is_near_page_bottom, _is_near_page_top, _ends_with_terminal
  - block_nav: _prev_text_non_float, _prev_text_non_float_idx, _next_text_non_float_idx
  - block_access: block_page, block_bbox, block_id, block_pages
  - block_merge: _merge_block_pair, _merge_inline_runs, _refresh_canonical_quote_attrs
  - notes.keys: leading_note_marker, note_ref_key, chinese_to_int
"""

from __future__ import annotations

# --- Constants ---
from .constants import (
    TERMINAL_PUNCT,
    FLOAT_LIKE_TYPES,
    MERGEABLE_TEXT_TYPES,
    QUOTE_TYPES,
    _DEFAULT_PAGE_HEIGHT,
    _NEAR_PAGE_BOTTOM_RATIO,
    _NEAR_PAGE_TOP_RATIO,
    _QUOTE_MIN_LEFT_MARGIN,
    _QUOTE_MIN_WIDTH_RATIO,
)

# --- Block access ---
from .block_access import block_id as _block_id
from .block_access import block_page as _block_page
from .block_access import block_pages as _block_pages
from .block_access import block_bbox as _bbox

# --- Block merge ---
from .block_merge import _merge_block_pair, _merge_inline_runs, _refresh_canonical_quote_attrs
from .block_merge import _join_text

# --- Notes keys ---
from .notes.keys import chinese_to_int as _chinese_to_int
from .notes.keys import leading_note_marker as _leading_note_marker
from .notes.keys import note_ref_key as _note_ref_key

# --- Layout helpers ---
from .layout_helpers import (
    _canonical_quote_layout,
    _page_coord_heights,
    _page_coord_widths,
    _is_near_page_bottom,
    _is_near_page_top,
    _ends_with_terminal,
)

# --- Block navigation ---
from .block_nav import (
    _prev_text_non_float,
    _prev_text_non_float_idx,
    _next_text_non_float_idx,
)