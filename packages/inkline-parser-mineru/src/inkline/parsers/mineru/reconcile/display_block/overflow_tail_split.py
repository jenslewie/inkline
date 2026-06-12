"""Page-bottom display block overflow tail split. Splits a page-bottom display block when its final line is prose narrative rather than displayed text, converting the tail back to a paragraph and merging it with the next page's prose."""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, PARAGRAPH
from ..block_access import block_bbox as _bbox, block_page as _block_page, block_pages as _block_pages
from ..block_merge import _merge_block_pair, _refresh_display_block_attrs
from ..layout_helpers import (
    _ends_with_terminal, _is_near_page_bottom, _is_near_page_top, _page_coord_heights,
)
from ..block_nav import _prev_text_non_float
from ..notes.keys import note_ref_key as _note_ref_key


def reconcile_page_bottom_overflow_tail_from_display_block(blocks: List[Dict[str, Any]], layout: LayoutStats) -> None:
    page_heights = _page_coord_heights(blocks)
    i = 0
    while i + 1 < len(blocks):
        b = blocks[i]
        nxt = blocks[i + 1]
        if b.get("type") != DISPLAY_BLOCK or nxt.get("type") != PARAGRAPH:
            i += 1
            continue
        bp = max(_block_pages(b) or [_block_page(b) or -1])
        np = _block_page(nxt)
        if bp is None or np is None or np != bp + 1:
            i += 1
            continue
        if not (_is_near_page_bottom(b, page_heights) and _is_near_page_top(nxt, page_heights)):
            i += 1
            continue
        text = str(b.get("text", ""))
        if "\n" not in text:
            i += 1
            continue
        kept_display_block_text, tail = text.rsplit("\n", 1)
        kept_display_block_text = kept_display_block_text.rstrip()
        tail = tail.lstrip()
        if not kept_display_block_text or not tail:
            i += 1
            continue
        if not _ends_with_terminal(kept_display_block_text) or _ends_with_terminal(tail):
            i += 1
            continue
        display_block_runs, tail_runs = _split_inline_runs_at_last_newline((b.get("attrs") or {}).get("inline_runs"))
        display_block_refs, tail_refs = _split_note_refs_by_runs((b.get("attrs") or {}).get("note_refs"), display_block_runs, tail_runs)
        b["text"] = kept_display_block_text
        _refresh_display_block_attrs(b, prev_text=_prev_text_non_float(blocks, i))
        attrs = b.setdefault("attrs", {})
        if display_block_runs:
            attrs["inline_runs"] = display_block_runs
        if display_block_refs is not None:
            attrs["note_refs"] = display_block_refs
        ev = attrs.setdefault("classification_evidence", [])
        if "split_page_bottom_overflow_tail_from_display_block" not in ev:
            ev.append("split_page_bottom_overflow_tail_from_display_block")

        new_para = copy.deepcopy(b)
        new_para["block_id"] = f"{b.get('block_id')}_tail"
        new_para["type"] = PARAGRAPH
        new_para["text"] = tail
        new_para.pop("level", None)
        nattrs = new_para.setdefault("attrs", {})
        for k in ["role", "content_form", "content_form_confidence", "content_form_scores", "classification_evidence", "quote_text", "attribution"]:
            nattrs.pop(k, None)
        nattrs["split_from_display_block_id"] = b.get("block_id")
        if tail_runs:
            nattrs["inline_runs"] = tail_runs
        if tail_refs is not None:
            nattrs["note_refs"] = tail_refs
        new_para["block_id"] = nxt.get("block_id", new_para["block_id"])
        _merge_block_pair(new_para, nxt, "split_display_block_tail_joined_to_page_top_paragraph", {"narrative_tail": True}, [])
        del blocks[i + 1]
        blocks.insert(i + 1, new_para)
        i += 2


def _split_inline_runs_at_last_newline(runs: Any) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not isinstance(runs, list):
        return [], []
    split_run_index = -1
    split_char_index = -1
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or run.get("type") != "text":
            continue
        char_index = str(run.get("text", "")).rfind("\n")
        if char_index >= 0:
            split_run_index = index
            split_char_index = char_index
    if split_run_index < 0:
        return [], []

    display_block_runs: List[Dict[str, Any]] = []
    tail_runs: List[Dict[str, Any]] = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        copied = dict(run)
        if index < split_run_index:
            display_block_runs.append(copied)
        elif index > split_run_index:
            tail_runs.append(copied)
        else:
            text = str(copied.get("text", ""))
            before = text[:split_char_index].rstrip()
            after = text[split_char_index + 1:].lstrip()
            if before:
                display_block_runs.append({"type": "text", "text": before})
            if after:
                tail_runs.append({"type": "text", "text": after})
    return display_block_runs, tail_runs


def _split_note_refs_by_runs(
    refs: Any,
    display_block_runs: List[Dict[str, Any]],
    tail_runs: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]] | None, List[Dict[str, Any]] | None]:
    if not isinstance(refs, list):
        return None, None
    buckets: Dict[tuple[str, str, int | None], List[Dict[str, Any]]] = {}
    for ref in refs:
        if isinstance(ref, dict):
            buckets.setdefault(_note_ref_key(ref), []).append(ref)
    return _refs_for_runs(display_block_runs, buckets), _refs_for_runs(tail_runs, buckets)


def _refs_for_runs(
    runs: List[Dict[str, Any]],
    buckets: Dict[tuple[str, str, int | None], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for run in runs:
        if run.get("type") != "note_ref":
            continue
        matches = buckets.get(_note_ref_key(run)) or []
        if matches:
            out.append(matches.pop(0))
    return out
