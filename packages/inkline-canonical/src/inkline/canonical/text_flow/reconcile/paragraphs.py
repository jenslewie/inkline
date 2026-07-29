"""Geometry-proven cross-page paragraph reconciliation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, TypeGuard

from inkline.canonical.text_flow.reconcile.common import merge_records

_BODY_LANE_EDGE_TOLERANCE = 0.12
_MIN_BODY_LANE_OVERLAP = 0.7
_MIN_BODY_LANE_WIDTH_RATIO = 0.75
_MIN_FIRST_LINE_INDENT = 8.0
_PAGE_BOTTOM_RATIO = 0.8
_PAGE_FOOT_BAND_START_RATIO = 0.75
_PAGE_FOOT_BAND_END_RATIO = 0.85
_PAGE_TOP_RATIO = 0.2


def reconcile_cross_page_paragraphs(
    records: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge only proven adjacent-page paragraph continuations."""

    reconciled = deepcopy(records)
    source_pages = _source_page_numbers(pages)
    index = 0
    while index < len(reconciled):
        candidate = _paragraph_boundary_candidate(
            reconciled,
            index,
            source_pages,
            pages,
            page_layout,
        )
        if candidate is None:
            index += 1
            continue
        right_index, interruptions, evidence = candidate
        merge_records(
            reconciled[index],
            reconciled[right_index],
            reason="cross_page_paragraph_continuation",
            joiner="",
            interruptions=interruptions,
            boundary_evidence=evidence,
        )
        del reconciled[right_index]
        # Re-evaluate the merged record's new last-page fragment. Footnotes from
        # prior transitions remain independent records and are skipped by page.
    return reconciled


