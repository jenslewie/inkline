"""Reconciliation pass re-export hub. All reconciliation functions are exported from here for use by canonical/core.py and tests."""

from __future__ import annotations

from .cross_page import merge_cross_page_paragraphs, resolve_source_pdf_path
from .display_quotes import reconcile_display_quotes
from .cjk import reconcile_cjk_numbered_display_quotes
from .display import reconcile_generic_display_quote_structures
from .figures import reconcile_figure_captions
from .footnotes import (
    merge_continuation_footnotes,
    promote_cross_page_footnote_continuation_paragraphs,
    promote_page_reference_list_footnotes,
    recover_unmarked_page_footnote_markers,
    split_page_footnote_blocks,
)
from .notes import recover_missing_note_refs
from .notes import resolve_note_links
from .tables import reconcile_table_continuations

__all__ = [
    "merge_cross_page_paragraphs",
    "resolve_source_pdf_path",
    "reconcile_display_quotes",
    "reconcile_cjk_numbered_display_quotes",
    "reconcile_generic_display_quote_structures",
    "reconcile_figure_captions",
    "reconcile_table_continuations",
    "promote_page_reference_list_footnotes",
    "recover_unmarked_page_footnote_markers",
    "promote_cross_page_footnote_continuation_paragraphs",
    "merge_continuation_footnotes",
    "split_page_footnote_blocks",
    "recover_missing_note_refs",
    "resolve_note_links",
]
