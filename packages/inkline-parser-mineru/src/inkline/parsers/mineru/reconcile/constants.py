"""Shared constants for reconciliation passes."""

from __future__ import annotations

TERMINAL_PUNCT = set('。？！!?；;：:.”’\"\'）】》」』')
FLOAT_LIKE_TYPES = {"figure", "caption", "table_continuation"}
MERGEABLE_TEXT_TYPES = {"paragraph", "list_item", "blockquote"}
QUOTE_TYPES = {"blockquote", "epigraph"}

_DEFAULT_PAGE_HEIGHT = 1000.0
_NEAR_PAGE_BOTTOM_RATIO = 0.82
_NEAR_PAGE_TOP_RATIO = 0.22
_QUOTE_MIN_LEFT_MARGIN = 18
_QUOTE_MIN_WIDTH_RATIO = 0.95