def _paragraph_boundary_candidate(
    records: list[dict[str, Any]],
    left_index: int,
    source_pages: set[int],
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> tuple[int, list[dict[str, Any]], dict[str, Any]] | None:
    left = records[left_index]
    if left.get("unit_type") != "paragraph":
        return None
    left_page = _last_page(left)
    if left_page is None:
        return None
    right_page = left_page + 1
    if left_page not in source_pages or right_page not in source_pages:
        return None

    interruptions: list[dict[str, Any]] = []
    for right_index in range(left_index + 1, len(records)):
        right = records[right_index]
        first_page = _first_page(right)
        last_page = _last_page(right)
        if first_page is None or last_page is None:
            return None
        if _prior_transition_footnote(right, first_page, last_page, left_page):
            continue
        if first_page < left_page or first_page > right_page:
            return None
        if first_page == left_page:
            if not _page_foot_interruption(right, left_page, pages, page_layout):
                return None
            if last_page > right_page:
                return None
            interruptions.append(right)
            continue
        if right.get("unit_type") != "paragraph":
            return None
        evidence = _boundary_evidence(
            left,
            right,
            interruptions,
            left_page,
            right_page,
            pages,
            page_layout,
        )
        if evidence is None:
            return None
        return right_index, interruptions, evidence
    return None


def _prior_transition_footnote(
    record: dict[str, Any],
    first_page: int,
    last_page: int,
    left_page: int,
) -> bool:
    return (
        record.get("unit_type") == "footnote"
        and first_page < left_page
        and last_page <= left_page
    )


def _boundary_evidence(
    left: dict[str, Any],
    right: dict[str, Any],
    interruptions: list[dict[str, Any]],
    left_page: int,
    right_page: int,
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> dict[str, Any] | None:
    left_edge = _left_edge_evidence(
        left,
        interruptions,
        left_page,
        pages,
        page_layout,
    )
    right_top = _right_starts_at_page_top(right, right_page, pages, page_layout)
    body_lane = _compatible_body_lanes(
        left,
        right,
        left_page,
        right_page,
        page_layout,
    )
    indent = _right_first_line_indent(right)
    if left_edge is None or not right_top or body_lane is None or indent is None:
        return None
    indent_value, indent_threshold = indent
    if indent_value >= indent_threshold:
        return None
    return {
        "physical_page_transition": [left_page, right_page],
        "left_page_bottom": left_edge == "page_bottom",
        "body_end_above_footnote_band": left_edge == "footnote_band",
        "right_page_top": True,
        "body_lane": body_lane,
        "right_first_line_indent": indent_value,
        "right_first_line_indent_threshold": indent_threshold,
        "across_page_footnotes": bool(interruptions),
    }


def _left_edge_evidence(
    left: dict[str, Any],
    interruptions: list[dict[str, Any]],
    page: int,
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> str | None:
    bbox = _bbox_on_page(left, page)
    page_height = _page_height(page, pages, page_layout)
    if not _valid_bbox(bbox) or page_height is None:
        return None
    if float(bbox[3]) >= page_height * _PAGE_BOTTOM_RATIO:
        return "page_bottom"
    if not interruptions:
        return None
    footnote_bboxes = [_bbox_on_page(record, page) for record in interruptions]
    if not all(_valid_bbox(value) for value in footnote_bboxes):
        return None
    typed_bboxes = [value for value in footnote_bboxes if value is not None]
    band_top = min(float(value[1]) for value in typed_bboxes)
    band_bottom = max(float(value[3]) for value in typed_bboxes)
    if (
        float(bbox[3]) < band_top
        and band_top >= page_height * _PAGE_FOOT_BAND_START_RATIO
        and band_bottom >= page_height * _PAGE_FOOT_BAND_END_RATIO
    ):
        return "footnote_band"
    return None


def _right_starts_at_page_top(
    right: dict[str, Any],
    page: int,
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> bool:
    bbox = _bbox_on_page(right, page)
    page_height = _page_height(page, pages, page_layout)
    page_record = _page_record(page_layout, page)
    if not _valid_bbox(bbox) or page_height is None or page_record is None:
        return False
    body_lane = page_record.get("body_lane")
    line_height = _float(body_lane.get("line_height")) if isinstance(body_lane, dict) else None
    top_limit = max(
        page_height * _PAGE_TOP_RATIO,
        (line_height or 0.0) * 2.0,
    )
    return 0.0 <= float(bbox[1]) <= top_limit


def _compatible_body_lanes(
    left: dict[str, Any],
    right: dict[str, Any],
    left_page: int,
    right_page: int,
    page_layout: dict[str, Any],
) -> dict[str, float] | None:
    left_position = _body_lane_position(left, left_page, page_layout)
    right_position = _body_lane_position(right, right_page, page_layout)
    if left_position is None or right_position is None:
        return None
    left_inset, left_overlap, left_width = left_position
    right_inset, right_overlap, right_width = right_position
    width_ratio = min(left_width, right_width) / max(left_width, right_width)
    if (
        left_overlap < _MIN_BODY_LANE_OVERLAP
        or right_overlap < _MIN_BODY_LANE_OVERLAP
        or abs(left_inset) > _BODY_LANE_EDGE_TOLERANCE
        or abs(right_inset) > _BODY_LANE_EDGE_TOLERANCE
        or abs(left_inset - right_inset) > _BODY_LANE_EDGE_TOLERANCE
        or width_ratio < _MIN_BODY_LANE_WIDTH_RATIO
    ):
        return None
    return {
        "left_inset_ratio": left_inset,
        "right_inset_ratio": right_inset,
        "body_width_ratio": width_ratio,
    }


def _body_lane_position(
    record: dict[str, Any],
    page: int,
    page_layout: dict[str, Any],
) -> tuple[float, float, float] | None:
    bbox = _bbox_on_page(record, page)
    page_record = _page_record(page_layout, page)
    if not _valid_bbox(bbox) or page_record is None:
        return None
    body_lane = page_record.get("body_lane")
    if not isinstance(body_lane, dict):
        return None
    body_left = _float(body_lane.get("body_left"))
    body_right = _float(body_lane.get("body_right"))
    if body_left is None or body_right is None or body_right <= body_left:
        return None
    body_width = body_right - body_left
    record_width = float(bbox[2]) - float(bbox[0])
    if record_width <= 0:
        return None
    overlap = max(
        0.0,
        min(float(bbox[2]), body_right) - max(float(bbox[0]), body_left),
    )
    return (
        (float(bbox[0]) - body_left) / body_width,
        overlap / record_width,
        body_width,
    )


def _right_first_line_indent(right: dict[str, Any]) -> tuple[float, float] | None:
    observation_ids = right.get("observation_ids")
    attrs = right.get("attrs")
    if not isinstance(observation_ids, list) or not observation_ids or not isinstance(attrs, dict):
        return None
    metrics_by_observation = attrs.get("text_line_metrics_by_observation")
    if not isinstance(metrics_by_observation, dict):
        return None
    metrics = metrics_by_observation.get(str(observation_ids[0]))
    if not isinstance(metrics, dict):
        return None
    indent = _float(metrics.get("first_line_indent"))
    char_width = _float(metrics.get("char_width"))
    if indent is None or char_width is None or char_width <= 0:
        return None
    return indent, max(_MIN_FIRST_LINE_INDENT, char_width * 1.15)


def _page_foot_interruption(
    record: dict[str, Any],
    page: int,
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> bool:
    if record.get("unit_type") != "footnote":
        return False
    bbox = _bbox_on_page(record, page)
    page_height = _page_height(page, pages, page_layout)
    return (
        _valid_bbox(bbox)
        and page_height is not None
        and float(bbox[1]) >= page_height * _PAGE_FOOT_BAND_START_RATIO
    )


def _bbox_on_page(record: dict[str, Any], page: int) -> list[float] | None:
    spans = record.get("spans")
    span_bboxes = [
        span["bbox"]
        for span in spans or []
        if isinstance(span, dict)
        and span.get("page") == page
        and _valid_bbox(span.get("bbox"))
    ]
    if span_bboxes:
        return [
            min(float(bbox[0]) for bbox in span_bboxes),
            min(float(bbox[1]) for bbox in span_bboxes),
            max(float(bbox[2]) for bbox in span_bboxes),
            max(float(bbox[3]) for bbox in span_bboxes),
        ]
    bbox = record.get("bbox")
    if record.get("page") == page and _valid_bbox(bbox):
        return bbox
    return None


def _page_height(
    page: int,
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> float | None:
    page_record = _page_record(page_layout, page)
    if page_record is not None:
        page_size = page_record.get("page_size")
        value = page_size.get("height") if isinstance(page_size, dict) else None
        height = _float(value)
        if height is not None:
            return height
        body_lane = page_record.get("body_lane")
        if isinstance(body_lane, dict):
            height = _float(body_lane.get("page_height"))
            if height is not None:
                return height
    source_page = next(
        (
            record
            for record in pages
            if isinstance(record, dict) and record.get("page") == page
        ),
        None,
    )
    return _float(source_page.get("height")) if source_page is not None else None


def _page_record(
    page_layout: dict[str, Any], page: int
) -> dict[str, Any] | None:
    records = page_layout.get("pages")
    if not isinstance(records, list):
        return None
    return next(
        (
            record
            for record in records
            if isinstance(record, dict) and record.get("page") == page
        ),
        None,
    )


def _source_page_numbers(pages: list[dict[str, Any]]) -> set[int]:
    return {
        int(record["page"])
        for record in pages
        if isinstance(record, dict) and isinstance(record.get("page"), int)
    }


def _first_page(record: dict[str, Any]) -> int | None:
    pages = record.get("pages")
    value = pages[0] if isinstance(pages, list) and pages else record.get("page")
    return int(value) if isinstance(value, int) else None


def _last_page(record: dict[str, Any]) -> int | None:
    pages = record.get("pages")
    value = pages[-1] if isinstance(pages, list) and pages else record.get("page")
    return int(value) if isinstance(value, int) else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_bbox(value: Any) -> TypeGuard[list[float]]:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )
