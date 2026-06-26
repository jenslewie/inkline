"""Shared display block geometry helpers."""

from __future__ import annotations

from typing import Any, Dict

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, HEADING
from ..block_access import block_bbox as _bbox
from ..block_merge import _refresh_display_block_attrs
from ..layout_helpers import _scaled_body_metrics


def force_generic_display_block_attrs(
    b: Dict[str, Any],
    prev_text: str = "",
    evidence: str = "layout_defined_display_block",
) -> None:
    if b.get("type") == HEADING:
        b.pop("level", None)
    b["type"] = DISPLAY_BLOCK
    _refresh_display_block_attrs(b, prev_text=prev_text)
    attrs = b.setdefault("attrs", {})
    attrs["layout_role"] = "inline_display_block"
    ev = attrs.setdefault("classification_evidence", [])
    if evidence not in ev:
        ev.append(evidence)


def display_lanes_compatible(
    left: Dict[str, Any],
    right: Dict[str, Any],
    layout: LayoutStats,
    coord_width: float | None = None,
) -> bool:
    lbb = _bbox(left)
    rbb = _bbox(right)
    if not lbb or not rbb:
        return False
    body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    left_x0 = float(lbb[0])
    right_x0 = float(rbb[0])
    if abs(left_x0 - right_x0) <= max(36.0, body_width * 0.05):
        return True
    left_width = max(0.0, float(lbb[2]) - left_x0)
    right_width = max(0.0, float(rbb[2]) - right_x0)
    left_compact = left_width <= body_width * 0.58
    right_compact = right_width <= body_width * 0.58
    return (
        left_compact and right_compact and left_x0 >= body_left + 70 and right_x0 >= body_left + 70
    )
