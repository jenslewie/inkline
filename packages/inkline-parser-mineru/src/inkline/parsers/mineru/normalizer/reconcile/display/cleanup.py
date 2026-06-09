"""Display quote cleanup orchestrator. Runs a sequence of display quote cleanup passes in dependency order: date fragment demotion → intro merging → footnote interruptions → page-top set-off → record-style runs → page-bottom tail splitting."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from .page_top import reconcile_page_top_set_off_display_blocks

from .date_fragments import (
    reconcile_false_short_date_quotes,
    reconcile_demoted_date_start_cross_page_paragraphs,
    reconcile_date_start_cross_page_paragraph_attrs,
)
from .intro_runs import (
    reconcile_parenthetical_header_display_quote_runs,
    reconcile_short_display_intro_quote_runs,
    reconcile_intro_display_quote_continuations,
)
from .record_runs import reconcile_record_style_display_quote_runs
from .quote_tail_split import reconcile_page_bottom_overflow_tail_from_quotes
from .footnote_interruptions import reconcile_display_quote_across_footnote_interruptions


def reconcile_display_quote_cleanup_structures(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    reconcile_false_short_date_quotes(blocks, layout)
    reconcile_demoted_date_start_cross_page_paragraphs(blocks, layout)
    reconcile_date_start_cross_page_paragraph_attrs(blocks, layout)
    reconcile_parenthetical_header_display_quote_runs(blocks, layout)
    reconcile_short_display_intro_quote_runs(blocks, layout)
    reconcile_intro_display_quote_continuations(blocks, layout)
    reconcile_display_quote_across_footnote_interruptions(blocks, layout)
    reconcile_page_top_set_off_display_blocks(blocks, layout)
    reconcile_record_style_display_quote_runs(blocks, layout)
    reconcile_page_bottom_overflow_tail_from_quotes(blocks, layout)
