"""Parser-neutral reconciliation for logical TextFlow records."""

from inkline.canonical.text_flow.reconcile.footnotes import (
    reconcile_cross_page_footnotes,
)

__all__ = ["reconcile_cross_page_footnotes"]
