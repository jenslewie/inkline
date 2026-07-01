from __future__ import annotations

from copy import deepcopy
from statistics import median
from typing import Any


def classify_text_units_by_layout(
    units: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    page_profiles = _page_profiles(units, pages)
    classified = deepcopy(units)
    for unit in classified:
        if unit.get("unit_type") != "paragraph":
            continue
        bbox = unit.get("bbox")
        if not _valid_bbox(bbox):
            continue
        profile = page_profiles.get(int(unit["page"]))
        if not profile:
            continue
        signals = _display_signals(bbox, profile)
        if _is_display_candidate(signals):
            unit["unit_type"] = "display_block"
            attrs = unit.setdefault("attrs", {})
            attrs["layout_role"] = "set_off"
            attrs["layout_classification"] = {
                "method": "page_body_lane_geometry_v1",
                "signals": signals,
            }
    return classified


def _page_profiles(
    units: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> dict[int, dict[str, float]]:
    page_sizes = {
        int(page["page"]): {
            "width": float(page["width"]),
            "height": float(page["height"]),
        }
        for page in pages
    }
    grouped: dict[int, list[list[float]]] = {}
    for unit in units:
        if unit.get("unit_type") != "paragraph":
            continue
        bbox = unit.get("bbox")
        if not _valid_bbox(bbox):
            continue
        grouped.setdefault(int(unit["page"]), []).append([float(value) for value in bbox])

    profiles: dict[int, dict[str, float]] = {}
    for page, bboxes in grouped.items():
        if len(bboxes) < 3:
            continue
        left = median(bbox[0] for bbox in bboxes)
        right = median(bbox[2] for bbox in bboxes)
        width = median(_width(bbox) for bbox in bboxes)
        if width <= 0:
            continue
        size = page_sizes.get(page, {})
        profiles[page] = {
            "body_left": float(left),
            "body_right": float(right),
            "body_width": float(width),
            "page_width": float(size.get("width") or 0.0),
            "page_height": float(size.get("height") or 0.0),
        }
    return profiles


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
