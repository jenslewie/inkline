from __future__ import annotations

from collections import Counter
from copy import deepcopy
from statistics import median
from typing import Any

MIN_BODY_WIDTH_RATIO = 0.2
MAX_BODY_WIDTH_RATIO = 0.92
MAX_REFERENCE_WIDTH_SPREAD_RATIO = 2.5


def audit_text_unit_layout(
    units: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> dict[str, Any]:
    page_profiles, profile_quality = _page_profiles(units, pages)
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
        record = _unit_record(unit, page_profiles)
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
    for page, bboxes in grouped.items():
        if len(bboxes) < 3:
            profile_quality["rejected_too_few_references"] += 1
            continue
        left = median(bbox[0] for bbox in bboxes)
        right = median(bbox[2] for bbox in bboxes)
        width = median(_width(bbox) for bbox in bboxes)
        if width <= 0:
            profile_quality["rejected_invalid_width"] += 1
            continue
        size = page_sizes.get(page, {})
        page_width = float(size.get("width") or 0.0)
        if _has_unstable_widths(bboxes):
            profile_quality["rejected_unstable_widths"] += 1
            continue
        if _has_extreme_body_width(width, page_width):
            profile_quality["rejected_extreme_body_width"] += 1
            continue
        profiles[page] = {
            "body_left": float(left),
            "body_right": float(right),
            "body_width": float(width),
            "page_width": page_width,
            "page_height": float(size.get("height") or 0.0),
            "reference_unit_count": len(bboxes),
        }
        profile_quality["accepted"] += 1
    return profiles, _profile_quality_summary(profile_quality)


def _profile_quality_summary(profile_quality: Counter[str]) -> dict[str, int]:
    keys = (
        "accepted",
        "rejected_too_few_references",
        "rejected_invalid_width",
        "rejected_unstable_widths",
        "rejected_extreme_body_width",
    )
    return {key: int(profile_quality.get(key, 0)) for key in keys}


def _has_unstable_widths(bboxes: list[list[float]]) -> bool:
    widths = [_width(bbox) for bbox in bboxes if _width(bbox) > 0]
    if not widths:
        return True
    return max(widths) / min(widths) > MAX_REFERENCE_WIDTH_SPREAD_RATIO


def _has_extreme_body_width(body_width: float, page_width: float) -> bool:
    if page_width <= 0:
        return False
    ratio = body_width / page_width
    return ratio < MIN_BODY_WIDTH_RATIO or ratio > MAX_BODY_WIDTH_RATIO


def _page_profile_records(page_profiles: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "page": page,
            "page_width": profile["page_width"],
            "page_height": profile["page_height"],
            "body_left": profile["body_left"],
            "body_right": profile["body_right"],
            "body_width": profile["body_width"],
            "reference_unit_count": profile["reference_unit_count"],
        }
        for page, profile in sorted(page_profiles.items())
    ]


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
    unit: dict[str, Any], page_profiles: dict[int, dict[str, Any]]
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
    return signals


def _is_display_candidate(signals: list[str]) -> bool:
    return signals == ["narrower_than_body_lane", "inset_from_body_lane"]


def _valid_bbox(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(
        isinstance(number, int | float) for number in value
    )


def _width(bbox: list[float]) -> float:
    return float(bbox[2]) - float(bbox[0])
