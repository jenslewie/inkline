from __future__ import annotations

from collections import Counter
from itertools import pairwise
from statistics import median
from typing import Any, TypeGuard, cast

from inkline.canonical.observed.index import ObservedIndex, build_observed_index
from inkline.canonical.page_layout.contract import (
    PAGE_LAYOUT_ANALYSIS_SCHEMA_NAME,
    PAGE_LAYOUT_ANALYSIS_SCHEMA_VERSION,
)
from inkline.canonical.page_layout.validation import validate_page_layout_analysis
from inkline.canonical.schema import ValidationError

MIN_BODY_WIDTH_RATIO = 0.2
MAX_BODY_WIDTH_RATIO = 0.92
MIN_LOCAL_PROFILE_REFERENCES = 2
MIN_DOMINANT_REFERENCE_RATIO = 0.7
MAX_DOMINANT_WIDTH_SPREAD_RATIO = 1.5
VISUAL_KINDS = {"image_region", "table_region"}
TEXT_KINDS = {"text_region", "footnote_region"}
CONTENT_KINDS = VISUAL_KINDS | TEXT_KINDS


def build_page_layout_analysis(
    document: dict[str, Any], observed_index: ObservedIndex | None = None
) -> dict[str, Any]:
    """Build reusable layout evidence without constructing logical text units."""

    index = observed_index or build_observed_index(document)
    doc_id = str(document.get("metadata", {}).get("doc_id") or "")
    if index.doc_id != doc_id:
        raise ValidationError(
            f"ObservedIndex doc_id {index.doc_id!r} does not match document doc_id {doc_id!r}"
        )
    pages = [cast(dict[str, Any], index.pages_by_number[page]) for page in index.page_numbers]
    observations = [
        cast(dict[str, Any], observation) for observation in index.observations_by_id.values()
    ]
    page_sizes = _page_sizes(pages)
    fragments = _layout_fragments(observations, page_sizes)
    page_profile_map, profile_quality = _page_layout_profile_map(fragments, page_sizes)
    book_profile = _book_layout_profile(page_profile_map, fragments)
    observations_by_page = _observations_by_page(observations)
    records = [
        _page_record(
            page,
            page_sizes[page],
            page_profile_map.get(page),
            book_profile,
            fragments,
            observations_by_page.get(page, []),
        )
        for page in index.page_numbers
    ]
    missing_reasons = Counter(
        record["coverage"]["profile_status"] for record in records if record["body_lane"] is None
    )
    analysis = {
        "metadata": {
            "schema_name": PAGE_LAYOUT_ANALYSIS_SCHEMA_NAME,
            "schema_version": PAGE_LAYOUT_ANALYSIS_SCHEMA_VERSION,
            "doc_id": index.doc_id,
        },
        "book_layout_profile": book_profile,
        "pages": records,
        "audit": {
            "total_pages": len(records),
            "pages_with_profiles": sum(record["body_lane"] is not None for record in records),
            "pages_without_profiles": sum(record["body_lane"] is None for record in records),
            "pages_without_profiles_by_reason": dict(sorted(missing_reasons.items())),
            "profile_quality": _profile_quality_summary(profile_quality),
        },
    }
    validate_page_layout_analysis(analysis)
    return analysis


def _layout_fragments(
    observations: list[dict[str, Any]], page_sizes: dict[int, dict[str, float]]
) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    title_cluster_pages = _title_cluster_pages(observations, page_sizes)
    for observation in sorted(observations, key=_observation_order):
        if observation.get("role_hint") != "body_text":
            continue
        page = int(observation["page"])
        if page in title_cluster_pages:
            continue
        bboxes = _observation_bboxes(observation)
        attrs_value = observation.get("attrs")
        attrs = attrs_value if isinstance(attrs_value, dict) else {}
        metrics = attrs.get("text_line_metrics")
        for bbox in bboxes:
            fragments.append(
                {
                    "page": page,
                    "bbox": bbox,
                    "text_line_metrics": metrics if isinstance(metrics, dict) else None,
                }
            )
    return fragments


