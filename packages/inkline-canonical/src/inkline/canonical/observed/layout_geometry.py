from __future__ import annotations

from typing import Any, TypeGuard


def page_layout_profile_map(
    page_layout: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    """Return legacy-compatible page profiles from layout analysis."""

    profiles: dict[int, dict[str, Any]] = {}
    for page_record in page_layout["pages"]:
        body_lane = page_record.get("body_lane")
        if not isinstance(body_lane, dict):
            continue
        profile = dict(body_lane)
        profile.pop("profile_scope", None)
        profile["reference_unit_count"] = int(profile.pop("reference_fragment_count"))
        if profile.get("profile_source") == "local":
            profile.pop("profile_source")
        profiles[int(page_record["page"])] = profile
    return profiles


def display_gap_threshold(book_profile: dict[str, Any]) -> float:
    normal_gap = _float_or_none(book_profile.get("normal_gap_y"))
    if normal_gap is not None:
        return max(normal_gap * 2.5, normal_gap + 18.0)
    line_height = _float_or_none(book_profile.get("line_height"))
    if line_height is not None:
        return max(24.0, line_height * 0.45)
    return 24.0


def display_signals(
    bbox: list[float],
    profile: dict[str, Any],
    book_profile: dict[str, Any],
    context: dict[str, float | bool],
) -> list[str]:
    signals: list[str] = []
    body_width = float(profile["body_width"])
    body_left = float(profile["body_left"])
    body_right = float(profile["body_right"])
    width = _width(bbox)
    left_inset = float(bbox[0]) - body_left
    right_inset = body_right - float(bbox[2])
    indent_unit = _profile_indent_unit(book_profile, body_width)
    if width <= body_width * 0.72:
        signals.append("narrower_than_body_lane")
    if left_inset >= body_width * 0.12 and right_inset >= body_width * 0.08:
        signals.append("inset_from_body_lane")
    elif (
        width <= body_width * 0.96
        and left_inset >= body_width * 0.05
        and right_inset >= body_width * -0.03
    ):
        signals.append("left_inset_set_off_text")
    elif (
        body_width * 0.94 <= width <= body_width * 0.98
        and left_inset >= max(24.0, body_width * 0.03)
        and right_inset >= body_width * -0.03
        and _height(bbox) >= 80.0
    ):
        signals.append("slightly_inset_tall_block")
    if _book_indent_set_off(bbox, body_width, left_inset, right_inset, indent_unit):
        signals.append("book_indent_set_off_text")
    if _right_aligned_attribution(bbox, body_left, body_right, body_width, indent_unit):
        signals.append("right_aligned_attribution")
    if context.get("display_gap_before") is True:
        signals.append("display_gap_before")
    if context.get("display_gap_after") is True:
        signals.append("display_gap_after")
    return signals


def is_display_candidate(signals: list[str]) -> bool:
    has_gap_before = "display_gap_before" in signals
    has_gap_after = "display_gap_after" in signals
    has_any_display_gap = has_gap_before or has_gap_after
    has_display_gap_pair = has_gap_before and has_gap_after
    strong_inset = "narrower_than_body_lane" in signals and "inset_from_body_lane" in signals
    right_aligned = "right_aligned_attribution" in signals
    set_off_prose = any(
        signal in signals
        for signal in (
            "left_inset_set_off_text",
            "slightly_inset_tall_block",
            "book_indent_set_off_text",
        )
    )
    return (
        (right_aligned and has_any_display_gap)
        or (strong_inset and has_any_display_gap)
        or (set_off_prose and has_display_gap_pair)
    )


def valid_bbox(value: Any) -> TypeGuard[list[float]]:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )


def _profile_indent_unit(book_profile: dict[str, Any], body_width: float) -> float:
    indent_unit = _float_or_none(book_profile.get("indent_unit"))
    if indent_unit is not None and indent_unit > 0:
        return indent_unit
    return max(24.0, body_width * 0.04)


def _book_indent_set_off(
    bbox: list[float],
    body_width: float,
    left_inset: float,
    right_inset: float,
    indent_unit: float,
) -> bool:
    return (
        _width(bbox) <= body_width - indent_unit * 0.5
        and left_inset >= max(12.0, indent_unit * 0.85)
        and right_inset >= -indent_unit
    )


def _right_aligned_attribution(
    bbox: list[float],
    body_left: float,
    body_right: float,
    body_width: float,
    indent_unit: float,
) -> bool:
    near_right = abs(float(bbox[2]) - body_right) <= max(24.0, indent_unit * 1.5)
    compact = _width(bbox) <= body_width * 0.55
    right_lane = float(bbox[0]) >= body_left + body_width * 0.40
    return near_right and compact and right_lane


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _width(bbox: list[float]) -> float:
    return float(bbox[2]) - float(bbox[0])


def _height(bbox: list[float]) -> float:
    return float(bbox[3]) - float(bbox[1])
