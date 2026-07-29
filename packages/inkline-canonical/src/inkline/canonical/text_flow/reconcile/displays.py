"""Type-strict, geometry-proven cross-page display reconciliation."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, TypeGuard

from inkline.canonical.text_flow.reconcile.common import merge_records

_DISPLAY_LANE_TOLERANCE = 0.12
_MIN_BODY_LANE_OVERLAP = 0.7
_PAGE_BOTTOM_RATIO = 0.8
_PAGE_FOOT_BAND_START_RATIO = 0.75
_PAGE_FOOT_BAND_END_RATIO = 0.85
_PAGE_TOP_RATIO = 0.2
_ATTRIBUTION_SIGNALS = {
    "right_aligned_attribution",
    "terminal_right_aligned_attribution",
}


def reconcile_cross_page_displays(
    records: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge only proven adjacent-page display continuations."""

    reconciled = deepcopy(records)
    eligible_endpoints = {
        id(record)
        for record in reconciled
        if record.get("unit_type") == "display_block"
        and _canonical_single_page_record(record)
    }
    source_pages = _source_page_numbers(pages)
    index = 0
    while index < len(reconciled):
        candidate = _display_boundary_candidate(
            reconciled,
            index,
            eligible_endpoints,
            source_pages,
            pages,
            page_layout,
        )
        if candidate is None:
            index += 1
            continue
        right_index, interruptions, evidence, layout_form = candidate
        merge_records(
            reconciled[index],
            reconciled[right_index],
            reason="cross_page_display_block_continuation",
            joiner="\n" if layout_form == "short_line_group" else "",
            interruptions=interruptions,
            boundary_evidence=evidence,
        )
        del reconciled[right_index]
        # Keep the merged left endpoint in place so its new physical boundary
        # must independently prove the next transition.
    return reconciled


def _display_boundary_candidate(
    records: list[dict[str, Any]],
    left_index: int,
    eligible_endpoints: set[int],
    source_pages: set[int],
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> tuple[int, list[dict[str, Any]], dict[str, Any], str] | None:
    left = records[left_index]
    if id(left) not in eligible_endpoints or left.get("unit_type") != "display_block":
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
            if (
                last_page > right_page
                or not _page_foot_interruption(
                    right,
                    left_page,
                    pages,
                    page_layout,
                )
            ):
                return None
            interruptions.append(right)
            continue
        if (
            id(right) not in eligible_endpoints
            or right.get("unit_type") != "display_block"
            or not _canonical_single_page_record(right, right_page)
        ):
            return None
        boundary = _boundary_evidence(
            left,
            right,
            interruptions,
            left_page,
            right_page,
            pages,
            page_layout,
        )
        if boundary is None:
            return None
        evidence, layout_form = boundary
        return right_index, interruptions, evidence, layout_form
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
) -> tuple[dict[str, Any], str] | None:
    if not _valid_record_geometry(left) or not _valid_record_geometry(right):
        return None
    if any(not _valid_record_geometry(record) for record in interruptions):
        return None
    left_form = _layout_form(left)
    right_form = _layout_form(right)
    if (
        left_form is None
        or left_form != right_form
        or _has_attribution_boundary(left, left_form)
        or _has_attribution_boundary(right, right_form)
    ):
        return None
    left_edge = _left_edge_evidence(
        left,
        interruptions,
        left_page,
        pages,
        page_layout,
    )
    right_top = _right_starts_at_page_top(right, right_page, pages, page_layout)
    display_lane = _compatible_display_lanes(
        left,
        right,
        left_page,
        right_page,
        page_layout,
    )
    if left_edge is None or not right_top or display_lane is None:
        return None
    return (
        {
            "physical_page_transition": [left_page, right_page],
            "left_page_bottom": left_edge == "page_bottom",
            "display_end_above_footnote_band": left_edge == "footnote_band",
            "right_page_top": True,
            "layout_form": left_form,
            "display_lane": display_lane,
            "across_page_footnotes": bool(interruptions),
        },
        left_form,
    )


def _layout_form(record: dict[str, Any]) -> str | None:
    attrs = record.get("attrs")
    if not isinstance(attrs, dict):
        return None
    direct_form: str | None = None
    if "layout_form" in attrs:
        direct = attrs["layout_form"]
        if not isinstance(direct, str) or not direct:
            return None
        direct_form = direct
    fragments = attrs.get("layout_fragments")
    if fragments is None:
        return direct_form
    if not isinstance(fragments, list) or not fragments:
        return None
    fragment_forms: set[str] = set()
    for fragment in fragments:
        if (
            not isinstance(fragment, dict)
            or fragment.get("classified_type") != "display_block"
            or fragment.get("status") != "resolved"
            or not isinstance(fragment.get("signals"), list)
            or not all(isinstance(signal, str) for signal in fragment["signals"])
        ):
            return None
        form = fragment.get("layout_form")
        if not isinstance(form, str) or not form:
            return None
        fragment_forms.add(form)
    if len(fragment_forms) != 1:
        return None
    fragment_form = next(iter(fragment_forms))
    return fragment_form if direct_form in {None, fragment_form} else None


