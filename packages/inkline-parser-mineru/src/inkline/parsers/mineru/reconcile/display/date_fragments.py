"""Date-start prose fragment fixes. Demotes short date-start fragments (e.g. "1593 年 12 月上旬，...") that were misclassified as display quotes, then merges them across pages as normal paragraph continuations."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ..cjk import _is_cjk_numbered_item_block
from ..block_access import block_bbox as _bbox, block_page as _block_page
from ..block_merge import _merge_block_pair
from ..layout_helpers import (
    _canonical_quote_layout, _ends_with_terminal,
    _is_near_page_bottom, _is_near_page_top, _page_coord_heights,
)


def reconcile_false_short_date_quotes(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    for b in blocks:
        if b.get("type") != "display_block":
            continue
        text = str(b.get("text", "")).strip()
        if re.match(r"^\d{3,4}\s*年", text) and len(text) < 120 and not text.startswith("“"):
            b["type"] = "paragraph"
            b.pop("level", None)
            attrs = b.setdefault("attrs", {})
            for k in ["role", "content_form", "content_form_confidence", "content_form_scores", "classification_evidence", "quote_text", "attribution"]:
                attrs.pop(k, None)
            attrs["demoted_reason"] = "short_date_start_prose_fragment_not_display_block"


def reconcile_demoted_date_start_cross_page_paragraphs(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    page_heights = _page_coord_heights(blocks)
    i = 0
    while i + 1 < len(blocks):
        cur = blocks[i]
        nxt = blocks[i + 1]
        if cur.get("type") != "paragraph" or nxt.get("type") != "paragraph":
            i += 1
            continue
        text = str(cur.get("text", "")).strip()
        if not re.match(r"^\d{3,4}\s*年", text):
            i += 1
            continue
        if len(text) > 140 or _ends_with_terminal(text):
            i += 1
            continue
        cp, np = _block_page(cur), _block_page(nxt)
        if cp is None or np is None or np != cp + 1:
            i += 1
            continue
        if not (_is_near_page_bottom(cur, page_heights) and _is_near_page_top(nxt, page_heights)):
            i += 1
            continue
        if _is_cjk_numbered_item_block(nxt) or _canonical_quote_layout(nxt, layout):
            i += 1
            continue
        _merge_block_pair(
            cur,
            nxt,
            "date_start_fragment_cross_page_paragraph_continuation",
            {"date_start_fragment": True},
            [],
        )
        del blocks[i + 1]
        continue


def reconcile_date_start_cross_page_paragraph_attrs(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    for b in blocks:
        if b.get("type") != "paragraph":
            continue
        text = str(b.get("text", "")).strip()
        if not re.match(r"^\d{3,4}\s*年", text):
            continue
        src = b.get("source") or {}
        pages = src.get("pages") or []
        if len(pages) < 2:
            continue
        spans = src.get("spans") or []
        if len(spans) < 2:
            continue
        first_bbox = spans[0].get("bbox") or []
        next_bbox = spans[1].get("bbox") or []
        if len(first_bbox) < 4 or len(next_bbox) < 4:
            continue
        first_height = float(first_bbox[3]) - float(first_bbox[1])
        next_height = float(next_bbox[3]) - float(next_bbox[1])
        if first_height > 28 or float(first_bbox[1]) < layout.page_height * 0.85 or next_height < 180:
            continue
        attrs = b.get("attrs") or {}
        if attrs.get("merge_reason") != "cross_page_paragraph_continuation":
            continue
        raw_type = attrs.get("raw_type", "paragraph")
        new_attrs: Dict[str, Any] = {
            "raw_types": attrs.get("raw_types") or [raw_type],
            "demoted_reason": "short_date_start_prose_fragment_not_display_block",
        }
        if attrs.get("note_refs"):
            new_attrs["note_refs"] = attrs["note_refs"]
        if "inline_runs" in attrs:
            new_attrs["inline_runs"] = attrs["inline_runs"]
        if "merged_from" in attrs:
            new_attrs["merged_from"] = attrs["merged_from"]
        new_attrs["merge_reason"] = "date_start_fragment_cross_page_paragraph_continuation"
        new_attrs["merge_evidence"] = {"date_start_fragment": True}
        b["attrs"] = new_attrs
