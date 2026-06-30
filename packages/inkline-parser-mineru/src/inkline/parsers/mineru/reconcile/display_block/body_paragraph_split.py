"""Display block body-paragraph split. Splits display blocks that have absorbed
body prose lines, demoting the prose tail back to paragraph type."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, FOOTNOTE, PARAGRAPH
from ...schema.models import BBox
from ..block_access import block_bbox as _bbox
from ..block_access import block_page as _block_page
from ..block_merge import _merge_block_pair
from ..constants import FLOAT_LIKE_TYPES
from ..layout_helpers import _page_coord_widths, _scaled_body_metrics
from ..notes.keys import note_ref_key as _note_ref_key
from .source_spans import (
    apply_embedded_display_source as _apply_embedded_display_source,
)
from .source_spans import (
    apply_source_from_spans as _apply_source_from_spans,
)
from .source_spans import (
    embedded_display_spans as _embedded_display_spans,
)
from .source_spans import (
    is_display_lane_span as _is_display_lane_span,
)
from .source_spans import (
    line_has_body_flow_source_span as _line_has_body_flow_source_span,
)
from .source_spans import (
    line_has_body_lane_source_span as _line_has_body_lane_source_span,
)
from .source_spans import (
    span_bbox as _span_bbox,
)
from .source_spans import (
    span_has_body_flow_layout as _span_has_body_flow_layout,
)
from .source_spans import (
    surrounding_spans as _surrounding_spans,
)
from .source_spans import (
    text_for_spans as _text_for_spans,
)


@dataclass(frozen=True)
class _BodyTailSplit:
    display_text: str
    body_text: str
    split_idx: int
    original_source: Dict[str, Any]
    source_spans: List[Dict[str, Any]]
    display_runs: List[Dict[str, Any]]
    body_runs: List[Dict[str, Any]]
    display_refs: List[Dict[str, Any]] | None
    body_refs: List[Dict[str, Any]] | None
    nonempty_lines: List[str]


@dataclass(frozen=True)
class _EmbeddedShortLineSplit:
    before_text: str
    display_text: str
    after_text: str
    start_line: int
    end_line: int
    lines: List[str]
    original_attrs: Dict[str, Any]
    original_source: Dict[str, Any]
    source_spans: List[Dict[str, Any]]
    before_runs: List[Dict[str, Any]]
    display_runs: List[Dict[str, Any]]
    after_runs: List[Dict[str, Any]]
    before_refs: List[Dict[str, Any]] | None
    display_refs: List[Dict[str, Any]] | None
    after_refs: List[Dict[str, Any]] | None
    fallback_before_spans: List[Dict[str, Any]]
    fallback_display_spans: List[Dict[str, Any]]
    fallback_after_spans: List[Dict[str, Any]]


@dataclass(frozen=True)
class _ShortLineTextSplit:
    before_text: str
    display_text: str
    after_text: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class _InlineSplitPartitions:
    before_runs: List[Dict[str, Any]]
    display_runs: List[Dict[str, Any]]
    after_runs: List[Dict[str, Any]]
    before_refs: List[Dict[str, Any]] | None
    display_refs: List[Dict[str, Any]] | None
    after_refs: List[Dict[str, Any]] | None


@dataclass(frozen=True)
class _FallbackSpans:
    before: List[Dict[str, Any]]
    display: List[Dict[str, Any]]
    after: List[Dict[str, Any]]


def reconcile_display_block_body_paragraph_split(
    blocks: List[Dict[str, Any]], layout: LayoutStats
) -> None:
    """Demote body-paragraph tails from display blocks back to paragraphs.

    When a display-run merge absorbs body prose, the resulting display block
    may contain wide body-width lines that should be separate paragraphs.
    This pass scans each display block and splits the text at the first
    body-width prose line, keeping only the display-prefix as display_block.
    """
    page_widths = _page_coord_widths(blocks)
    page_body_lefts = _page_body_lefts(blocks, layout, page_widths)
    _split_leading_body_intro_from_display_blocks(blocks, layout, page_widths, page_body_lefts)
    _split_body_tails_from_display_blocks(blocks, layout, page_widths, page_body_lefts)
    _split_embedded_paragraph_boundaries_from_display_blocks(blocks, layout, page_widths)
    _split_embedded_short_line_groups_from_paragraphs(blocks, layout, page_widths, page_body_lefts)


def _split_body_tails_from_display_blocks(
    blocks: List[Dict[str, Any]],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float],
) -> None:
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        split = _body_tail_split_for_block(
            cur, blocks, i, layout, page_widths, page_body_lefts
        )
        if split is None:
            i += 1
            continue
        new_para = _apply_body_tail_split(cur, split)
        blocks.insert(i + 1, new_para)
        _merge_split_tail_with_following_paragraph(blocks, i + 1)
        i += 2


def _body_tail_split_for_block(
    block: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    block_index: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float],
) -> _BodyTailSplit | None:
    if block.get("type") != DISPLAY_BLOCK:
        return None
    text = str(block.get("text", "")).strip()
    if "\n" not in text:
        return None
    split_point = _find_body_split_point(
        block, text, layout, page_widths, page_body_lefts, blocks, block_index
    )
    if split_point is None:
        return None
    display_text = text[:split_point].strip()
    body_text = text[split_point:].strip()
    if not display_text or not body_text:
        return None
    body_lines = [ln.strip() for ln in body_text.split("\n") if ln.strip()]
    if not body_lines:
        return None
    split_idx = len(text[:split_point].split("\n")) - 1
    if not _body_tail_has_prose_evidence(
        block, blocks, block_index, text, body_lines, split_idx, layout, page_widths, page_body_lefts
    ):
        return None
    original_source = block.get("source") or {}
    source_spans = [
        span for span in original_source.get("spans") or [] if isinstance(span, dict)
    ]
    display_runs, body_runs = _split_inline_runs_at_offset(
        (block.get("attrs") or {}).get("inline_runs"), split_point
    )
    display_refs, body_refs = _split_note_refs_by_runs(
        (block.get("attrs") or {}).get("note_refs"),
        display_runs,
        body_runs,
    )
    return _BodyTailSplit(
        display_text=display_text,
        body_text=body_text,
        split_idx=split_idx,
        original_source=original_source,
        source_spans=source_spans,
        display_runs=display_runs,
        body_runs=body_runs,
        display_refs=display_refs,
        body_refs=body_refs,
        nonempty_lines=[line.strip() for line in text.split("\n") if line.strip()],
    )


def _body_tail_has_prose_evidence(
    block: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    block_index: int,
    text: str,
    body_lines: List[str],
    split_idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float],
) -> bool:
    if any(len(line) > 60 for line in body_lines):
        return True
    split_lines = text.split("\n")
    has_body_lane = _line_has_body_lane_source_span(
        block, split_lines, split_idx, layout, page_widths, page_body_lefts
    )
    has_body_flow = _line_has_body_flow_source_span(
        block, split_lines, split_idx, layout, page_widths, page_body_lefts
    )
    return has_body_lane or (
        has_body_flow and _has_following_cross_page_paragraph(blocks, block_index)
    )


def _apply_body_tail_split(block: Dict[str, Any], split: _BodyTailSplit) -> Dict[str, Any]:
    block["text"] = split.display_text
    attrs = block.setdefault("attrs", {})
    ev = attrs.setdefault("classification_evidence", [])
    if "split_body_paragraph_from_display_block" not in ev:
        ev.append("split_body_paragraph_from_display_block")
    _set_optional_inline_runs(attrs, split.display_runs)
    _set_optional_note_refs(attrs, split.display_refs)

    new_para = copy.deepcopy(block)
    new_para["block_id"] = f"{block.get('block_id')}_body"
    new_para["type"] = PARAGRAPH
    new_para["text"] = split.body_text
    new_para.pop("level", None)
    _prepare_split_body_tail_attrs(new_para, block, split)
    if (
        len(split.source_spans) == len(split.nonempty_lines)
        and 0 < split.split_idx < len(split.source_spans)
    ):
        _apply_source_from_spans(
            block,
            split.original_source,
            split.source_spans[: split.split_idx],
        )
        _apply_source_from_spans(
            new_para,
            split.original_source,
            split.source_spans[split.split_idx :],
        )
    return new_para


def _prepare_split_body_tail_attrs(
    paragraph: Dict[str, Any],
    original: Dict[str, Any],
    split: _BodyTailSplit,
) -> None:
    attrs = paragraph.setdefault("attrs", {})
    for key in [
        "role",
        "content_form",
        "content_form_confidence",
        "content_form_scores",
        "classification_evidence",
        "quote_text",
        "attribution",
        "layout_role",
        "line_count",
        "has_attribution_line",
        "line_layouts",
        "raw_types",
    ]:
        attrs.pop(key, None)
    attrs.pop("merged_from", None)
    attrs.pop("merge_evidence", None)
    attrs.pop("merge_origin", None)
    _set_optional_inline_runs(attrs, split.body_runs)
    _set_optional_note_refs(attrs, split.body_refs)
    attrs["split_from_display_block_id"] = original.get("block_id")


def _set_optional_inline_runs(attrs: Dict[str, Any], runs: List[Dict[str, Any]]) -> None:
    if runs:
        attrs["inline_runs"] = runs
    else:
        attrs.pop("inline_runs", None)


def _set_optional_note_refs(
    attrs: Dict[str, Any], refs: List[Dict[str, Any]] | None
) -> None:
    if refs is not None:
        attrs["note_refs"] = refs
    else:
        attrs.pop("note_refs", None)


def _split_embedded_paragraph_boundaries_from_display_blocks(
    blocks: List[Dict[str, Any]],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> None:
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") != DISPLAY_BLOCK:
            i += 1
            continue
        split = _geometry_embedded_paragraph_split(cur, layout, page_widths)
        if split is None:
            i += 1
            continue
        prefix_spans, paragraph_spans, display_spans, after_spans = split
        original_source = cur.get("source") or {}
        original_id = cur.get("block_id")
        merge_attrs = {
            k: v
            for k, v in (cur.get("attrs") or {}).items()
            if k in {"merge_reason", "merge_evidence"}
        }

        cur["text"] = _text_for_spans(prefix_spans)
        _apply_source_from_spans(cur, original_source, prefix_spans)
        inserts = _embedded_paragraph_boundary_inserts(
            cur,
            original_id,
            original_source,
            paragraph_spans,
            display_spans,
            after_spans,
        )
        cur.setdefault("attrs", {}).update(merge_attrs)
        blocks[i + 1 : i + 1] = inserts
        i += 1 + len(inserts)


def _embedded_paragraph_boundary_inserts(
    template: Dict[str, Any],
    original_id: str | None,
    original_source: Dict[str, Any],
    paragraph_spans: List[Dict[str, Any]],
    display_spans: List[Dict[str, Any]],
    after_spans: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    inserts = [
        _embedded_paragraph_block(
            template, f"{original_id}_paragraph", original_id, original_source, paragraph_spans
        ),
        _embedded_display_block(
            template, f"{original_id}_display", original_id, original_source, display_spans
        ),
    ]
    if after_spans:
        inserts.append(
            _embedded_paragraph_block(
                template, f"{original_id}_after", original_id, original_source, after_spans
            )
        )
    return inserts


def _embedded_paragraph_block(
    template: Dict[str, Any],
    block_id: str,
    original_id: str | None,
    original_source: Dict[str, Any],
    spans: List[Dict[str, Any]],
) -> Dict[str, Any]:
    block = copy.deepcopy(template)
    block["block_id"] = block_id
    block["type"] = PARAGRAPH
    block["text"] = _text_for_spans(spans)
    attrs = block.setdefault("attrs", {})
    _demote_display_attrs(attrs)
    attrs["split_from_display_block_id"] = original_id
    _apply_source_from_spans(block, original_source, spans)
    return block


def _embedded_display_block(
    template: Dict[str, Any],
    block_id: str,
    original_id: str | None,
    original_source: Dict[str, Any],
    spans: List[Dict[str, Any]],
) -> Dict[str, Any]:
    block = copy.deepcopy(template)
    block["block_id"] = block_id
    block["type"] = DISPLAY_BLOCK
    block["text"] = _text_for_spans(spans)
    attrs = block.setdefault("attrs", {})
    attrs["layout_role"] = "inline_display_block"
    attrs["layout_form"] = "short_line_group"
    attrs["line_count"] = len(spans)
    attrs["split_from_display_block_id"] = original_id
    _apply_source_from_spans(block, original_source, spans)
    return block


def _split_leading_body_intro_from_display_blocks(
    blocks: List[Dict[str, Any]],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float],
) -> None:
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") != DISPLAY_BLOCK:
            i += 1
            continue
        split = _leading_body_intro_split(cur, blocks, i, layout, page_widths, page_body_lefts)
        if split is None:
            i += 1
            continue
        intro_spans, display_spans = split
        intro = _apply_leading_body_intro_split(cur, intro_spans, display_spans)
        if intro is None:
            i += 1
            continue
        blocks.insert(i, intro)
        i += 2


def _apply_leading_body_intro_split(
    block: Dict[str, Any],
    intro_spans: List[Dict[str, Any]],
    display_spans: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    intro_text = _text_for_spans(intro_spans)
    display_text = _text_for_spans(display_spans)
    if not intro_text or not display_text:
        return None
    original_source = block.get("source") or {}
    original_attrs = block.get("attrs") or {}
    original_id = block.get("block_id")
    intro_runs, display_runs = _split_inline_runs_at_offset(
        original_attrs.get("inline_runs"), len(intro_text)
    )
    intro_refs, display_refs = _split_note_refs_by_runs(
        original_attrs.get("note_refs"), intro_runs, display_runs
    )
    intro = _leading_intro_block(
        block, original_id, intro_text, original_source, intro_spans, intro_runs, intro_refs
    )
    _apply_leading_display_tail(
        block, display_text, original_source, display_spans, display_runs, display_refs
    )
    return intro


def _leading_intro_block(
    template: Dict[str, Any],
    original_id: str | None,
    text: str,
    original_source: Dict[str, Any],
    spans: List[Dict[str, Any]],
    runs: List[Dict[str, Any]],
    refs: List[Dict[str, Any]] | None,
) -> Dict[str, Any]:
    block = copy.deepcopy(template)
    block["block_id"] = f"{original_id}_intro"
    block["type"] = PARAGRAPH
    block["text"] = text
    block.pop("level", None)
    attrs = block.setdefault("attrs", {})
    _demote_display_attrs(attrs)
    attrs["split_from_display_block_id"] = original_id
    _set_optional_inline_runs(attrs, runs)
    _set_optional_note_refs(attrs, refs)
    _apply_source_from_spans(block, original_source, spans)
    return block


def _apply_leading_display_tail(
    block: Dict[str, Any],
    text: str,
    original_source: Dict[str, Any],
    spans: List[Dict[str, Any]],
    runs: List[Dict[str, Any]],
    refs: List[Dict[str, Any]] | None,
) -> None:
    block["text"] = text
    attrs = block.setdefault("attrs", {})
    attrs["split_leading_body_intro"] = True
    _set_optional_inline_runs(attrs, runs)
    _set_optional_note_refs(attrs, refs)
    _apply_source_from_spans(block, original_source, spans)


def _leading_body_intro_split(
    block: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]] | None:
    if (block.get("attrs") or {}).get("merge_reason") != "same_page_display_block_continuation":
        return None
    spans = [
        span
        for span in (block.get("source") or {}).get("spans") or []
        if isinstance(span, dict) and span.get("text")
    ]
    if len(spans) < 2:
        return None
    first = spans[0]
    second = spans[1]
    first_bbox = _span_bbox(first)
    second_bbox = _span_bbox(second)
    page = first.get("page")
    if (
        first_bbox is None
        or second_bbox is None
        or page is None
        or second.get("page") != page
    ):
        return None
    page = int(page)
    if not _span_has_body_flow_layout(first, layout, page_widths, page_body_lefts):
        return None
    if not _is_display_lane_span(second, layout, page_widths):
        return None
    prev_bbox = _previous_body_flow_span_bbox(blocks, idx, page, layout, page_widths, page_body_lefts)
    if not prev_bbox:
        return None
    line_height = max(1.0, float(first_bbox[3]) - float(first_bbox[1]))
    tight_gap = max(18.0, line_height * 1.25)
    boundary_gap = max(24.0, line_height * 1.5)
    prev_gap = float(first_bbox[1]) - float(prev_bbox[3])
    next_gap = float(second_bbox[1]) - float(first_bbox[3])
    if not (0 <= prev_gap <= tight_gap and next_gap >= boundary_gap):
        return None
    return [first], spans[1:]


def _previous_body_flow_span_bbox(
    blocks: List[Dict[str, Any]],
    idx: int,
    page: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float],
) -> BBox | None:
    for candidate in reversed(blocks[:idx]):
        if candidate.get("type") == FOOTNOTE or candidate.get("type") in FLOAT_LIKE_TYPES:
            continue
        if candidate.get("type") != PARAGRAPH:
            return None
        bboxes = []
        source = candidate.get("source") or {}
        for span in source.get("spans") or []:
            if not isinstance(span, dict) or span.get("page") != page:
                continue
            bbox = _span_bbox(span)
            if bbox and _span_has_body_flow_layout(span, layout, page_widths, page_body_lefts):
                bboxes.append(bbox)
        if not bboxes:
            bbox = _bbox(candidate)
            if _block_page(candidate) == page and bbox:
                span = {"page": page, "bbox": bbox}
                if _span_has_body_flow_layout(span, layout, page_widths, page_body_lefts):
                    bboxes.append(bbox)
        if bboxes:
            return max(bboxes, key=lambda bbox: float(bbox[3]))
        return None
    return None


def _geometry_embedded_paragraph_split(
    block: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> (
    tuple[
        List[Dict[str, Any]],
        List[Dict[str, Any]],
        List[Dict[str, Any]],
        List[Dict[str, Any]],
    ]
    | None
):
    spans = [
        span
        for span in (block.get("source") or {}).get("spans") or []
        if isinstance(span, dict) and span.get("text")
    ]
    if len(spans) < 4:
        return None
    boxes = [_span_bbox(span) for span in spans]
    if any(bbox is None for bbox in boxes):
        return None
    bboxes = [bbox for bbox in boxes if bbox is not None]
    heights = [max(1.0, float(bbox[3]) - float(bbox[1])) for bbox in bboxes]
    line_height = sorted(heights)[len(heights) // 2] if heights else 18.0
    boundary_gap = max(24.0, line_height * 1.5)
    tight_gap = max(22.0, line_height * 1.25)

    for start in range(2, len(spans) - 1):
        paragraph_idx = start - 1
        if float(bboxes[start][1]) - float(bboxes[paragraph_idx][3]) < boundary_gap:
            continue
        if float(bboxes[paragraph_idx][1]) - float(bboxes[paragraph_idx - 1][3]) < boundary_gap:
            continue
        end = start + 1
        while end < len(spans) and _line_belongs_to_geometry_run(
            bboxes[start], bboxes[end], layout, page_widths, spans[end]
        ):
            gap = float(bboxes[end][1]) - float(bboxes[end - 1][3])
            if gap < -8.0 or gap > tight_gap:
                break
            end += 1
        if end - start < 2:
            continue
        return spans[:paragraph_idx], spans[paragraph_idx:start], spans[start:end], spans[end:]
    return None


def _demote_display_attrs(attrs: Dict[str, Any]) -> None:
    for key in [
        "layout_role",
        "layout_form",
        "line_count",
        "has_attribution_line",
        "line_layouts",
        "raw_types",
        "merged_from",
        "merge_reason",
        "merge_evidence",
        "interrupted_by",
    ]:
        attrs.pop(key, None)


def _split_embedded_short_line_groups_from_paragraphs(
    blocks: List[Dict[str, Any]],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
    page_body_lefts: Dict[int, float] | None = None,
) -> None:
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") != PARAGRAPH:
            i += 1
            continue
        attrs = cur.get("attrs") or {}
        if not attrs.get("split_from_display_block_id"):
            i += 1
            continue
        text = str(cur.get("text") or "").strip()
        split = _embedded_short_line_split_plan(
            cur, text, layout, page_widths, page_body_lefts
        )
        if split is None:
            i += 1
            continue
        inserts = _apply_embedded_short_line_split(
            cur, split, layout, page_widths, page_body_lefts
        )
        blocks[i + 1 : i + 1] = inserts
        i += 1 + len(inserts)


def _embedded_short_line_split_plan(
    block: Dict[str, Any],
    text: str,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
) -> _EmbeddedShortLineSplit | None:
    text_split = _embedded_short_line_text_split(block, text, layout, page_widths)
    if text_split is None:
        return None
    original_attrs = block.get("attrs") or {}
    original_source = block.get("source") or {}
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    inline = _embedded_inline_partitions(
        original_attrs, text_split.before_text, text_split.display_text
    )
    source_spans = [
        span for span in original_source.get("spans") or [] if isinstance(span, dict)
    ]
    fallback = _embedded_fallback_spans(
        source_spans,
        lines,
        layout,
        page_widths,
        page_body_lefts,
        text_split.start_line,
        text_split.end_line,
    )
    return _EmbeddedShortLineSplit(
        before_text=text_split.before_text,
        display_text=text_split.display_text,
        after_text=text_split.after_text,
        start_line=text_split.start_line,
        end_line=text_split.end_line,
        lines=lines,
        original_attrs=original_attrs,
        original_source=original_source,
        source_spans=source_spans,
        before_runs=inline.before_runs,
        display_runs=inline.display_runs,
        after_runs=inline.after_runs,
        before_refs=inline.before_refs,
        display_refs=inline.display_refs,
        after_refs=inline.after_refs,
        fallback_before_spans=fallback.before,
        fallback_display_spans=fallback.display,
        fallback_after_spans=fallback.after,
    )


def _embedded_short_line_text_split(
    block: Dict[str, Any],
    text: str,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
) -> _ShortLineTextSplit | None:
    split = _embedded_short_line_group_split_by_geometry(block, text, layout, page_widths)
    if split is None:
        split = _embedded_short_line_group_split(text)
    if split is None:
        return None
    before_text, display_text, after_text, start_line, end_line = split
    return _ShortLineTextSplit(before_text, display_text, after_text, start_line, end_line)


def _embedded_inline_partitions(
    attrs: Dict[str, Any], before_text: str, display_text: str
) -> _InlineSplitPartitions:
    before_runs, display_after_runs = _split_inline_runs_at_offset(
        attrs.get("inline_runs"), _display_start_offset(before_text)
    )
    display_runs, after_runs = _split_inline_runs_at_offset(display_after_runs, len(display_text))
    before_refs, display_after_refs = _split_note_refs_by_runs(
        attrs.get("note_refs"), before_runs, display_after_runs
    )
    display_refs, after_refs = _split_note_refs_by_runs(
        display_after_refs, display_runs, after_runs
    )
    return _InlineSplitPartitions(
        before_runs, display_runs, after_runs, before_refs, display_refs, after_refs
    )


def _display_start_offset(before_text: str) -> int:
    return len(before_text) + (1 if before_text else 0)


def _embedded_fallback_spans(
    source_spans: List[Dict[str, Any]],
    lines: List[str],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
    start_line: int,
    end_line: int,
) -> _FallbackSpans:
    if not source_spans or len(source_spans) == len(lines):
        return _FallbackSpans([], [], [])
    display_spans = _embedded_display_spans(
        source_spans,
        layout,
        page_widths,
        page_body_lefts,
        max(1, end_line - start_line),
    )
    before_spans, after_spans = _surrounding_spans(source_spans, display_spans)
    return _FallbackSpans(before_spans, display_spans, after_spans)


def _apply_embedded_short_line_split(
    block: Dict[str, Any],
    split: _EmbeddedShortLineSplit,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
) -> List[Dict[str, Any]]:
    _apply_embedded_before_paragraph(block, split)
    inserts = [
        _embedded_short_line_display_block(block, split, layout, page_widths, page_body_lefts)
    ]
    if split.after_text:
        inserts.append(_embedded_after_block(block, split))
    return inserts


def _apply_embedded_before_paragraph(
    block: Dict[str, Any], split: _EmbeddedShortLineSplit
) -> None:
    block["text"] = split.before_text
    attrs = block.setdefault("attrs", {})
    attrs.pop("layout_form", None)
    attrs["embedded_display_split"] = True
    _set_partitioned_inline_attrs(attrs, split.before_runs, split.before_refs)
    if len(split.source_spans) == len(split.lines):
        _apply_source_from_spans(
            block, split.original_source, split.source_spans[: split.start_line]
        )
    elif split.fallback_before_spans:
        _apply_source_from_spans(block, split.original_source, split.fallback_before_spans)


def _embedded_short_line_display_block(
    block: Dict[str, Any],
    split: _EmbeddedShortLineSplit,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
) -> Dict[str, Any]:
    display_block = copy.deepcopy(block)
    display_block["block_id"] = f"{block.get('block_id')}_display"
    display_block["type"] = DISPLAY_BLOCK
    display_block["text"] = split.display_text
    display_attrs = display_block.setdefault("attrs", {})
    display_attrs["layout_role"] = "inline_display_block"
    display_attrs["layout_form"] = "short_line_group"
    display_attrs["line_count"] = len(
        [line for line in split.display_text.split("\n") if line.strip()]
    )
    display_attrs["split_from_paragraph_id"] = block.get("block_id")
    _set_partitioned_inline_attrs(display_attrs, split.display_runs, split.display_refs)
    _apply_embedded_display_spans(
        block, display_block, split, layout, page_widths, page_body_lefts
    )
    return display_block


def _apply_embedded_display_spans(
    original_block: Dict[str, Any],
    display_block: Dict[str, Any],
    split: _EmbeddedShortLineSplit,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
) -> None:
    if len(split.source_spans) == len(split.lines):
        _apply_source_from_spans(
            display_block,
            split.original_source,
            split.source_spans[split.start_line : split.end_line],
        )
    elif split.fallback_display_spans:
        _apply_source_from_spans(
            display_block, split.original_source, split.fallback_display_spans
        )
    else:
        _apply_embedded_display_source(
            original_block,
            display_block,
            layout,
            page_widths,
            page_body_lefts,
            split.start_line,
            split.end_line,
        )


def _embedded_after_block(
    block: Dict[str, Any], split: _EmbeddedShortLineSplit
) -> Dict[str, Any]:
    after_block = copy.deepcopy(block)
    after_block["block_id"] = f"{block.get('block_id')}_after"
    after_block["type"] = PARAGRAPH
    after_block["text"] = split.after_text
    after_attrs = after_block.setdefault("attrs", {})
    after_attrs.pop("layout_role", None)
    after_attrs.pop("layout_form", None)
    after_attrs.pop("line_count", None)
    _set_partitioned_inline_attrs(after_attrs, split.after_runs, split.after_refs)
    after_attrs["split_from_paragraph_id"] = block.get("block_id")
    if len(split.source_spans) == len(split.lines):
        _apply_source_from_spans(
            after_block, split.original_source, split.source_spans[split.end_line :]
        )
    elif split.fallback_after_spans:
        _apply_source_from_spans(after_block, split.original_source, split.fallback_after_spans)
    return after_block


def _embedded_short_line_group_split(
    text: str,
) -> tuple[str, str, str, int, int] | None:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 3:
        return None
    for start in range(1, len(lines) - 1):
        if start > 1 and _looks_like_display_short_line(lines[start - 1]):
            continue
        end = start
        while end < len(lines) and _looks_like_display_short_line(lines[end]):
            end += 1
        if end - start < 2:
            continue
        before = "\n".join(lines[:start]).strip()
        display = "\n".join(lines[start:end]).strip()
        after = "\n".join(lines[end:]).strip()
        if before and display:
            return before, display, after, start, end
    return None


def _embedded_short_line_group_split_by_geometry(
    block: Dict[str, Any],
    text: str,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> tuple[str, str, str, int, int] | None:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    spans = [
        span for span in (block.get("source") or {}).get("spans") or [] if isinstance(span, dict)
    ]
    if len(lines) < 3 or len(spans) != len(lines):
        return None
    bboxes = [_span_bbox(span) for span in spans]
    if any(bbox is None for bbox in bboxes):
        return None
    boxes = [bbox for bbox in bboxes if bbox is not None]
    heights = [max(1.0, float(bbox[3]) - float(bbox[1])) for bbox in boxes]
    line_height = sorted(heights)[len(heights) // 2] if heights else 18.0
    boundary_gap = max(24.0, line_height * 1.5)
    tight_gap = max(22.0, line_height * 1.25)

    for start in range(1, len(lines) - 1):
        before_gap = float(boxes[start][1]) - float(boxes[start - 1][3])
        if before_gap < boundary_gap:
            continue
        end = start + 1
        while end < len(lines) and _line_belongs_to_geometry_run(
            boxes[start], boxes[end], layout, page_widths, spans[end]
        ):
            gap = float(boxes[end][1]) - float(boxes[end - 1][3])
            if gap < -8.0 or gap > tight_gap:
                break
            end += 1
        if end - start < 2:
            continue
        if end < len(lines):
            after_gap = float(boxes[end][1]) - float(boxes[end - 1][3])
            if after_gap < boundary_gap:
                continue
        before = "\n".join(lines[:start]).strip()
        display = "\n".join(lines[start:end]).strip()
        after = "\n".join(lines[end:]).strip()
        if before and display:
            return before, display, after, start, end
    return None


def _line_belongs_to_geometry_run(
    first_bbox: BBox,
    candidate_bbox: BBox,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    candidate_span: Dict[str, Any],
) -> bool:
    page = candidate_span.get("page")
    coord_width = page_widths.get(int(page)) if page is not None and page_widths else None
    _body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    first_x0, first_x1, first_width = _horizontal_bbox_metrics(first_bbox)
    cand_x0, cand_x1, cand_width = _horizontal_bbox_metrics(candidate_bbox)
    left_match = _near_bbox_edge(cand_x0, first_x0, max(28.0, body_width * 0.04))
    right_match = _near_bbox_edge(cand_x1, first_x1, max(30.0, body_width * 0.045))
    comparable_width = cand_width <= _geometry_run_max_width(first_width, body_width)
    return comparable_width and (left_match or right_match)


def _horizontal_bbox_metrics(bbox: BBox) -> tuple[float, float, float]:
    x0 = float(bbox[0])
    x1 = float(bbox[2])
    return x0, x1, max(1.0, x1 - x0)


def _near_bbox_edge(candidate: float, expected: float, tolerance: float) -> bool:
    return abs(candidate - expected) <= tolerance


def _geometry_run_max_width(first_width: float, body_width: float) -> float:
    return max(first_width * 1.45, body_width * 0.36)


def _looks_like_display_short_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and len(stripped) <= 32


def _set_partitioned_inline_attrs(
    attrs: Dict[str, Any],
    runs: List[Dict[str, Any]],
    refs: List[Dict[str, Any]] | None,
) -> None:
    if runs:
        attrs["inline_runs"] = runs
    else:
        attrs.pop("inline_runs", None)
    if refs is not None:
        if refs:
            attrs["note_refs"] = refs
        else:
            attrs.pop("note_refs", None)


def _merge_split_tail_with_following_paragraph(blocks: List[Dict[str, Any]], idx: int) -> None:
    if idx < 0 or idx >= len(blocks):
        return
    left = blocks[idx]
    if left.get("type") != PARAGRAPH:
        return
    if not (left.get("attrs") or {}).get("split_from_display_block_id"):
        return
    text = str(left.get("text") or "").rstrip()
    if not text or text[-1] in "。？！!?；;：:.”’\"'）】》」』":
        return
    left_page = _block_page(left)
    if left_page is None:
        return

    j = idx + 1
    interruptions: List[Dict[str, Any]] = []
    while j < len(blocks):
        candidate = blocks[j]
        if candidate.get("type") == FOOTNOTE or candidate.get("type") in FLOAT_LIKE_TYPES:
            interruptions.append(candidate)
            j += 1
            continue
        break
    if j >= len(blocks):
        return
    right = blocks[j]
    right_page = _block_page(right)
    if right.get("type") != PARAGRAPH or right_page is None:
        return
    if right_page <= left_page or right_page > left_page + 1:
        return
    _merge_block_pair(
        left,
        right,
        "split_display_body_tail_joined_to_following_paragraph",
        {"after_float_or_footnote_interruption": bool(interruptions)},
        interruptions,
    )
    del blocks[j]


def _has_following_cross_page_paragraph(blocks: List[Dict[str, Any]], idx: int) -> bool:
    if idx < 0 or idx >= len(blocks):
        return False
    left_page = _block_page(blocks[idx])
    if left_page is None:
        return False
    j = idx + 1
    while j < len(blocks):
        candidate = blocks[j]
        if candidate.get("type") == FOOTNOTE or candidate.get("type") in FLOAT_LIKE_TYPES:
            j += 1
            continue
        break
    if j >= len(blocks):
        return False
    right = blocks[j]
    right_page = _block_page(right)
    return (
        right.get("type") == PARAGRAPH
        and right_page is not None
        and left_page < right_page <= left_page + 1
    )


def _find_body_split_point(
    block: Dict[str, Any],
    text: str,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
    page_body_lefts: Dict[int, float] | None = None,
    blocks: List[Dict[str, Any]] | None = None,
    block_index: int | None = None,
) -> int | None:
    """Find the character offset where body prose begins within a display block.

    Scans lines from the start.  Returns the offset of the first line whose
    length and block-level bbox confirm body-width prose, but only if it is
    preceded by at least one shorter display-like line.

    Only splits when the block-level bbox confirms body-width positioning
    (at body indent with >= 88% body width).  Indented/narrow display blocks
    are never split — text-length alone is not layout evidence.
    """
    lines = text.split("\n")
    first_body_idx = _first_body_split_line_index(
        block, lines, layout, page_widths, page_body_lefts, blocks, block_index
    )
    if first_body_idx is None:
        return None
    if not _has_body_lane_tail_evidence(block, layout, page_widths, page_body_lefts):
        return None
    return _line_start_offset(lines, first_body_idx)


def _first_body_split_line_index(
    block: Dict[str, Any],
    lines: List[str],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
    blocks: List[Dict[str, Any]] | None,
    block_index: int | None,
) -> int | None:
    bb = _bbox(block)
    page = _block_page(block)
    coord_width = page_widths.get(page) if page is not None and page_widths else None
    body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    page_body_left = (
        page_body_lefts.get(page, body_left) if page is not None and page_body_lefts else body_left
    )
    block_at_body = bb and (
        float(bb[0]) <= page_body_left + max(24.0, body_width * 0.035)
        and (float(bb[2]) - float(bb[0])) >= body_width * 0.88
    )
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        line_offset = _line_start_offset(lines, idx)
        note_boundary_before_line = _has_note_ref_boundary_before_offset(block, line_offset)
        if len(stripped) > 80 and idx > 0 and block_at_body:
            return idx
        has_line_body_flow = _line_has_body_flow_source_span(
            block, lines, idx, layout, page_widths, page_body_lefts
        )
        if (
            idx > 0
            and (block.get("attrs") or {}).get("merge_reason")
            == "same_page_display_block_continuation"
            and has_line_body_flow
            and blocks is not None
            and block_index is not None
            and _has_following_cross_page_paragraph(blocks, block_index)
        ):
            return idx
        has_line_body_lane = _line_has_body_lane_source_span(
            block, lines, idx, layout, page_widths, page_body_lefts
        )
        if idx > 0 and note_boundary_before_line and has_line_body_lane:
            return idx
    return None


def _page_body_lefts(
    blocks: List[Dict[str, Any]],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> Dict[int, float]:
    candidates: Dict[int, List[float]] = {}
    for block in blocks:
        if block.get("type") != PARAGRAPH:
            continue
        bb = _bbox(block)
        page = _block_page(block)
        if not bb or page is None:
            continue
        coord_width = page_widths.get(page) if page_widths else None
        _body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
        width = max(0.0, float(bb[2]) - float(bb[0]))
        if width >= body_width * 0.55:
            candidates.setdefault(page, []).append(float(bb[0]))
    return {page: min(values) for page, values in candidates.items() if values}


def _has_body_lane_tail_evidence(
    block: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
    page_body_lefts: Dict[int, float] | None = None,
) -> bool:
    spans = (block.get("source") or {}).get("spans") or []
    if not spans:
        return True
    for span in spans:
        if not isinstance(span, dict):
            continue
        bbox = span.get("bbox")
        page = span.get("page")
        if not isinstance(bbox, list) or len(bbox) < 4 or page is None:
            continue
        page = int(page)
        coord_width = page_widths.get(page) if page_widths else None
        fallback_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
        body_left = page_body_lefts.get(page, fallback_left) if page_body_lefts else fallback_left
        x0 = float(bbox[0])
        width = max(0.0, float(bbox[2]) - x0)
        if x0 <= body_left + max(24.0, body_width * 0.035) and width >= body_width * 0.70:
            return True
        if _span_has_body_flow_layout(span, layout, page_widths, page_body_lefts):
            return True
    return False


def _line_start_offset(lines: List[str], idx: int) -> int:
    return sum(len(line) + 1 for line in lines[:idx])


def _has_note_ref_boundary_before_offset(block: Dict[str, Any], offset: int) -> bool:
    runs = (block.get("attrs") or {}).get("inline_runs")
    if not isinstance(runs, list):
        return False
    text_offset = 0
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("type") == "text":
            text_offset += len(str(run.get("text", "")))
            continue
        if run.get("type") == "note_ref" and 0 <= offset - text_offset <= 2:
            return True
    return False


def _split_inline_runs_at_offset(
    runs: Any, split_offset: int
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split inline runs at a character offset in the block text."""
    if not isinstance(runs, list):
        return [], []
    text_char_offset = 0
    split_run_index = -1
    split_char_index = 0
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or run.get("type") != "text":
            continue
        text = str(run.get("text", ""))
        next_offset = text_char_offset + len(text)
        if text_char_offset <= split_offset <= next_offset:
            split_run_index = index
            split_char_index = split_offset - text_char_offset
            break
        text_char_offset = next_offset

    if split_run_index < 0:
        return [], []

    display_runs: List[Dict[str, Any]] = []
    body_runs: List[Dict[str, Any]] = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        copied = dict(run)
        if index < split_run_index:
            display_runs.append(copied)
        elif index > split_run_index:
            body_runs.append(copied)
        else:
            text = str(copied.get("text", ""))
            before = text[:split_char_index].rstrip()
            after = text[split_char_index:].lstrip()
            if before:
                display_runs.append({"type": "text", "text": before})
            if after:
                body_runs.append({"type": "text", "text": after})
    return display_runs, body_runs


def _split_note_refs_by_runs(
    refs: Any,
    display_block_runs: List[Dict[str, Any]],
    body_runs: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]] | None, List[Dict[str, Any]] | None]:
    """Partition note refs to match the side they belong to.

    Modelled on overflow_tail_split._split_note_refs_by_runs.
    """
    if not isinstance(refs, list):
        return None, None
    buckets: Dict[tuple[str, str, int | None], List[Dict[str, Any]]] = {}
    for ref in refs:
        if isinstance(ref, dict):
            buckets.setdefault(_note_ref_key(ref), []).append(ref)
    return _refs_for_runs(display_block_runs, buckets), _refs_for_runs(body_runs, buckets)


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
