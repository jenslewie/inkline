"""Display block normalization for the output layout schema. Converts blockquote/poem blocks to the public display_block type, normalizes line_layouts and other layout-first attributes for downstream consumers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schema.patterns import ATTR_RE

DISPLAY_SOURCE_TYPES = {"blockquote", "epigraph", "epigraph_group"}
INTERNAL_DISPLAY_ATTR_KEYS = {
    "content_form",
    "content_form_confidence",
    "content_form_scores",
    "classification_evidence",
    "quote_text",
    "attribution",
    "source_block_type",
    "source_role",
}


def _display_layout_form(b: Dict[str, Any]) -> str:
    typ = b.get("type")
    attrs = b.get("attrs") or {}
    role = attrs.get("role")
    if typ == "epigraph_group":
        return "standalone_sparse_page_group"
    if typ == "epigraph" or role == "part_or_chapter_epigraph":
        return "standalone_sparse_page"
    lines = [ln.strip() for ln in str(b.get("text", "")).split("\n") if ln.strip()]
    if len(lines) >= 2:
        short_ratio = sum(len(ln) <= 36 for ln in lines) / len(lines)
        if max(len(ln) for ln in lines) <= 60 and short_ratio >= 0.6:
            return "short_line_group"
    return "set_off_text"


def _display_layout_role(old_type: str, old_role: Optional[str]) -> str:
    if old_type == "epigraph_group":
        return "standalone_display_group"
    if old_type == "epigraph" or old_role == "part_or_chapter_epigraph":
        return "standalone_display_page"
    return "inline_display_block"


def _normalize_display_item_attrs(item: Dict[str, Any]) -> None:
    text = str(item.get("text", ""))
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    item["layout_form"] = "short_line_group" if len(lines) >= 2 and max((len(ln) for ln in lines), default=0) <= 60 else "set_off_text"
    item["line_count"] = len(lines)
    item["has_attribution_line"] = any(ATTR_RE.match(ln) for ln in lines)
    for key in INTERNAL_DISPLAY_ATTR_KEYS:
        item.pop(key, None)


def normalize_display_blocks_for_layout_schema(blocks: List[Dict[str, Any]]) -> None:
    """Collapse internal display-text labels into a layout-first block type.

    Reconciliation still uses the richer internal quote/poem/epigraph labels to
    avoid throwing away the existing repair logic. This final pass keeps the
    canonical schema more portable by making the public item type layout-based.
    """
    for b in blocks:
        old_type = str(b.get("type", ""))
        if old_type not in DISPLAY_SOURCE_TYPES:
            continue
        attrs = b.setdefault("attrs", {})
        old_role = attrs.get("role")
        lines = [ln.strip() for ln in str(b.get("text", "")).split("\n") if ln.strip()]
        attrs["layout_form"] = _display_layout_form(b)
        attrs["layout_role"] = _display_layout_role(old_type, old_role)
        attrs["line_count"] = len(lines)
        attrs["has_attribution_line"] = any(ATTR_RE.match(ln) for ln in lines)
        attrs.pop("role", None)
        for item in attrs.get("items") or []:
            if isinstance(item, dict):
                _normalize_display_item_attrs(item)
        for key in INTERNAL_DISPLAY_ATTR_KEYS:
            attrs.pop(key, None)
        b["type"] = "display_block"


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
