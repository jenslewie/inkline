"""Split embedded short-line display groups out of paragraph tails."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, PARAGRAPH
from ...schema.models import BBox
from ..layout_helpers import _scaled_body_metrics
from .inline_split import set_partitioned_inline_attrs as _set_partitioned_inline_attrs
from .inline_split import split_inline_runs_at_offset as _split_inline_runs_at_offset
from .inline_split import split_note_refs_by_runs as _split_note_refs_by_runs
from .source_spans import apply_embedded_display_source as _apply_embedded_display_source
from .source_spans import apply_source_from_spans as _apply_source_from_spans
from .source_spans import embedded_display_spans as _embedded_display_spans
from .source_spans import span_bbox as _span_bbox
from .source_spans import surrounding_spans as _surrounding_spans


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


def split_embedded_short_line_groups_from_paragraphs(
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
        split = _embedded_short_line_split_plan(cur, text, layout, page_widths, page_body_lefts)
        if split is None:
            i += 1
            continue
        inserts = _apply_embedded_short_line_split(cur, split, layout, page_widths, page_body_lefts)
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
    source_spans = [span for span in original_source.get("spans") or [] if isinstance(span, dict)]
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


def _apply_embedded_before_paragraph(block: Dict[str, Any], split: _EmbeddedShortLineSplit) -> None:
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
    _apply_embedded_display_spans(block, display_block, split, layout, page_widths, page_body_lefts)
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
        _apply_source_from_spans(display_block, split.original_source, split.fallback_display_spans)
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


def _embedded_after_block(block: Dict[str, Any], split: _EmbeddedShortLineSplit) -> Dict[str, Any]:
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
