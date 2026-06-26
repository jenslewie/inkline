"""Reconciliation pass re-export hub. All reconciliation functions are exported from here for use by canonical/core.py and tests."""

from __future__ import annotations

from .cross_page import merge_cross_page_paragraphs, resolve_source_pdf_path
from .display_block import reconcile_generic_display_block_structures
from .display_block.layout import reconcile_display_blocks
from .figure import reconcile_figure_captions
from .footnote import (
    merge_continuation_footnotes,
    promote_cross_page_footnote_continuation_paragraphs,
    promote_page_reference_list_footnotes,
    recover_unmarked_page_footnote_markers,
    split_page_footnote_blocks,
)
from .notes.markers import recover_missing_note_refs
from .notes.resolver import resolve_note_links
from .table import reconcile_table_continuations

__all__ = [
    "merge_continuation_footnotes",
    "merge_cross_page_paragraphs",
    "promote_cross_page_footnote_continuation_paragraphs",
    "promote_page_reference_list_footnotes",
    "reconcile_display_blocks",
    "reconcile_figure_captions",
    "reconcile_generic_display_block_structures",
    "reconcile_table_continuations",
    "recover_missing_note_refs",
    "recover_unmarked_page_footnote_markers",
    "resolve_note_links",
    "resolve_source_pdf_path",
    "split_page_footnote_blocks",
]
