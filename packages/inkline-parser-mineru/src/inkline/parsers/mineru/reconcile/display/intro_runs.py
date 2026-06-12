"""Intro/continuation display quote merging. Three passes: (1) parenthetical header + indented display merging, (2) short colon-ending intro + display body merging, (3) adjacent display-quote continuation block merging after an introducer."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ..constants import FLOAT_LIKE_TYPES
from ..block_access import block_bbox as _bbox, block_page as _block_page, block_pages as _block_pages
from ..layout_helpers import _canonical_quote_layout
from ..block_nav import _prev_text_non_float
from .helpers import (
    display_quote_multiline_seed,
    force_generic_quote_attrs,
    is_left_shifted_intro_before_display_lane_ds,
    is_parenthetical_time_header,
    is_short_display_text_block,
    merge_quote_run,
    quote_run_is_intro_continuation_candidate,
)


def reconcile_parenthetical_header_display_quote_runs(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        text = str(cur.get("text", "")).strip()
        cbb = _bbox(cur)
        if cur.get("type") != "paragraph" or not is_parenthetical_time_header(text) or not cbb:
            i += 1
            continue
        if float(cbb[0]) < layout.body_left + 45:
            i += 1
            continue
        page = _block_page(cur)
        end = i + 1
        while end < len(blocks):
            nxt = blocks[end]
            if nxt.get("type") in FLOAT_LIKE_TYPES:
                break
            if nxt.get("type") not in {"paragraph", "display_block"}:
                break
            ntext = str(nxt.get("text", "")).strip()
            if not ntext:
                break
            if is_parenthetical_time_header(ntext):
                break
            if _block_page(nxt) != page:
                break
            nbb = _bbox(nxt)
            if not nbb:
                break
            display_indented = float(nbb[0]) >= layout.body_left + 45
            if not display_indented and not _canonical_quote_layout(nxt, layout):
                break
            end += 1
        if end > i + 1:
            i = merge_quote_run(
                blocks,
                i,
                end,
                prev_text=_prev_text_non_float(blocks, i),
                reason="parenthetical_letter_display_block_layout",
            )
            continue
        i += 1


def reconcile_short_display_intro_quote_runs(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    i = 0
    while i + 1 < len(blocks):
        cur, nxt = blocks[i], blocks[i + 1]
        text = str(cur.get("text", "")).strip()
        if cur.get("type") != "display_block" or nxt.get("type") not in {"paragraph", "display_block"}:
            i += 1
            continue
        if not text.endswith(("：", ":")) or len(text) > 42:
            i += 1
            continue
        cp, np = _block_page(cur), _block_page(nxt)
        if cp is None or np is None or cp != np:
            i += 1
            continue
        cbb, nbb = _bbox(cur), _bbox(nxt)
        if not cbb or not nbb:
            i += 1
            continue
        if float(nbb[1]) - float(cbb[3]) > 45:
            i += 1
            continue
        if not _canonical_quote_layout(nxt, layout):
            i += 1
            continue
        nxt_text = str(nxt.get("text", "")).strip()
        if nxt_text.endswith(("：", ":")):
            i += 1
            continue
        nbb_check = _bbox(nxt)
        if nbb_check and nxt.get("type") == "paragraph":
            near_body = float(nbb_check[0]) <= layout.body_left + max(48.0, layout.body_width * 0.055)
            full_width = (float(nbb_check[2]) - float(nbb_check[0])) >= layout.body_width * 0.88
            if near_body and full_width:
                cbb_check = _bbox(cur)
                cur_near_body = cbb_check and float(cbb_check[0]) <= layout.body_left + max(48.0, layout.body_width * 0.055)
                cur_full_width = cbb_check and (float(cbb_check[2]) - float(cbb_check[0])) >= layout.body_width * 0.88
                if not (cur_near_body and cur_full_width):
                    i += 1
                    continue
        merge_quote_run(
            blocks,
            i,
            i + 2,
            prev_text=_prev_text_non_float(blocks, i),
            reason="formal_edict_display_block_layout",
        )
        continue


def reconcile_intro_display_quote_continuations(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if not quote_run_is_intro_continuation_candidate(cur, layout):
            i += 1
            continue
        if not display_quote_multiline_seed(cur.get("text", "")):
            i += 1
            continue
        prev_text = _prev_text_non_float(blocks, i)
        introduced = prev_text.rstrip().endswith(("：", ":"))
        if not introduced:
            i += 1
            continue
        end = i + 1
        while end < len(blocks):
            nxt = blocks[end]
            if nxt.get("type") in FLOAT_LIKE_TYPES:
                break
            if is_left_shifted_intro_before_display_lane_ds(blocks, end, layout):
                break
            if not is_short_display_text_block(nxt, layout):
                break
            cp = max(_block_pages(blocks[end - 1]) or [_block_page(blocks[end - 1]) or -1])
            np = _block_page(nxt)
            if cp is None or np is None or np > cp + 1:
                break
            end += 1
        if end > i + 1:
            merge_quote_run(
                blocks,
                i,
                end,
                prev_text=prev_text,
                reason="introduced_display_block_continuation_layout",
            )
            continue
        i += 1
