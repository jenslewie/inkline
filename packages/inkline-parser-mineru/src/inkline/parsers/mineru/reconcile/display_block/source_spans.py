"""Source-span helpers for display-block reconciliation."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...normalize.builders import union_bbox
from ...schema.models import BBox
from ..layout_helpers import _scaled_body_metrics


def text_for_spans(spans: List[Dict[str, Any]]) -> str:
    return "\n".join(
        str(span.get("text") or "").strip() for span in spans if span.get("text")
    ).strip()


def apply_source_from_spans(
    block: Dict[str, Any],
    original_source: Dict[str, Any],
    spans: List[Dict[str, Any]],
) -> None:
    bboxes = [span_bbox(span) for span in spans]
    bbox = union_bbox([bbox for bbox in bboxes if bbox])
    if not bbox:
        return
    pages = [int(span["page"]) for span in spans if span.get("page") is not None]
    source = dict(original_source)
    source["bbox"] = bbox
    source["spans"] = [dict(span) for span in spans]
    if pages:
        source["page"] = pages[0]
        source["pages"] = sorted(set(pages))
    block["source"] = source


def surrounding_spans(
    source_spans: List[Dict[str, Any]],
    display_spans: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not source_spans or not display_spans:
        return [], []
    display_ids = {id(span) for span in display_spans}
    indexes = [idx for idx, span in enumerate(source_spans) if id(span) in display_ids]
    if not indexes:
        return [], []
    return source_spans[: min(indexes)], source_spans[max(indexes) + 1 :]


def apply_embedded_display_source(
    original: Dict[str, Any],
    display_block: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
    start_line: int,
    end_line: int,
) -> None:
    source = original.get("source") or {}
    spans = [span for span in source.get("spans") or [] if isinstance(span, dict)]
    display_spans = embedded_display_spans(
        spans,
        layout,
        page_widths,
        page_body_lefts,
        max(1, end_line - start_line),
    )
    if display_spans:
        apply_source_from_spans(display_block, source, display_spans)


def embedded_display_spans(
    spans: List[Dict[str, Any]],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
    line_count: int,
) -> List[Dict[str, Any]]:
    if not spans:
        return []
    body_seen = False
    candidates: List[Dict[str, Any]] = []
    for span in spans:
        if is_body_width_span(span, layout, page_widths, page_body_lefts):
            if candidates:
                break
            body_seen = True
            continue
        if body_seen and is_display_lane_span(span, layout, page_widths):
            candidates.append(span)
            if len(candidates) >= line_count:
                break
    return candidates


def is_body_width_span(
    span: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
) -> bool:
    bbox = span_bbox(span)
    page = span.get("page")
    if not bbox or page is None:
        return False
    page = int(page)
    fallback_left, _body_right, body_width = _scaled_body_metrics(
        layout, page_widths.get(page) if page_widths else None
    )
    body_left = page_body_lefts.get(page, fallback_left) if page_body_lefts else fallback_left
    x0 = float(bbox[0])
    width = max(0.0, float(bbox[2]) - x0)
    return x0 <= body_left + max(24.0, body_width * 0.035) and width >= body_width * 0.65


def span_has_body_flow_layout(
    span: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
    page_body_lefts: Dict[int, float] | None,
) -> bool:
    bbox = span_bbox(span)
    page = span.get("page")
    if not bbox or page is None:
        return False
    page = int(page)
    fallback_left, _body_right, body_width = _scaled_body_metrics(
        layout, page_widths.get(page) if page_widths else None
    )
    body_left = page_body_lefts.get(page, fallback_left) if page_body_lefts else fallback_left
    x0 = float(bbox[0])
    width = max(0.0, float(bbox[2]) - x0)
    if width < body_width * 0.65:
        return False
    near_body_left = x0 <= body_left + max(48.0, body_width * 0.06)
    indent = x0 - body_left
    first_line_indent = max(34.0, body_width * 0.045) <= indent <= max(82.0, body_width * 0.11)
    return near_body_left or first_line_indent


def is_display_lane_span(
    span: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None,
) -> bool:
    bbox = span_bbox(span)
    page = span.get("page")
    if not bbox or page is None:
        return False
    body_left, _body_right, body_width = _scaled_body_metrics(
        layout, page_widths.get(int(page)) if page_widths else None
    )
    x0 = float(bbox[0])
    width = max(0.0, float(bbox[2]) - x0)
    return x0 >= body_left + max(34.0, body_width * 0.04) or width <= body_width * 0.58


def span_bbox(span: Dict[str, Any]) -> BBox | None:
    bbox = span.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        return bbox
    return None


def line_has_body_lane_source_span(
    block: Dict[str, Any],
    lines: List[str],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
    page_body_lefts: Dict[int, float] | None = None,
) -> bool:
    span = source_span_for_text_line(block, lines, idx)
    return bool(span and is_body_width_span(span, layout, page_widths, page_body_lefts))


def line_has_body_flow_source_span(
    block: Dict[str, Any],
    lines: List[str],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
    page_body_lefts: Dict[int, float] | None = None,
) -> bool:
    span = source_span_for_text_line(block, lines, idx)
    return bool(span and span_has_body_flow_layout(span, layout, page_widths, page_body_lefts))


def source_span_for_text_line(
    block: Dict[str, Any], lines: List[str], idx: int
) -> Dict[str, Any] | None:
    spans = [
        span for span in (block.get("source") or {}).get("spans") or [] if isinstance(span, dict)
    ]
    if not spans:
        return None
    nonempty_indexes = [line_idx for line_idx, line in enumerate(lines) if line.strip()]
    if len(spans) != len(nonempty_indexes):
        return None
    try:
        ordinal = nonempty_indexes.index(idx)
    except ValueError:
        return None
    return spans[ordinal]
