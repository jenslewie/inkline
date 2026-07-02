from __future__ import annotations

from collections import Counter
from copy import deepcopy
from statistics import median
from typing import Any

MIN_BODY_WIDTH_RATIO = 0.2
MAX_BODY_WIDTH_RATIO = 0.92
MIN_LOCAL_PROFILE_REFERENCES = 2
MIN_DOMINANT_REFERENCE_RATIO = 0.65
MAX_DOMINANT_WIDTH_SPREAD_RATIO = 1.5


def audit_text_unit_layout(
    units: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> dict[str, Any]:
    page_profiles, profile_quality = _page_profiles(units, pages)
    page_sizes = _page_sizes(pages)
    unit_records: list[dict[str, Any]] = []
    summary = {
        "pages_with_profiles": len(page_profiles),
        "paragraph_units": 0,
        "classified_display_blocks": 0,
        "skipped_no_bbox": 0,
        "skipped_no_profile": 0,
    }
    for unit in units:
        if unit.get("unit_type") != "paragraph":
            continue
        summary["paragraph_units"] += 1
        record = _unit_record(unit, page_profiles, page_sizes)
        unit_records.append(record)
        if record["decision"] == "display_block":
            summary["classified_display_blocks"] += 1
        elif record["decision"] == "skipped_no_bbox":
            summary["skipped_no_bbox"] += 1
        elif record["decision"] == "skipped_no_profile":
            summary["skipped_no_profile"] += 1
    return {
        "summary": summary,
        "profile_quality": profile_quality,
        "page_profiles": _page_profile_records(page_profiles),
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


def _page_profiles(
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
    deferred_pages: dict[int, list[list[float]]] = {}
    for page, bboxes in grouped.items():
        profile, rejection_reason = _local_page_profile(page, bboxes, page_sizes)
        if profile:
            profiles[page] = profile
            profile_quality["accepted"] += 1
            continue
        if rejection_reason == "needs_fallback":
            deferred_pages[page] = bboxes
            continue
        profile_quality[f"rejected_{rejection_reason}"] += 1

    for page, bboxes in deferred_pages.items():
        source_page = _nearest_profile_page(page, profiles)
        if source_page is None:
            profile_quality["rejected_no_stable_profile"] += 1
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
    widths = sorted((_width(bbox) for bbox in valid_bboxes), reverse=True)
    anchor_count = max(MIN_LOCAL_PROFILE_REFERENCES, len(widths) // 2)
    anchor = median(widths[:anchor_count])
    threshold = anchor * MIN_DOMINANT_REFERENCE_RATIO
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


def _page_profile_records(page_profiles: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for page, profile in sorted(page_profiles.items()):
        record = {
            "page": page,
            "page_width": profile["page_width"],
            "page_height": profile["page_height"],
            "body_left": profile["body_left"],
            "body_right": profile["body_right"],
            "body_width": profile["body_width"],
            "reference_unit_count": profile["reference_unit_count"],
        }
        if profile.get("profile_source"):
            record["profile_source"] = profile["profile_source"]
            record["profile_source_page"] = profile["profile_source_page"]
        records.append(record)
    return records


def _nearest_profile_page(page: int, page_profiles: dict[int, dict[str, Any]]) -> int | None:
    if not page_profiles:
        return None
    return min(page_profiles, key=lambda candidate: (abs(candidate - page), candidate))


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
    page_profiles: dict[int, dict[str, Any]],
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
    short_line_group = _short_line_group(unit, page_sizes)
    if short_line_group:
        width = _width(bbox)
        return {
            **base,
            "classified_type": "display_block",
            "width": width,
            "body_width": None,
            "width_ratio": None,
            "left_inset": None,
            "right_inset": None,
            "signals": [f"{short_line_group}_aligned_short_line_group"],
            "layout_form": "short_line_group",
            "alignment": short_line_group,
            "decision": "display_block",
        }
    profile = page_profiles.get(int(unit["page"]))
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
    signals = _display_signals(bbox, profile)
    decision = "display_block" if _is_display_candidate(signals) else "paragraph"
    return {
        **base,
        "classified_type": decision,
        **metrics,
        "signals": signals,
        "decision": decision,
    }


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
    return signals


def _is_display_candidate(signals: list[str]) -> bool:
    return signals == ["narrower_than_body_lane", "inset_from_body_lane"] or signals == [
        "left_inset_set_off_text"
    ]


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
