"""Display block cleanup orchestrator.

Only geometry/structure passes run here. Text-form recognizers that used to
promote or merge display blocks from prose content are intentionally excluded
from the canonical pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from .body_paragraph_split import reconcile_display_block_body_paragraph_split
from .footnote_interruptions import reconcile_display_block_across_footnote_interruptions
from .overflow_tail_split import reconcile_page_bottom_overflow_tail_from_display_block
from .page_top import reconcile_page_top_set_off_display_blocks
from .right_align import reconcile_right_aligned_terminal_blocks


def reconcile_display_block_cleanup_structures(
    blocks: List[Dict[str, Any]], layout: LayoutStats
) -> None:
    reconcile_page_top_set_off_display_blocks(blocks, layout)
    reconcile_page_bottom_overflow_tail_from_display_block(blocks, layout)
    reconcile_display_block_body_paragraph_split(blocks, layout)
    reconcile_display_block_across_footnote_interruptions(blocks, layout)
    reconcile_display_block_body_paragraph_split(blocks, layout)
    reconcile_right_aligned_terminal_blocks(blocks, layout)
