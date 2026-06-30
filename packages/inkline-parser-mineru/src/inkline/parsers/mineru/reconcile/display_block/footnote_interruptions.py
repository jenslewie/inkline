"""Display blocks across footnote interruptions. Merges display block continuations that are split by page-bottom footnotes. Detects when a display block at page bottom and another at next page top share the same visual lane."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...normalize.builders import union_bbox
from ...schema.block_types import DISPLAY_BLOCK, FOOTNOTE, PARAGRAPH
from ...schema.models import BBox
from ..block_access import block_bbox as _bbox
from ..block_access import block_page as _block_page
from ..block_access import block_pages as _block_pages
from ..block_merge import _merge_block_pair, _refresh_display_block_attrs
from ..block_nav import _prev_text_non_float
from ..constants import _DEFAULT_PAGE_HEIGHT
from ..layout_helpers import (
    _display_block_layout,
    _is_near_page_bottom,
    _is_near_page_top,
    _page_coord_heights,
    _page_coord_widths,
    _scaled_body_metrics,
)
from .helpers import (
    display_lanes_compatible,
)
from .inline_split import set_partitioned_inline_attrs as _set_partitioned_inline_attrs
from .inline_split import split_inline_runs_at_offset as _split_inline_runs_at_offset
from .inline_split import split_note_refs_by_runs as _split_note_refs_by_runs


@dataclass(frozen=True)
class _LeadingContinuationSources:
    first_span: Dict[str, Any]
    rest_spans: List[Dict[str, Any]]
    first_bbox: BBox
    rest_bbox: BBox


@dataclass(frozen=True)
class _LeadingContinuationInline:
    first_runs: List[Dict[str, Any]]
    rest_runs: List[Dict[str, Any]]
    first_refs: List[Dict[str, Any]] | None
    rest_refs: List[Dict[str, Any]] | None


def reconcile_display_block_across_footnote_interruptions(
    blocks: List[Dict[str, Any]], layout: LayoutStats
) -> None:
    i = 0
    page_widths = _page_coord_widths(blocks)
    page_heights = _page_coord_heights(blocks)
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") != DISPLAY_BLOCK or not _is_interrupted_display_candidate(
            cur, page_heights
        ):
            i += 1
            continue
        cp = max(_block_pages(cur) or [_block_page(cur) or -1])
        j, skipped = _following_footnote_interruptions(blocks, i + 1)
        if not skipped:
            i += 1
            continue
        while j < len(blocks):
            nxt = blocks[j]
            np = _block_page(nxt)
            if np is None or np > cp + 1:
                break
            if np == cp + 1 and not _is_near_page_top(nxt, page_heights):
                break
            if (cur.get("attrs") or {}).get("has_attribution_line"):
                break
            if not _is_continuation_candidate(nxt, layout, page_widths.get(np)):
                break
            _split_next_page_leading_continuation_line(blocks, j)
            nxt = blocks[j]
            coord_width = _continuation_coord_width(cur, nxt, page_widths)
            lane_compatible = display_lanes_compatible(cur, nxt, layout, coord_width)
            wide_cross_page_continuation = _cross_page_wide_display_lanes_compatible(
                cur, nxt, layout, coord_width
            )
            if not (lane_compatible or wide_cross_page_continuation):
                break
            if nxt.get("type") == PARAGRAPH and _is_body_width_paragraph(
                nxt, layout, page_widths.get(np)
            ):
                break
            left_id = cur.get("block_id")
            right_id = nxt.get("block_id")
            _merge_block_pair(
                cur,
                nxt,
                "display_block_continuation_across_footnotes",
                {"footnote_interrupted_display_block": True},
                skipped,
                joiner=None if wide_cross_page_continuation else "newline",
            )
            _replace_referenced_by_block_id(blocks, right_id, left_id)
            _refresh_display_block_attrs(cur, prev_text=_prev_text_non_float(blocks, i))
            del blocks[j]
            cp = max(_block_pages(cur) or [cp])
            break
        i += 1


def _is_interrupted_display_candidate(
    block: Dict[str, Any], page_heights: Dict[int, float]
) -> bool:
    if len(_block_pages(block)) > 1:
        return True
    bb = _bbox(block)
    page = _block_page(block)
    lower_page_display = bool(
        bb
        and page is not None
        and float(bb[3]) >= page_heights.get(page, _DEFAULT_PAGE_HEIGHT) * 0.65
    )
    return lower_page_display or _is_near_page_bottom(block, page_heights)


def _following_footnote_interruptions(
    blocks: List[Dict[str, Any]], start: int
) -> tuple[int, List[Dict[str, Any]]]:
    skipped: List[Dict[str, Any]] = []
    idx = start
    while idx < len(blocks) and blocks[idx].get("type") == FOOTNOTE:
        skipped.append(_interruption_summary(blocks[idx]))
        idx += 1
    return idx, skipped


def _interruption_summary(block: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "page": _block_page(block),
        "bbox": _bbox(block),
        "block_id": block.get("block_id"),
        "type": block.get("type"),
    }


def _is_continuation_candidate(
    block: Dict[str, Any], layout: LayoutStats, coord_width: float | None
) -> bool:
    return block.get("type") == DISPLAY_BLOCK or (
        block.get("type") == PARAGRAPH and _display_block_layout(block, layout, coord_width)
    )


def _continuation_coord_width(
    left: Dict[str, Any], right: Dict[str, Any], page_widths: Dict[int, float]
) -> float | None:
    widths = [
        width
        for width in (
            page_widths.get(_block_page(left) or -1),
            page_widths.get(_block_page(right) or -1),
        )
        if width is not None
    ]
    return max(widths) if widths else None


def _is_body_width_paragraph(
    block: Dict[str, Any], layout: LayoutStats, coord_width: float | None
) -> bool:
    bb = _bbox(block)
    if not bb:
        return False
    body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    body_indent = float(bb[0]) <= body_left + max(48.0, body_width * 0.055)
    body_width_match = (float(bb[2]) - float(bb[0])) >= body_width * 0.88
    return body_indent and body_width_match


def _cross_page_wide_display_lanes_compatible(
    left: Dict[str, Any],
    right: Dict[str, Any],
    layout: LayoutStats,
    coord_width: float | None = None,
) -> bool:
    lbb = _bbox(left)
    rbb = _bbox(right)
    if not lbb or not rbb:
        return False
    if left.get("type") != DISPLAY_BLOCK or right.get("type") != DISPLAY_BLOCK:
        return False
    body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    left_x0, left_x1, left_width = _horizontal_bbox_metrics(lbb)
    right_x0, right_x1, right_width = _horizontal_bbox_metrics(rbb)
    left_set_off = (
        left_x0 >= body_left + max(34.0, body_width * 0.045)
        and body_width * 0.45 <= left_width <= body_width * 1.05
    )
    right_set_off = right_x0 >= body_left and body_width * 0.45 <= right_width <= body_width * 1.05
    right_edges_match = abs(left_x1 - right_x1) <= max(38.0, body_width * 0.055)
    left_edges_near = abs(left_x0 - right_x0) <= max(48.0, body_width * 0.07)
    return left_set_off and right_set_off and right_edges_match and left_edges_near


def _horizontal_bbox_metrics(bbox: BBox) -> tuple[float, float, float]:
    x0 = float(bbox[0])
    x1 = float(bbox[2])
    return x0, x1, max(0.0, x1 - x0)


def _split_next_page_leading_continuation_line(blocks: List[Dict[str, Any]], idx: int) -> None:
    block = blocks[idx]
    text = str(block.get("text") or "").strip()
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return
    source = block.get("source") or {}
    sources = _leading_continuation_sources(source)
    if sources is None:
        return
    inline = _leading_continuation_inline(block.get("attrs") or {}, len(lines[0]))

    block["text"] = lines[0]
    block["source"] = _source_for_spans(source, [sources.first_span], sources.first_bbox)
    _set_partitioned_inline_attrs(
        block.setdefault("attrs", {}), inline.first_runs, inline.first_refs
    )

    rest = copy.deepcopy(block)
    rest["block_id"] = f"{block.get('block_id')}_tail"
    rest["type"] = PARAGRAPH
    rest["text"] = "\n".join(lines[1:])
    rest["source"] = _source_for_spans(source, sources.rest_spans, sources.rest_bbox)
    rest_attrs = rest.setdefault("attrs", {})
    rest_attrs["split_from_display_block_id"] = block.get("block_id")
    _set_partitioned_inline_attrs(rest_attrs, inline.rest_runs, inline.rest_refs)
    rest_attrs.pop("merged_from", None)
    rest_attrs.pop("merge_reason", None)
    rest_attrs.pop("merge_evidence", None)
    rest_attrs.pop("interrupted_by", None)
    blocks.insert(idx + 1, rest)


def _leading_continuation_sources(source: Dict[str, Any]) -> _LeadingContinuationSources | None:
    spans = [span for span in source.get("spans") or [] if isinstance(span, dict)]
    if len(spans) < 2:
        return None
    first_span = spans[0]
    rest_spans = spans[1:]
    first_bbox = _span_bbox(first_span)
    rest_bbox = union_bbox([bbox for bbox in (_span_bbox(span) for span in rest_spans) if bbox])
    if not first_bbox or not rest_bbox:
        return None
    return _LeadingContinuationSources(first_span, rest_spans, first_bbox, rest_bbox)


def _leading_continuation_inline(
    attrs: Dict[str, Any], first_line_length: int
) -> _LeadingContinuationInline:
    first_runs, rest_runs = _split_inline_runs_at_offset(
        attrs.get("inline_runs"), first_line_length
    )
    first_refs, rest_refs = _split_note_refs_by_runs(attrs.get("note_refs"), first_runs, rest_runs)
    return _LeadingContinuationInline(first_runs, rest_runs, first_refs, rest_refs)


def _source_for_spans(
    source: Dict[str, Any], spans: List[Dict[str, Any]], bbox: BBox
) -> Dict[str, Any]:
    pages = [int(span["page"]) for span in spans if span.get("page") is not None]
    out = dict(source)
    out["bbox"] = bbox
    out["spans"] = [dict(span) for span in spans]
    if pages:
        out["page"] = pages[0]
        out["pages"] = sorted(set(pages))
    return out


def _span_bbox(span: Dict[str, Any]) -> BBox | None:
    bbox = span.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        return bbox
    return None


def _replace_referenced_by_block_id(blocks: List[Dict[str, Any]], old_id: Any, new_id: Any) -> None:
    if old_id is None or new_id is None or old_id == new_id:
        return
    for block in blocks:
        attrs = block.get("attrs")
        if not isinstance(attrs, dict):
            continue
        refs = attrs.get("referenced_by")
        if not isinstance(refs, list) or old_id not in refs:
            continue
        updated: List[Any] = []
        for ref in refs:
            replacement = new_id if ref == old_id else ref
            if replacement not in updated:
                updated.append(replacement)
        attrs["referenced_by"] = updated