def _title_cluster_pages(
    observations: list[dict[str, Any]], page_sizes: dict[int, dict[str, float]]
) -> set[int]:
    grouped = _observations_by_page(observations)
    return {
        page
        for page, page_observations in grouped.items()
        if _is_title_cluster_page(page_observations, page_sizes.get(page, {}))
    }


def _is_title_cluster_page(observations: list[dict[str, Any]], page_size: dict[str, float]) -> bool:
    if any(observation.get("kind") in VISUAL_KINDS for observation in observations):
        return False
    text = [
        observation
        for observation in observations
        if observation.get("kind") == "text_region"
        and observation.get("role_hint") in {"title_text", "body_text"}
        and _valid_bbox(observation.get("bbox"))
    ]
    title_bboxes = [
        observation["bbox"] for observation in text if observation.get("role_hint") == "title_text"
    ]
    body_bboxes = [
        observation["bbox"] for observation in text if observation.get("role_hint") == "body_text"
    ]
    width = float(page_size.get("width") or 0.0)
    height = float(page_size.get("height") or 0.0)
    if not 2 <= len(text) <= 4 or not title_bboxes or not body_bboxes or width <= 0 or height <= 0:
        return False
    page_center = width / 2.0
    min_title_top = min(float(bbox[1]) for bbox in title_bboxes)
    max_title_bottom = max(float(bbox[3]) for bbox in title_bboxes)
    vertical_margin = height * 0.12
    return all(
        _width(bbox) <= width * 0.55
        and abs((float(bbox[0]) + float(bbox[2])) / 2.0 - page_center) <= width * 0.12
        and float(bbox[1]) >= min_title_top - vertical_margin
        and float(bbox[3]) <= max_title_bottom + vertical_margin
        for bbox in body_bboxes
    )


def _observation_order(observation: dict[str, Any]) -> tuple[int, int, float, float, str]:
    attrs_value = observation.get("attrs")
    attrs = attrs_value if isinstance(attrs_value, dict) else {}
    reading_order = attrs.get("reading_order")
    bbox = observation.get("bbox")
    return (
        int(observation["page"]),
        int(reading_order) if isinstance(reading_order, int) else 999999,
        float(bbox[1]) if _valid_bbox(bbox) else float("inf"),
        float(bbox[0]) if _valid_bbox(bbox) else float("inf"),
        str(observation["observation_id"]),
    )


def _observation_bboxes(observation: dict[str, Any]) -> list[list[float]]:
    page = int(observation["page"])
    spans = observation.get("spans")
    span_bboxes = [
        [float(value) for value in span["bbox"]]
        for span in spans or []
        if isinstance(span, dict)
        and (not isinstance(span.get("page"), int) or int(span["page"]) == page)
        and _valid_bbox(span.get("bbox"))
    ]
    if span_bboxes:
        return span_bboxes
    bbox = observation.get("bbox")
    return [[float(value) for value in bbox]] if _valid_bbox(bbox) else []


def _page_layout_profile_map(
    fragments: list[dict[str, Any]], page_sizes: dict[int, dict[str, float]]
) -> tuple[dict[int, dict[str, Any]], Counter[str]]:
    grouped: dict[int, list[list[float]]] = {}
    for fragment in fragments:
        grouped.setdefault(int(fragment["page"]), []).append(fragment["bbox"])
    profiles: dict[int, dict[str, Any]] = {}
    deferred: dict[int, tuple[list[list[float]], str]] = {}
    quality: Counter[str] = Counter()
    for page, bboxes in grouped.items():
        profile, reason = _local_page_profile(page, bboxes, page_sizes)
        if profile is not None:
            profiles[page] = profile
            quality["accepted"] += 1
        else:
            deferred[page] = (bboxes, reason)
    for page, (bboxes, reason) in deferred.items():
        source_page = _nearest_profile_page(page, profiles)
        if source_page is None:
            quality[
                "rejected_no_stable_profile" if reason == "needs_fallback" else f"rejected_{reason}"
            ] += 1
            continue
        source = profiles[source_page]
        size = page_sizes.get(page, {})
        profiles[page] = {
            "body_left": source["body_left"],
            "body_right": source["body_right"],
            "body_width": source["body_width"],
            "page_width": float(size.get("width") or source["page_width"]),
            "page_height": float(size.get("height") or source["page_height"]),
            "reference_fragment_count": len(bboxes),
            "profile_source": "nearest_page",
            "profile_source_page": source_page,
        }
        quality["filled_from_nearest_profile"] += 1
    return profiles, quality


def _local_page_profile(
    page: int,
    bboxes: list[list[float]],
    page_sizes: dict[int, dict[str, float]],
) -> tuple[dict[str, Any] | None, str]:
    dominant = _dominant_reference_bboxes(bboxes)
    if not dominant:
        return None, "needs_fallback"
    if _has_unstable_dominant_widths(dominant):
        return None, "unstable_widths"
    left = median(bbox[0] for bbox in dominant)
    right = median(bbox[2] for bbox in dominant)
    width = median(_width(bbox) for bbox in dominant)
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
        "reference_fragment_count": len(dominant),
    }, ""


def _dominant_reference_bboxes(bboxes: list[list[float]]) -> list[list[float]]:
    valid = [bbox for bbox in bboxes if _width(bbox) > 0]
    if len(valid) < MIN_LOCAL_PROFILE_REFERENCES:
        return []
    threshold = max(_width(bbox) for bbox in valid) * MIN_DOMINANT_REFERENCE_RATIO
    dominant = [bbox for bbox in valid if _width(bbox) >= threshold]
    return dominant if len(dominant) >= MIN_LOCAL_PROFILE_REFERENCES else []


def _has_unstable_dominant_widths(bboxes: list[list[float]]) -> bool:
    widths = [_width(bbox) for bbox in bboxes if _width(bbox) > 0]
    return not widths or max(widths) / min(widths) > MAX_DOMINANT_WIDTH_SPREAD_RATIO


def _has_extreme_body_width(body_width: float, page_width: float) -> bool:
    if page_width <= 0:
        return False
    ratio = body_width / page_width
    return ratio < MIN_BODY_WIDTH_RATIO or ratio > MAX_BODY_WIDTH_RATIO


def _nearest_profile_page(page: int, profiles: dict[int, dict[str, Any]]) -> int | None:
    if not profiles:
        return None
    return min(profiles, key=lambda candidate: (abs(candidate - page), candidate))


def _book_layout_profile(
    profiles: dict[int, dict[str, Any]], fragments: list[dict[str, Any]]
) -> dict[str, Any]:
    local_profiles = [profile for profile in profiles.values() if not profile.get("profile_source")]
    normal_gaps = _normal_gaps(fragments, profiles)
    normal_gap = _median_or_none(normal_gaps)
    return {
        "profile_scope": "book",
        "source_page_count": len(local_profiles),
        "body_width": _median_or_none([float(profile["body_width"]) for profile in local_profiles]),
        "indent_unit": _median_or_none(_indent_units(fragments)),
        "line_height": _median_or_none([_height(fragment["bbox"]) for fragment in fragments]),
        "normal_gap_y": normal_gap,
        "display_gap_y": _median_or_none(_display_gaps(fragments, profiles, normal_gap)),
    }


