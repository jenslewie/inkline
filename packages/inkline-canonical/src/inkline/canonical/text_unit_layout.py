from __future__ import annotations

from collections import Counter
from copy import deepcopy
from itertools import pairwise
from statistics import median
from typing import Any

MIN_BODY_WIDTH_RATIO = 0.2
MAX_BODY_WIDTH_RATIO = 0.92
MIN_LOCAL_PROFILE_REFERENCES = 2
MIN_DOMINANT_REFERENCE_RATIO = 0.7
MAX_DOMINANT_WIDTH_SPREAD_RATIO = 1.5


def audit_text_unit_layout(
    units: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    page_layout_profile_map, profile_quality = _page_layout_profile_map(units, pages)
    book_layout_profile = _book_layout_profile(page_layout_profile_map, units)
    page_sizes = _page_sizes(pages)
    page_coverage = _page_coverage(pages, units, page_layout_profile_map, observations or [])
    unit_records: list[dict[str, Any]] = []
    summary = {
        "total_pages": page_coverage["total_pages"],
        "pages_with_profiles": len(page_layout_profile_map),
        "pages_without_profiles": len(page_coverage["pages_without_profiles"]),
        "pages_without_profiles_by_reason": page_coverage["pages_without_profiles_by_reason"],
        "paragraph_units": 0,
        "classified_display_blocks": 0,
        "skipped_no_bbox": 0,
        "skipped_no_profile": 0,
    }
    for unit in units:
        if unit.get("unit_type") != "paragraph":
            continue
        summary["paragraph_units"] += 1
        record = _unit_record(unit, page_layout_profile_map, page_sizes)
        unit_records.append(record)
        if record["decision"] == "display_block":
            summary["classified_display_blocks"] += 1
        elif record["decision"] == "skipped_no_bbox":
            summary["skipped_no_bbox"] += 1
        elif record["decision"] == "skipped_no_profile":
            summary["skipped_no_profile"] += 1
    return {
        "summary": summary,
        "page_coverage": page_coverage,
        "profile_quality": profile_quality,
        "book_layout_profile": book_layout_profile,
        "page_layout_profiles": _page_layout_profile_records(
            page_layout_profile_map, book_layout_profile
        ),
        "unit_records": unit_records,
    }


def classify_text_units_by_layout(
    units: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    audit = audit_text_unit_layout(units, pages)
    records_by_unit_id = {record["unit_id"]: record for record in audit["unit_records"]}
    classified = deepcopy(units)
    for unit in classified:
        record = records_by_unit_id.get(str(unit.get("unit_id")))
        if record and record["decision"] == "display_block":
            unit["unit_type"] = "display_block"
            attrs = unit.setdefault("attrs", {})
            attrs["layout_role"] = "set_off"
            if record.get("layout_form"):
                attrs["layout_form"] = record["layout_form"]
            if record.get("alignment"):
                attrs["alignment"] = record["alignment"]
            attrs["layout_classification"] = {
                "method": "page_body_lane_geometry_v1",
                "signals": list(record["signals"]),
            }
    return classified


def _page_layout_profile_map(
    units: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    page_sizes = {
        int(page["page"]): {
            "width": float(page["width"]),
            "height": float(page["height"]),
        }
        for page in pages
    }
    profile_quality: Counter[str] = Counter()
    grouped: dict[int, list[list[float]]] = {}
    for unit in units:
        if unit.get("unit_type") != "paragraph":
            continue
        page = int(unit["page"])
        grouped.setdefault(page, []).extend(_reference_bboxes(unit, page))

    profiles: dict[int, dict[str, Any]] = {}
    deferred_pages: dict[int, tuple[list[list[float]], str]] = {}
    for page, bboxes in grouped.items():
        profile, rejection_reason = _local_page_profile(page, bboxes, page_sizes)
        if profile:
            profiles[page] = profile
            profile_quality["accepted"] += 1
            continue
        deferred_pages[page] = (bboxes, rejection_reason)

    for page, (bboxes, rejection_reason) in deferred_pages.items():
        source_page = _nearest_profile_page(page, profiles)
        if source_page is None:
            if rejection_reason == "needs_fallback":
                profile_quality["rejected_no_stable_profile"] += 1
            else:
                profile_quality[f"rejected_{rejection_reason}"] += 1
            continue
        size = page_sizes.get(page, {})
        source = profiles[source_page]
        profiles[page] = {
            "body_left": source["body_left"],
            "body_right": source["body_right"],
            "body_width": source["body_width"],
            "page_width": float(size.get("width") or source["page_width"]),
            "page_height": float(size.get("height") or source["page_height"]),
            "reference_unit_count": len(bboxes),
            "profile_source": "nearest_page",
            "profile_source_page": source_page,
        }
        profile_quality["filled_from_nearest_profile"] += 1
    return profiles, _profile_quality_summary(profile_quality)


def _local_page_profile(
    page: int,
    bboxes: list[list[float]],
    page_sizes: dict[int, dict[str, float]],
) -> tuple[dict[str, Any] | None, str]:
    dominant_bboxes = _dominant_reference_bboxes(bboxes)
    if not dominant_bboxes:
        return None, "needs_fallback"
    if _has_unstable_dominant_widths(dominant_bboxes):
        return None, "unstable_widths"
    left = median(bbox[0] for bbox in dominant_bboxes)
    right = median(bbox[2] for bbox in dominant_bboxes)
    width = median(_width(bbox) for bbox in dominant_bboxes)
    if width <= 0:
        return None, "invalid_width"
    size = page_sizes.get(page, {})
    page_width = float(size.get("width") or 0.0)
    if _has_extreme_body_width(width, page_width):
        return None, "extreme_body_width"
    return {
        "body_left": float(left),
        "body_right": float(right),
        "body_width": float(width),
        "page_width": page_width,
        "page_height": float(size.get("height") or 0.0),
        "reference_unit_count": len(dominant_bboxes),
    }, ""


def _dominant_reference_bboxes(bboxes: list[list[float]]) -> list[list[float]]:
    valid_bboxes = [bbox for bbox in bboxes if _width(bbox) > 0]
    if len(valid_bboxes) < MIN_LOCAL_PROFILE_REFERENCES:
        return []
    widest = max(_width(bbox) for bbox in valid_bboxes)
    threshold = widest * MIN_DOMINANT_REFERENCE_RATIO
    dominant_bboxes = [bbox for bbox in valid_bboxes if _width(bbox) >= threshold]
    if len(dominant_bboxes) < MIN_LOCAL_PROFILE_REFERENCES:
        return []
    return dominant_bboxes


def _page_sizes(pages: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    return {
        int(page["page"]): {
            "width": float(page["width"]),
            "height": float(page["height"]),
        }
        for page in pages
        if isinstance(page.get("page"), int)
        and isinstance(page.get("width"), int | float)
        and isinstance(page.get("height"), int | float)
    }


def _profile_quality_summary(profile_quality: Counter[str]) -> dict[str, int]:
    keys = (
        "accepted",
        "filled_from_nearest_profile",
        "rejected_no_stable_profile",
        "rejected_invalid_width",
        "rejected_unstable_widths",
        "rejected_extreme_body_width",
    )
    return {key: int(profile_quality.get(key, 0)) for key in keys}


def _has_unstable_dominant_widths(bboxes: list[list[float]]) -> bool:
    widths = [_width(bbox) for bbox in bboxes if _width(bbox) > 0]
    if not widths:
        return True
    return max(widths) / min(widths) > MAX_DOMINANT_WIDTH_SPREAD_RATIO


def _has_extreme_body_width(body_width: float, page_width: float) -> bool:
    if page_width <= 0:
        return False
    ratio = body_width / page_width
    return ratio < MIN_BODY_WIDTH_RATIO or ratio > MAX_BODY_WIDTH_RATIO


def _page_layout_profile_records(
    page_layout_profile_map: dict[int, dict[str, Any]], book_layout_profile: dict[str, Any]
) -> list[dict[str, Any]]:
    records = []
    for page, profile in sorted(page_layout_profile_map.items()):
        body_width_delta = None
        book_body_width = book_layout_profile.get("body_width")
        if isinstance(book_body_width, int | float):
            body_width_delta = round(float(profile["body_width"]) - float(book_body_width), 4)
        record = {
            "page": page,
            "profile_scope": "page",
            "profile_source": str(profile.get("profile_source") or "local"),
            "page_width": profile["page_width"],
            "page_height": profile["page_height"],
            "body_left": profile["body_left"],
            "body_right": profile["body_right"],
            "body_width": profile["body_width"],
            "book_body_width": book_body_width,
            "body_width_delta": body_width_delta,
            "indent_unit": book_layout_profile.get("indent_unit"),
            "line_height": book_layout_profile.get("line_height"),
            "normal_gap_y": book_layout_profile.get("normal_gap_y"),
            "display_gap_y": book_layout_profile.get("display_gap_y"),
            "reference_unit_count": profile["reference_unit_count"],
        }
        if profile.get("profile_source"):
            record["profile_source_page"] = profile["profile_source_page"]
        records.append(record)
    return records


def _book_layout_profile(
    page_layout_profile_map: dict[int, dict[str, Any]], units: list[dict[str, Any]]
) -> dict[str, Any]:
    local_profiles = [
        profile for profile in page_layout_profile_map.values() if not profile.get("profile_source")
    ]
    return {
        "profile_scope": "book",
        "source_page_count": len(local_profiles),
        "body_width": _median_or_none([float(profile["body_width"]) for profile in local_profiles]),
        "indent_unit": _median_or_none(_indent_units(units)),
        "line_height": _median_or_none(_line_heights(units)),
        "normal_gap_y": _median_or_none(_normal_gaps(units, page_layout_profile_map)),
        "display_gap_y": _median_or_none(_display_gaps(units, page_layout_profile_map)),
    }


def _indent_units(units: list[dict[str, Any]]) -> list[float]:
    indents: list[float] = []
    for metrics in _text_line_metrics(units):
        indent = _metric_float(metrics, "first_line_indent")
        if indent is None or indent <= 0:
            continue
        char_width = _metric_float(metrics, "char_width")
        if char_width is not None and indent < char_width * 0.75:
            continue
        indents.append(indent)
    return indents


def _text_line_metrics(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for unit in units:
        attrs = unit.get("attrs") if isinstance(unit.get("attrs"), dict) else {}
        by_observation = attrs.get("text_line_metrics_by_observation")
        if not isinstance(by_observation, dict):
            continue
        for metrics in by_observation.values():
            if isinstance(metrics, dict):
                records.append(metrics)
    return records


def _line_heights(units: list[dict[str, Any]]) -> list[float]:
    heights: list[float] = []
    for unit in units:
        for bbox in _line_bboxes(unit):
            height = _height(bbox)
            if height > 0:
                heights.append(height)
    return heights


def _normal_gaps(
    units: list[dict[str, Any]], page_layout_profile_map: dict[int, dict[str, Any]]
) -> list[float]:
    gaps: list[float] = []
    for bboxes in _body_like_line_bboxes_by_page(units, page_layout_profile_map).values():
        sorted_bboxes = sorted(bboxes, key=lambda bbox: (bbox[1], bbox[0]))
        for previous, current in pairwise(sorted_bboxes):
            gap = float(current[1]) - float(previous[3])
            if 0 <= gap <= max(48.0, _height(previous) * 2.0):
                gaps.append(gap)
    return gaps


def _display_gaps(
    units: list[dict[str, Any]], page_layout_profile_map: dict[int, dict[str, Any]]
) -> list[float]:
    normal_gap = _median_or_none(_normal_gaps(units, page_layout_profile_map))
    if normal_gap is None:
        return []
    threshold = max(normal_gap * 2.5, normal_gap + 18.0)
    gaps: list[float] = []
    for bboxes in _body_like_line_bboxes_by_page(units, page_layout_profile_map).values():
        sorted_bboxes = sorted(bboxes, key=lambda bbox: (bbox[1], bbox[0]))
        for previous, current in pairwise(sorted_bboxes):
            gap = float(current[1]) - float(previous[3])
            if gap >= threshold:
                gaps.append(gap)
    return gaps


def _body_like_line_bboxes_by_page(
    units: list[dict[str, Any]], page_layout_profile_map: dict[int, dict[str, Any]]
) -> dict[int, list[list[float]]]:
    grouped: dict[int, list[list[float]]] = {}
    for unit in units:
        if unit.get("unit_type") != "paragraph":
            continue
        page = int(unit["page"])
        profile = page_layout_profile_map.get(page)
        if not profile or profile.get("profile_source"):
            continue
        for bbox in _line_bboxes(unit):
            if _is_body_like_bbox(bbox, profile):
                grouped.setdefault(page, []).append(bbox)
    return grouped


def _is_body_like_bbox(bbox: list[float], profile: dict[str, Any]) -> bool:
    body_width = float(profile["body_width"])
    if body_width <= 0:
        return False
    left_delta = abs(float(bbox[0]) - float(profile["body_left"]))
    right_delta = abs(float(bbox[2]) - float(profile["body_right"]))
    return (
        _width(bbox) >= body_width * 0.70
        and left_delta <= max(24.0, body_width * 0.06)
        and right_delta <= max(32.0, body_width * 0.08)
    )


def _median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _metric_float(metrics: dict[str, Any], key: str) -> float | None:
    try:
        return float(metrics[key])
    except (KeyError, TypeError, ValueError):
        return None


def _nearest_profile_page(
    page: int, page_layout_profile_map: dict[int, dict[str, Any]]
) -> int | None:
    if not page_layout_profile_map:
        return None
    return min(page_layout_profile_map, key=lambda candidate: (abs(candidate - page), candidate))


def _page_coverage(
    pages: list[dict[str, Any]],
    units: list[dict[str, Any]],
    page_layout_profile_map: dict[int, dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    page_numbers = sorted(int(page["page"]) for page in pages)
    units_by_page: dict[int, Counter[str]] = {page: Counter() for page in page_numbers}
    observation_kinds_by_page: dict[int, Counter[str]] = {page: Counter() for page in page_numbers}
    for unit in units:
        page = int(unit["page"])
        if page in units_by_page:
            units_by_page[page][str(unit.get("unit_type") or "")] += 1
    for observation in observations:
        page = int(observation["page"])
        if page in observation_kinds_by_page:
            observation_kinds_by_page[page][str(observation.get("kind") or "")] += 1

    profile_pages = set(page_layout_profile_map)
    pages_without_profiles = [
        {
            "page": page,
            "reason": _page_without_profile_reason(
                units_by_page[page], observation_kinds_by_page[page]
            ),
        }
        for page in page_numbers
        if page not in profile_pages
    ]
    return {
        "total_pages": len(page_numbers),
        "pages_with_profiles": len(profile_pages),
        "pages_without_profiles": pages_without_profiles,
        "pages_without_profiles_by_reason": dict(
            Counter(record["reason"] for record in pages_without_profiles)
        ),
        "mixed_pages": {
            "heading_with_paragraph_units": [
                page
                for page in page_numbers
                if units_by_page[page].get("heading") and units_by_page[page].get("paragraph")
            ],
            "image_with_text_units": [
                page
                for page in page_numbers
                if observation_kinds_by_page[page].get("image_region")
                and sum(units_by_page[page].values()) > 0
            ],
            "table_with_text_units": [
                page
                for page in page_numbers
                if observation_kinds_by_page[page].get("table_region")
                and sum(units_by_page[page].values()) > 0
            ],
        },
    }


def _page_without_profile_reason(unit_types: Counter[str], observation_kinds: Counter[str]) -> str:
    if unit_types.get("paragraph"):
        return "paragraph_without_profile"
    if unit_types and set(unit_types) == {"heading"}:
        return "heading_only"
    if unit_types:
        return "non_paragraph_text_units"

    content_kinds = Counter(
        {kind: count for kind, count in observation_kinds.items() if kind != "page_marker"}
    )
    if not content_kinds:
        return "empty"
    if set(content_kinds) == {"image_region"}:
        return "image_only"
    if set(content_kinds) == {"table_region"}:
        return "table_only"
    if set(content_kinds) == {"text_region"}:
        return "text_without_text_units"
    if content_kinds.get("image_region") and content_kinds.get("text_region"):
        return "image_with_text_without_units"
    if content_kinds.get("table_region") and content_kinds.get("text_region"):
        return "table_with_text_without_units"
    return "non_text_observations"


def _reference_bboxes(unit: dict[str, Any], page: int) -> list[list[float]]:
    span_bboxes = [
        [float(value) for value in span["bbox"]]
        for span in unit.get("spans") or []
        if isinstance(span, dict)
        and _span_page(span, page) == page
        and _valid_bbox(span.get("bbox"))
    ]
    if span_bboxes:
        return span_bboxes
    bbox = unit.get("bbox")
    if _valid_bbox(bbox):
        return [[float(value) for value in bbox]]
    return []


def _span_page(span: dict[str, Any], fallback: int) -> int:
    value = span.get("page")
    return int(value) if isinstance(value, int) else fallback


def _unit_record(
    unit: dict[str, Any],
    page_layout_profile_map: dict[int, dict[str, Any]],
    page_sizes: dict[int, dict[str, float]],
) -> dict[str, Any]:
    bbox = unit.get("bbox")
    base = {
        "unit_id": str(unit["unit_id"]),
        "page": int(unit["page"]),
        "original_type": str(unit["unit_type"]),
        "classified_type": str(unit["unit_type"]),
        "bbox": deepcopy(bbox),
        "signals": [],
    }
    if _is_caption_candidate(unit):
        width = _width(bbox) if _valid_bbox(bbox) else None
        return {
            **base,
            "width": width,
            "body_width": None,
            "width_ratio": None,
            "left_inset": None,
            "right_inset": None,
            "signals": ["caption_candidate"],
            "decision": "paragraph",
        }
    if not _valid_bbox(bbox):
        return {
            **base,
            "width": None,
            "body_width": None,
            "width_ratio": None,
            "left_inset": None,
            "right_inset": None,
            "decision": "skipped_no_bbox",
        }
    profile = page_layout_profile_map.get(int(unit["page"]))
    if not profile:
        width = _width(bbox)
        return {
            **base,
            "width": width,
            "body_width": None,
            "width_ratio": None,
            "left_inset": None,
            "right_inset": None,
            "decision": "skipped_no_profile",
        }
    metrics = _unit_metrics(bbox, profile)
    if profile.get("profile_source") == "nearest_page":
        return {
            **base,
            "classified_type": "paragraph",
            **metrics,
            "profile_source": "nearest_page",
            "profile_source_page": profile["profile_source_page"],
            "signals": [],
            "decision": "paragraph",
        }
    short_line_group = _short_line_group(unit, page_sizes)
    if short_line_group:
        return {
            **base,
            "classified_type": "display_block",
            **metrics,
            "signals": [f"{short_line_group}_aligned_short_line_group"],
            "layout_form": "short_line_group",
            "alignment": short_line_group,
            "decision": "display_block",
        }
    signals = _display_signals(bbox, profile)
    decision = "display_block" if _is_display_candidate(signals) else "paragraph"
    return {
        **base,
        "classified_type": decision,
        **metrics,
        "signals": signals,
        "decision": decision,
    }


def _is_caption_candidate(unit: dict[str, Any]) -> bool:
    attrs = unit.get("attrs")
    return isinstance(attrs, dict) and attrs.get("layout_role") == "caption_candidate"


def _unit_metrics(bbox: list[float], profile: dict[str, Any]) -> dict[str, float]:
    width = _width(bbox)
    body_width = float(profile["body_width"])
    left_inset = float(bbox[0]) - float(profile["body_left"])
    right_inset = float(profile["body_right"]) - float(bbox[2])
    return {
        "width": width,
        "body_width": body_width,
        "width_ratio": round(width / body_width, 4) if body_width > 0 else 0.0,
        "left_inset": left_inset,
        "right_inset": right_inset,
    }


def _display_signals(bbox: list[float], profile: dict[str, float]) -> list[str]:
    signals: list[str] = []
    body_width = profile["body_width"]
    left_inset = float(bbox[0]) - profile["body_left"]
    right_inset = profile["body_right"] - float(bbox[2])
    if _width(bbox) <= body_width * 0.72:
        signals.append("narrower_than_body_lane")
    if left_inset >= body_width * 0.12 and right_inset >= body_width * 0.08:
        signals.append("inset_from_body_lane")
    elif (
        _width(bbox) <= body_width * 0.96
        and left_inset >= body_width * 0.05
        and right_inset >= body_width * -0.03
    ):
        signals.append("left_inset_set_off_text")
    elif (
        body_width * 0.94 <= _width(bbox) <= body_width * 0.98
        and left_inset >= max(24.0, body_width * 0.03)
        and right_inset >= body_width * -0.03
        and _height(bbox) >= 80.0
    ):
        signals.append("slightly_inset_tall_block")
    return signals


def _is_display_candidate(signals: list[str]) -> bool:
    return (
        signals == ["narrower_than_body_lane", "inset_from_body_lane"]
        or signals == ["left_inset_set_off_text"]
        or signals == ["slightly_inset_tall_block"]
    )


def _short_line_group(unit: dict[str, Any], page_sizes: dict[int, dict[str, float]]) -> str | None:
    attrs = unit.get("attrs") if isinstance(unit.get("attrs"), dict) else {}
    merge_reasons = (
        attrs.get("merge_reasons") if isinstance(attrs.get("merge_reasons"), list) else []
    )
    if "same_page_short_line_group" not in merge_reasons:
        return None
    bboxes = _line_bboxes(unit)
    if len(bboxes) < 2:
        return None
    page_width = float(page_sizes.get(int(unit["page"]), {}).get("width") or 0.0)
    if page_width <= 0:
        return None
    if median(_width(bbox) for bbox in bboxes) > page_width * 0.62:
        return None
    tolerance = max(24.0, page_width * 0.03)
    if _spread([bbox[2] for bbox in bboxes]) <= tolerance:
        return "right"
    if _spread([bbox[0] for bbox in bboxes]) <= tolerance:
        return "left"
    centers = [(bbox[0] + bbox[2]) / 2 for bbox in bboxes]
    if _spread(centers) <= tolerance:
        return "center"
    return None


def _line_bboxes(unit: dict[str, Any]) -> list[list[float]]:
    bboxes = [
        [float(value) for value in span["bbox"]]
        for span in unit.get("spans") or []
        if isinstance(span, dict)
        and _span_page(span, int(unit["page"])) == int(unit["page"])
        and _valid_bbox(span.get("bbox"))
    ]
    if bboxes:
        return bboxes
    bbox = unit.get("bbox")
    return [[float(value) for value in bbox]] if _valid_bbox(bbox) else []


def _spread(values: list[float]) -> float:
    if not values:
        return 0.0
    return max(values) - min(values)


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )


def _width(bbox: list[float]) -> float:
    return float(bbox[2]) - float(bbox[0])


def _height(bbox: list[float]) -> float:
    return float(bbox[3]) - float(bbox[1])
