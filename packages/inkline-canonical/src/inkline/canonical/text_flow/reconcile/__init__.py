"""Parser-neutral reconciliation for logical TextFlow records."""

from typing import Any

from inkline.canonical.text_flow.reconcile.displays import (
    reconcile_cross_page_displays,
)
from inkline.canonical.text_flow.reconcile.footnotes import (
    reconcile_cross_page_footnotes,
)
from inkline.canonical.text_flow.reconcile.paragraphs import (
    reconcile_cross_page_paragraphs,
)

__all__ = [
    "reconcile_cross_page_displays",
    "reconcile_cross_page_footnotes",
    "reconcile_cross_page_paragraphs",
    "reconcile_text_flow_records",
    "reconcile_text_records",
]


def reconcile_text_flow_records(
    records: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run parser-neutral record reconciliation in dependency order."""

    reconciled = reconcile_cross_page_footnotes(records, page_layout)
    reconciled = reconcile_cross_page_paragraphs(reconciled, pages, page_layout)
    return reconcile_cross_page_displays(reconciled, pages, page_layout)


def reconcile_text_records(
    records: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Backward-compatible name for the parser-neutral orchestrator."""

    return reconcile_text_flow_records(records, pages, page_layout)
