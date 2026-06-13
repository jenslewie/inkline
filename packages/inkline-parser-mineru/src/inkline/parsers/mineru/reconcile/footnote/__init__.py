"""Footnote lifecycle re-export hub. Exports the three footnote lifecycle functions: split_page_footnote_blocks, promote_page_reference_list_footnotes, promote_cross_page_footnote_continuation_paragraphs, and merge_continuation_footnotes."""

from __future__ import annotations

from .merge import merge_continuation_footnotes
from .promote import (
    promote_cross_page_footnote_continuation_paragraphs,
    promote_page_reference_list_footnotes,
    recover_unmarked_page_footnote_markers,
    split_page_footnote_blocks,
)

__all__ = [
    "merge_continuation_footnotes",
    "promote_cross_page_footnote_continuation_paragraphs",
    "promote_page_reference_list_footnotes",
    "recover_unmarked_page_footnote_markers",
    "split_page_footnote_blocks",
]