def _has_attribution_boundary(record: dict[str, Any], layout_form: str) -> bool:
    if layout_form == "attribution":
        return True
    attrs = record.get("attrs")
    if not isinstance(attrs, dict):
        return True
    if attrs.get("has_attribution_line"):
        return True
    fragments = attrs.get("layout_fragments")
    if not isinstance(fragments, list):
        return False
    return any(
        isinstance(fragment, dict)
        and isinstance(fragment.get("signals"), list)
        and bool(_ATTRIBUTION_SIGNALS.intersection(fragment["signals"]))
        for fragment in fragments
    )


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
    line_height = (
        _float(body_lane.get("line_height"))
        if isinstance(body_lane, dict)
        else None
    )
    top_limit = max(page_height * _PAGE_TOP_RATIO, (line_height or 0.0) * 2.0)
    return 0.0 <= float(bbox[1]) <= top_limit


def _compatible_display_lanes(
    left: dict[str, Any],
    right: dict[str, Any],
    left_page: int,
    right_page: int,
    page_layout: dict[str, Any],
) -> dict[str, Any] | None:
    left_position = _display_lane_position(left, left_page, page_layout)
    right_position = _display_lane_position(right, right_page, page_layout)
    if left_position is None or right_position is None:
        return None
    axes = ("left", "center", "right")
    differences = [
        abs(left_value - right_value)
        for left_value, right_value in zip(left_position, right_position, strict=True)
    ]
    best_index = min(range(len(differences)), key=differences.__getitem__)
    difference = differences[best_index]
    if difference > _DISPLAY_LANE_TOLERANCE:
        return None
    return {
        "axis": axes[best_index],
        "left_position_ratio": left_position[best_index],
        "right_position_ratio": right_position[best_index],
        "difference_ratio": difference,
        "tolerance": _DISPLAY_LANE_TOLERANCE,
    }


def _display_lane_position(
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
    overlap = max(
        0.0,
        min(float(bbox[2]), body_right) - max(float(bbox[0]), body_left),
    )
    if record_width <= 0.0 or overlap / record_width < _MIN_BODY_LANE_OVERLAP:
        return None
    return (
        (float(bbox[0]) - body_left) / body_width,
        ((float(bbox[0]) + float(bbox[2])) / 2.0 - body_left) / body_width,
        (float(bbox[2]) - body_left) / body_width,
    )


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


def _valid_record_geometry(record: dict[str, Any]) -> bool:
    if not _valid_bbox(record.get("bbox")):
        return False
    spans = record.get("spans")
    return isinstance(spans, list) and all(
        isinstance(span, dict)
        and type(span.get("page")) is int
        and _valid_bbox(span.get("bbox"))
        for span in spans
    )


def _bbox_on_page(record: dict[str, Any], page: int) -> list[float] | None:
    spans = record.get("spans")
    if not isinstance(spans, list):
        return None
    target_spans = [
        span
        for span in spans
        if isinstance(span, dict) and type(span.get("page")) is int and span["page"] == page
    ]
    if target_spans:
        span_bboxes = [span.get("bbox") for span in target_spans]
        if not all(_valid_bbox(bbox) for bbox in span_bboxes):
            return None
        valid_bboxes = [bbox for bbox in span_bboxes if _valid_bbox(bbox)]
        return [
            min(float(bbox[0]) for bbox in valid_bboxes),
            min(float(bbox[1]) for bbox in valid_bboxes),
            max(float(bbox[2]) for bbox in valid_bboxes),
            max(float(bbox[3]) for bbox in valid_bboxes),
        ]
    if _canonical_single_page_record(record, page) and _valid_bbox(record.get("bbox")):
        return record["bbox"]
    return None


def _page_height(
    page: int,
    pages: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> float | None:
    del pages
    page_record = _page_record(page_layout, page)
    if page_record is None:
        return None
    page_size = page_record.get("page_size")
    if not isinstance(page_size, dict):
        return None
    height = _float(page_size.get("height"))
    return height if height is not None and height > 0 else None


def _page_record(
    page_layout: dict[str, Any], page: int
) -> dict[str, Any] | None:
    records = page_layout.get("pages")
    if not isinstance(records, list):
        return None
    matches = [
        record
        for record in records
        if isinstance(record, dict)
        and type(record.get("page")) is int
        and record["page"] == page
    ]
    return matches[0] if len(matches) == 1 else None


def _source_page_numbers(pages: list[dict[str, Any]]) -> set[int]:
    return {
        record["page"]
        for record in pages
        if isinstance(record, dict) and type(record.get("page")) is int
    }


def _first_page(record: dict[str, Any]) -> int | None:
    pages = record.get("pages")
    if not isinstance(pages, list) or not pages or type(pages[0]) is not int:
        return None
    return pages[0]


def _last_page(record: dict[str, Any]) -> int | None:
    pages = record.get("pages")
    if not isinstance(pages, list) or not pages or type(pages[-1]) is not int:
        return None
    return pages[-1]


def _canonical_single_page_record(
    record: dict[str, Any], page: int | None = None
) -> bool:
    pages = record.get("pages")
    if not isinstance(pages, list) or not pages or type(pages[0]) is not int:
        return False
    expected_page = pages[0] if page is None else page
    return all(type(value) is int and value == expected_page for value in pages)


def _float(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _valid_bbox(value: Any) -> TypeGuard[list[float]]:
    if not isinstance(value, list) or len(value) != 4:
        return False
    if not all(type(number) in (int, float) for number in value):
        return False
    try:
        coordinates = [float(number) for number in value]
    except OverflowError:
        return False
    return (
        all(math.isfinite(number) for number in coordinates)
        and coordinates[0] < coordinates[2]
        and coordinates[1] < coordinates[3]
    )
