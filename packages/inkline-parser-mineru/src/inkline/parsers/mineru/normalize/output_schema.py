"""Display block normalization for the output layout schema."""

from __future__ import annotations

from typing import Any, Dict, List

from ..schema.block_types import DISPLAY_BLOCK
from ..schema.patterns import ATTR_RE

INTERNAL_DISPLAY_ATTR_KEYS = {
    "content_form",
    "content_form_confidence",
    "content_form_scores",
    "classification_evidence",
    "attribution",
    "source_block_type",
    "source_role",
    "role",
    "quote_text",
}


def _display_layout_form(b: Dict[str, Any]) -> str:
    attrs = b.get("attrs") or {}
    if attrs.get("layout_form"):
        return str(attrs["layout_form"])
    lines = [ln.strip() for ln in str(b.get("text", "")).split("\n") if ln.strip()]
    if len(lines) >= 2:
        short_ratio = sum(len(ln) <= 36 for ln in lines) / len(lines)
        if max(len(ln) for ln in lines) <= 60 and short_ratio >= 0.6:
            return "short_line_group"
    return "set_off_text"


def _normalize_display_item_attrs(item: Dict[str, Any]) -> None:
    text = str(item.get("text", ""))
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    item["layout_form"] = (
        "short_line_group"
        if len(lines) >= 2 and max((len(ln) for ln in lines), default=0) <= 60
        else "set_off_text"
    )
    item["line_count"] = len(lines)
    item["has_attribution_line"] = any(ATTR_RE.match(ln) for ln in lines)
    for key in INTERNAL_DISPLAY_ATTR_KEYS:
        item.pop(key, None)


def normalize_display_blocks_for_layout_schema(blocks: List[Dict[str, Any]]) -> None:
    """Normalize public display-block attrs for layout-oriented consumers."""
    for b in blocks:
        if b.get("type") != DISPLAY_BLOCK:
            continue
        attrs = b.setdefault("attrs", {})
        lines = [ln.strip() for ln in str(b.get("text", "")).split("\n") if ln.strip()]
        attrs["layout_form"] = _display_layout_form(b)
        attrs["layout_role"] = attrs.get("layout_role", "inline_display_block")
        attrs["line_count"] = len(lines)
        attrs["has_attribution_line"] = any(ATTR_RE.match(ln) for ln in lines)
        for item in attrs.get("items") or []:
            if isinstance(item, dict):
                _normalize_display_item_attrs(item)
        for key in INTERNAL_DISPLAY_ATTR_KEYS:
            attrs.pop(key, None)


def remove_internal_note_ref_indexes(blocks: List[Dict[str, Any]]) -> None:
    """Remove legacy parallel note-ref indexes from public canonical output.

    New pipeline code uses ``inline_runs`` as the sole writable representation.
    The cleanup remains for older canonical inputs accepted by compatibility
    paths.
    """
    for block in blocks:
        attrs = block.get("attrs")
        if not isinstance(attrs, dict):
            continue
        attrs.pop("note_refs", None)
        attrs.pop("_middle_page_inline_markers", None)
        for item in attrs.get("items") or []:
            if isinstance(item, dict):
                item.pop("note_refs", None)
