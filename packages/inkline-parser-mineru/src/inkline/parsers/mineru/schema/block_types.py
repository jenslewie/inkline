"""Canonical block type names used by the MinerU parser."""

from __future__ import annotations

from inkline.canonical import BLOCK_TYPES

HEADING = "heading"
PARAGRAPH = "paragraph"
TOC_ITEM = "toc_item"
DISPLAY_BLOCK = "display_block"
LIST_ITEM = "list_item"
TABLE = "table"
TABLE_CONTINUATION = "table_continuation"
FIGURE = "figure"
CAPTION = "caption"
FOOTNOTE = "footnote"

CANONICAL_BLOCK_TYPES = (
    HEADING,
    PARAGRAPH,
    TOC_ITEM,
    DISPLAY_BLOCK,
    LIST_ITEM,
    TABLE,
    TABLE_CONTINUATION,
    FIGURE,
    CAPTION,
    FOOTNOTE,
)

if set(CANONICAL_BLOCK_TYPES) != BLOCK_TYPES:
    raise RuntimeError("MinerU block type names are out of sync with inkline.canonical")
