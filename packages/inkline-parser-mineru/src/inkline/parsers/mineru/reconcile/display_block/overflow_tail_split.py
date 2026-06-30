"""Page-bottom display block overflow tail split. Splits a page-bottom display block when its final line is prose narrative rather than displayed text, converting the tail back to a paragraph and merging it with the next page's prose."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, PARAGRAPH
from ...schema.models import BBox
from ..block_access import block_page as _block_page
from ..block_access import block_pages as _block_pages
from ..block_merge import _merge_block_pair, _refresh_display_block_attrs
from ..block_nav import _prev_text_non_float
from ..layout_helpers import (
    _is_near_page_bottom,
    _is_near_page_top,
    _page_coord_heights,
    _page_coord_widths,
    _scaled_body_metrics,
)
from ..notes.keys import note_ref_key as _note_ref_key


@dataclass(frozen=True)
class _OverflowTailText:
    display_text: str
    tail_text: str


@dataclass(frozen=True)
class _OverflowTailInline:
    display_runs: List[Dict[str, Any]]
    tail_runs: List[Dict[str, Any]]
    display_refs: List[Dict[str, Any]] | None
    tail_refs: List[Dict[str, Any]] | None


def reconcile_page_bottom_overflow_tail_from_display_block(
    blocks: List[Dict[str, Any]], layout: LayoutStats
) -> None:
    page_heights = _page_coord_heights(blocks)
    page_widths = _page_coord_widths(blocks)
    i = 0
    while i + 1 < len(blocks):
        b = blocks[i]
        nxt = blocks[i + 1]
        if not _is_page_bottom_overflow_pair(b, nxt, page_heights):
            i += 1
            continue
        split = _split_overflow_tail_text(str(b.get("text", "")))
        if split is None:
            i += 1
            continue
        if not _has_overflow_tail_geometry(b, nxt, layout, page_widths):
            i += 1
            continue
        inline = _overflow_tail_inline_parts(b.get("attrs") or {})
        _apply_overflow_display_head(b, split, inline, blocks, i)
        new_para = _overflow_tail_paragraph(b, nxt, split, inline)
        _merge_block_pair(
            new_para,
            nxt,
            "split_display_block_tail_joined_to_page_top_paragraph",
            {"narrative_tail": True},
            [],
        )
        del blocks[i + 1]
        blocks.insert(i + 1, new_para)
        i += 2


def _is_page_bottom_overflow_pair(
    block: Dict[str, Any], next_block: Dict[str, Any], page_heights: Dict[int, float]
) -> bool:
    if block.get("type") != DISPLAY_BLOCK or next_block.get("type") != PARAGRAPH:
        return False
    block_page = max(_block_pages(block) or [_block_page(block) or -1])
    next_page = _block_page(next_block)
    return (
        next_page is not None
        and next_page == block_page + 1
        and _is_near_page_bottom(block, page_heights)
        and _is_near_page_top(next_block, page_heights)
    )


def _split_overflow_tail_text(text: str) -> _OverflowTailText | None:
    if "\n" not in text:
        return None
    display_text, tail_text = text.rsplit("\n", 1)
    display_text = display_text.rstrip()
    tail_text = tail_text.lstrip()
    if not display_text or not tail_text:
        return None
    return _OverflowTailText(display_text, tail_text)


def _overflow_tail_inline_parts(attrs: Dict[str, Any]) -> _OverflowTailInline:
    display_runs, tail_runs = _split_inline_runs_at_last_newline(attrs.get("inline_runs"))
    display_refs, tail_refs = _split_note_refs_by_runs(
        attrs.get("note_refs"), display_runs, tail_runs
    )
    return _OverflowTailInline(display_runs, tail_runs, display_refs, tail_refs)


def _apply_overflow_display_head(
    block: Dict[str, Any],
    split: _OverflowTailText,
    inline: _OverflowTailInline,
    blocks: List[Dict[str, Any]],
    index: int,
) -> None:
    block["text"] = split.display_text
    _refresh_display_block_attrs(block, prev_text=_prev_text_non_float(blocks, index))
    attrs = block.setdefault("attrs", {})
    if inline.display_runs:
        attrs["inline_runs"] = inline.display_runs
    if inline.display_refs is not None:
        attrs["note_refs"] = inline.display_refs
    evidence = attrs.setdefault("classification_evidence", [])
    if "split_page_bottom_overflow_tail_from_display_block" not in evidence:
        evidence.append("split_page_bottom_overflow_tail_from_display_block")


def _overflow_tail_paragraph(
    block: Dict[str, Any],
    next_block: Dict[str, Any],
    split: _OverflowTailText,
    inline: _OverflowTailInline,
) -> Dict[str, Any]:
    new_para = copy.deepcopy(block)
    new_para["block_id"] = next_block.get("block_id", f"{block.get('block_id')}_tail")
    new_para["type"] = PARAGRAPH
    new_para["text"] = split.tail_text
    new_para.pop("level", None)
    attrs = new_para.setdefault("attrs", {})
    _remove_display_attrs(attrs)
    attrs["split_from_display_block_id"] = block.get("block_id")
    if inline.tail_runs:
        attrs["inline_runs"] = inline.tail_runs
    if inline.tail_refs is not None:
        attrs["note_refs"] = inline.tail_refs
    return new_para


def _remove_display_attrs(attrs: Dict[str, Any]) -> None:
    for key in [
        "role",
        "content_form",
        "content_form_confidence",
        "content_form_scores",
        "classification_evidence",
        "quote_text",
        "attribution",
    ]:
        attrs.pop(key, None)


def _has_overflow_tail_geometry(
    block: Dict[str, Any],
    next_block: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float],
) -> bool:
    lines = [line.strip() for line in str(block.get("text") or "").split("\n") if line.strip()]
    spans = [
        span for span in (block.get("source") or {}).get("spans") or [] if isinstance(span, dict)
    ]
    if len(lines) < 2 or len(spans) != len(lines):
        return False
    tail_span = spans[-1]
    kept_spans = spans[:-1]
    return (
        _span_starts_in_body_lane(tail_span, layout, page_widths)
        and _has_set_off_display_span(kept_spans, layout, page_widths)
        and _block_is_body_lane(next_block, layout, page_widths)
    )


def _span_starts_in_body_lane(
    span: Dict[str, Any], layout: LayoutStats, page_widths: Dict[int, float]
) -> bool:
    bbox = _span_bbox(span)
    page = span.get("page")
    if not bbox or page is None:
        return False
    body_left, _body_right, body_width = _scaled_body_metrics(layout, page_widths.get(int(page)))
    return float(bbox[0]) <= body_left + max(30.0, body_width * 0.04)


def _has_set_off_display_span(
    spans: List[Dict[str, Any]], layout: LayoutStats, page_widths: Dict[int, float]
) -> bool:
    for span in spans:
        bbox = _span_bbox(span)
        page = span.get("page")
        if not bbox or page is None:
            continue
        body_left, _body_right, body_width = _scaled_body_metrics(
            layout, page_widths.get(int(page))
        )
        x0 = float(bbox[0])
        width = max(0.0, float(bbox[2]) - x0)
        if x0 >= body_left + max(34.0, body_width * 0.045) or width <= body_width * 0.70:
            return True
    return False


def _block_is_body_lane(
    block: Dict[str, Any], layout: LayoutStats, page_widths: Dict[int, float]
) -> bool:
    source = block.get("source") or {}
    bbox = source.get("bbox")
    page = _block_page(block)
    if not isinstance(bbox, list) or len(bbox) < 4 or page is None:
        return False
    body_left, _body_right, body_width = _scaled_body_metrics(layout, page_widths.get(page))
    x0 = float(bbox[0])
    width = max(0.0, float(bbox[2]) - x0)
    return x0 <= body_left + max(48.0, body_width * 0.06) and width >= body_width * 0.70


def _span_bbox(span: Dict[str, Any]) -> BBox | None:
    bbox = span.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        return bbox
    return None


def _split_inline_runs_at_last_newline(
    runs: Any,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
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
            after = text[split_char_index + 1 :].lstrip()
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
