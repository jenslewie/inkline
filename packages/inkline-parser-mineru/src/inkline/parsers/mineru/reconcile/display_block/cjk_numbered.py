"""CJK numbered display block reconciliation."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, HEADING, LIST_ITEM, PARAGRAPH
from ..block_access import block_bbox as _bbox, block_page as _block_page, block_pages as _block_pages
from ..block_merge import _merge_block_pair, _refresh_display_block_attrs
from ..block_nav import _prev_text_non_float, _prev_text_non_float_idx, _next_text_non_float_idx
from ..notes.keys import chinese_to_int as _chinese_to_int

def _cjk_list_marker_rank(text: str) -> Optional[int]:
    m = re.match(r"^\s*([一二三四五六七八九十百]+)、", text or "")
    if not m:
        return None
    return _chinese_to_int(m.group(1))


def _is_cjk_numbered_item_block(block: Dict[str, Any]) -> bool:
    return _cjk_list_marker_rank(str(block.get("text", ""))) is not None


def reconcile_cjk_numbered_display_blocks(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    """Treat visually displayed CJK-numbered clauses as display blocks, not lists.

    MinerU sometimes emits lines beginning with “一、二、三、...” as list blocks,
    and sometimes as normal paragraphs/titles.  In narrative history books these
    are often visually set off. If such numbered clauses are emitted as display
    text or appear in a numbered run, promote them to display_block and merge
    the run.
    """

    def force_numbered_display_block_attrs(b: Dict[str, Any], evidence: str) -> None:
        attrs = b.setdefault("attrs", {})
        attrs["layout_role"] = "inline_display_block"
        ev = attrs.setdefault("classification_evidence", [])
        if evidence not in ev:
            ev.append(evidence)
        if "cjk_numbered_display_block_layout" not in ev:
            ev.append("cjk_numbered_display_block_layout")

    def promote(idx: int, evidence: str) -> None:
        b = blocks[idx]
        b["type"] = DISPLAY_BLOCK
        attrs = b.setdefault("attrs", {})
        if "raw_types" not in attrs:
            attrs["raw_types"] = [attrs.get("raw_type", b.get("type"))]
        _refresh_display_block_attrs(b, prev_text=_prev_text_non_float(blocks, idx))
        force_numbered_display_block_attrs(b, evidence)

    # First promote explicit list_item blocks and paragraph/title blocks that are
    # part of an adjacent CJK-numbered run.  This catches cases where MinerU emits
    # “一、二” as a list and “三、...” at the top of the next page as a title.
    for idx, b in enumerate(blocks):
        if not _is_cjk_numbered_item_block(b):
            continue
        typ = b.get("type")
        if typ == LIST_ITEM:
            promote(idx, "promoted_from_cjk_numbered_list_item_by_layout")
            continue
        if typ in {PARAGRAPH, HEADING}:
            pi = _prev_text_non_float_idx(blocks, idx)
            ni = _next_text_non_float_idx(blocks, idx)
            prev_is_item = pi is not None and _is_cjk_numbered_item_block(blocks[pi]) and blocks[pi].get("type") == DISPLAY_BLOCK
            next_is_item = ni is not None and _is_cjk_numbered_item_block(blocks[ni]) and blocks[ni].get("type") in {LIST_ITEM, DISPLAY_BLOCK, PARAGRAPH}
            introduced = _prev_text_non_float(blocks, idx).rstrip().endswith(("：", ":"))
            if prev_is_item or next_is_item or introduced:
                promote(idx, "promoted_from_cjk_numbered_paragraph_or_heading_by_layout")

    # Then merge consecutive CJK-numbered display blocks.  Allow adjacent-page
    # continuation even after terminal punctuation, because each numbered clause
    # naturally ends with punctuation.
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") != DISPLAY_BLOCK or not _is_cjk_numbered_item_block(cur):
            i += 1
            continue
        cur_rank = _cjk_list_marker_rank(cur.get("text", ""))
        while i + 1 < len(blocks):
            nxt = blocks[i + 1]
            if nxt.get("type") != DISPLAY_BLOCK or not _is_cjk_numbered_item_block(nxt):
                break
            nxt_rank = _cjk_list_marker_rank(nxt.get("text", ""))
            if cur_rank is not None and nxt_rank is not None and nxt_rank < cur_rank:
                break
            cp = max(_block_pages(cur) or [_block_page(cur) or -1])
            np = _block_page(nxt)
            cbb = _bbox(cur)
            nbb = _bbox(nxt)
            same_or_next_page = np is not None and cp is not None and np <= cp + 1
            aligned_or_numbered = True
            if cbb and nbb and np == cp:
                aligned_or_numbered = float(nbb[0]) >= float(cbb[0]) - 40 and float(nbb[2]) <= float(cbb[2]) + 220
            if not same_or_next_page or not aligned_or_numbered:
                break
            _merge_block_pair(
                cur,
                nxt,
                "cjk_numbered_display_block_continuation",
                {"numbered_clause_layout": True},
                [],
                joiner="newline",
            )
            del blocks[i + 1]
            _refresh_display_block_attrs(cur, prev_text=_prev_text_non_float(blocks, i))
            force_numbered_display_block_attrs(cur, "merged_cjk_numbered_display_block")
            cur_rank = _cjk_list_marker_rank((cur.get("text") or "").split("\n")[-1]) or nxt_rank
        i += 1