def _indent_units(fragments: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    seen_metrics: set[int] = set()
    for fragment in fragments:
        metrics = fragment.get("text_line_metrics")
        if not isinstance(metrics, dict) or id(metrics) in seen_metrics:
            continue
        seen_metrics.add(id(metrics))
        indent = _float_or_none(metrics.get("first_line_indent"))
        char_width = _float_or_none(metrics.get("char_width"))
        if indent is None or indent <= 0:
            continue
        if char_width is not None and indent < char_width * 0.75:
            continue
        values.append(indent)
    return values


def _normal_gaps(
    fragments: list[dict[str, Any]], profiles: dict[int, dict[str, Any]]
) -> list[float]:
    gaps: list[float] = []
    for bboxes in _group_profile_bboxes(fragments, profiles, strict=True).values():
        for previous, current in pairwise(sorted(bboxes, key=lambda bbox: (bbox[1], bbox[0]))):
            gap = float(current[1]) - float(previous[3])
            if 0 <= gap <= max(12.0, _height(previous) * 0.45):
                gaps.append(gap)
    if not gaps:
        return []
    positive = [gap for gap in gaps if gap > 0]
    if not positive:
        return gaps
    anchor = min(positive)
    threshold = max(anchor * 1.8, anchor + 4.0)
    return [gap for gap in gaps if gap <= threshold]


def _display_gaps(
    fragments: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    normal_gap: float | None,
) -> list[float]:
    if normal_gap is None:
        return []
    threshold = max(normal_gap * 2.5, normal_gap + 18.0)
    gaps: list[float] = []
    for bboxes in _group_profile_bboxes(fragments, profiles, strict=False).values():
        for previous, current in pairwise(sorted(bboxes, key=lambda bbox: (bbox[1], bbox[0]))):
            gap = float(current[1]) - float(previous[3])
            if gap >= threshold:
                gaps.append(gap)
    return gaps


def _group_profile_bboxes(
    fragments: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    *,
    strict: bool,
) -> dict[int, list[list[float]]]:
    grouped: dict[int, list[list[float]]] = {}
    for fragment in fragments:
        page = int(fragment["page"])
        profile = profiles.get(page)
        if not profile or profile.get("profile_source"):
            continue
        bbox = fragment["bbox"]
        if _is_body_like_bbox(bbox, profile, strict=strict):
            grouped.setdefault(page, []).append(bbox)
    return grouped


def _is_body_like_bbox(bbox: list[float], profile: dict[str, Any], *, strict: bool) -> bool:
    body_width = float(profile["body_width"])
    if body_width <= 0:
        return False
    left_delta = abs(float(bbox[0]) - float(profile["body_left"]))
    right_delta = abs(float(bbox[2]) - float(profile["body_right"]))
    if strict:
        return (
            _width(bbox) >= body_width * 0.96
            and left_delta <= max(12.0, body_width * 0.015)
            and right_delta <= max(16.0, body_width * 0.02)
        )
    return (
        _width(bbox) >= body_width * 0.70
        and left_delta <= max(24.0, body_width * 0.06)
        and right_delta <= max(32.0, body_width * 0.08)
    )


def _page_record(
    page: int,
    page_size: dict[str, float],
    profile: dict[str, Any] | None,
    book_profile: dict[str, Any],
    fragments: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    body_lane = _body_lane_record(profile, book_profile) if profile is not None else None
    return {
        "page": page,
        "page_size": page_size,
        "body_lane": body_lane,
        "coverage": {
            "profile_status": "profiled"
            if body_lane is not None
            else _missing_profile_reason(page, page_size, fragments, observations)
        },
        "role_signals": _role_signals(page_size, observations),
    }


def _body_lane_record(profile: dict[str, Any], book_profile: dict[str, Any]) -> dict[str, Any]:
    book_body_width = book_profile.get("body_width")
    body_width_delta = (
        round(float(profile["body_width"]) - float(book_body_width), 4)
        if isinstance(book_body_width, int | float)
        else None
    )
    record = {
        "profile_scope": "page",
        "profile_source": str(profile.get("profile_source") or "local"),
        "page_width": profile["page_width"],
        "page_height": profile["page_height"],
        "body_left": profile["body_left"],
        "body_right": profile["body_right"],
        "body_width": profile["body_width"],
        "book_body_width": book_body_width,
        "body_width_delta": body_width_delta,
        "indent_unit": book_profile.get("indent_unit"),
        "line_height": book_profile.get("line_height"),
        "normal_gap_y": book_profile.get("normal_gap_y"),
        "display_gap_y": book_profile.get("display_gap_y"),
        "reference_fragment_count": profile["reference_fragment_count"],
    }
    if profile.get("profile_source"):
        record["profile_source_page"] = profile["profile_source_page"]
    return record


def _missing_profile_reason(
    page: int,
    page_size: dict[str, float],
    fragments: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> str:
    if _is_title_cluster_page(observations, page_size):
        return "title_cluster"
    page_fragments = [fragment for fragment in fragments if int(fragment["page"]) == page]
    body_observations = [
        observation for observation in observations if observation.get("role_hint") == "body_text"
    ]
    if page_fragments:
        return "body_text_without_stable_profile"
    if body_observations:
        return "body_text_without_bbox"
    role_hints = Counter(str(observation.get("role_hint") or "") for observation in observations)
    kinds = Counter(str(observation.get("kind") or "") for observation in observations)
    if role_hints.get("title_text") and not role_hints.get("body_text"):
        return "title_only"
    if kinds.get("image_region") or kinds.get("table_region"):
        return "visual_with_text" if kinds.get("text_region") else "visual_only"
    return "empty" if not observations else "non_body_content"


def _role_signals(
    page_size: dict[str, float], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    width = page_size["width"]
    height = page_size["height"]
    page_area = width * height
    content = [
        observation
        for observation in observations
        if observation.get("kind") in CONTENT_KINDS and _valid_bbox(observation.get("bbox"))
    ]
    text = [observation for observation in content if observation.get("kind") in TEXT_KINDS]
    visuals = [observation for observation in content if observation.get("kind") in VISUAL_KINDS]
    return {
        "kind_counts": dict(
            sorted(Counter(str(observation.get("kind") or "") for observation in content).items())
        ),
        "role_hint_counts": dict(
            sorted(
                Counter(str(observation.get("role_hint") or "") for observation in content).items()
            )
        ),
        "content_count": len(content),
        "text_count": len(text),
        "visual_count": len(visuals),
        "body_zone_footnote_count": sum(
            observation.get("role_hint") == "footnote_text"
            and float(observation["bbox"][1]) < height * 0.7
            for observation in text
        ),
        "visual_area_ratio": _area_ratio(visuals, page_area),
        "text_area_ratio": _area_ratio(text, page_area),
        "centered_text_ratio": _centered_text_ratio(text, width),
        "tall_text_count": sum(_is_tall_text_region(observation) for observation in text),
    }


def _observations_by_page(
    observations: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for observation in observations:
        grouped.setdefault(int(observation["page"]), []).append(observation)
    return grouped


def _page_sizes(pages: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    return {
        int(page["page"]): {"width": float(page["width"]), "height": float(page["height"])}
        for page in pages
    }


def _profile_quality_summary(quality: Counter[str]) -> dict[str, int]:
    return {
        key: int(quality.get(key, 0))
        for key in (
            "accepted",
            "filled_from_nearest_profile",
            "rejected_no_stable_profile",
            "rejected_invalid_width",
            "rejected_unstable_widths",
            "rejected_extreme_body_width",
        )
    }


def _area_ratio(observations: list[dict[str, Any]], page_area: float) -> float:
    if page_area <= 0:
        return 0.0
    area = sum(_bbox_area(observation["bbox"]) for observation in observations)
    return round(min(area / page_area, 1.0), 4)


def _centered_text_ratio(observations: list[dict[str, Any]], page_width: float) -> float:
    if not observations or page_width <= 0:
        return 0.0
    centered = sum(
        abs((float(observation["bbox"][0]) + float(observation["bbox"][2])) / 2 - page_width / 2)
        <= page_width * 0.18
        for observation in observations
    )
    return centered / len(observations)


def _bbox_area(bbox: list[float]) -> float:
    return max(_width(bbox), 0.0) * max(_height(bbox), 0.0)


def _is_tall_text_region(observation: dict[str, Any]) -> bool:
    bbox = observation["bbox"]
    width = _width(bbox)
    return width > 0 and _height(bbox) >= width * 2


def _median_or_none(values: list[float]) -> float | None:
    values = [value for value in values if value > 0]
    return float(median(values)) if values else None


def _float_or_none(value: Any) -> float | None:
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


def _width(bbox: list[float]) -> float:
    return float(bbox[2]) - float(bbox[0])


def _height(bbox: list[float]) -> float:
    return float(bbox[3]) - float(bbox[1])
