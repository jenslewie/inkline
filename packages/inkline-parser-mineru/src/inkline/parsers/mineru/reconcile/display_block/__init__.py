"""Display block structure reconciliation."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from .cleanup import reconcile_display_block_cleanup_structures


def reconcile_generic_display_block_structures(
    blocks: List[Dict[str, Any]], layout: LayoutStats
) -> None:
    """Run geometry-first display block cleanup passes."""
    reconcile_display_block_cleanup_structures(blocks, layout)


__all__ = [
    "reconcile_generic_display_block_structures",
]
