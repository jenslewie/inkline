"""Display block structure reconciliation. The reconcile_generic_display_block_structures() function runs two passes: pair-date structure reconciliation, then the cleanup pass orchestrator."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from .pair_date import reconcile_display_block_pair_and_date_structures
from .cleanup import reconcile_display_block_cleanup_structures


def reconcile_generic_display_block_structures(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    """Generic correction pass for recurring display block structures."""
    reconcile_display_block_pair_and_date_structures(blocks, layout)
    reconcile_display_block_cleanup_structures(blocks, layout)


__all__ = [
    "reconcile_generic_display_block_structures",
]
