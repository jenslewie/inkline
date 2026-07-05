from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from inkline.canonical.observed import validate_observed_document

TEXT_UNIT_TYPES = {"heading", "paragraph", "display_block", "list_item", "footnote"}


def build_text_units(document: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    validate_observed_document(document)
    units: list[dict[str, Any]] = []
    ignored_counts: Counter[str] = Counter()
    page_sizes = _page_sizes(document["pages"])
    visual_bboxes = _visual_bboxes(document["observations"])
    image_bboxes = _region_bboxes(document["observations"], {"image_region"})
    table_bboxes = _region_bboxes(document["observations"], {"table_region"})
    ordered_observations = _ordered_observations(document["observations"])
    caption_title_ids = _visual_caption_title_ids(
        ordered_observations, image_bboxes, page_sizes
    )

    for observation in ordered_observations:
        layout_role = None
        unit_type = _unit_type(observation, caption_title_ids)
        if observation["observation_id"] in caption_title_ids:
            layout_role = "caption_candidate"
        if unit_type is None:
            ignored_counts[str(observation["kind"])] += 1
            continue
        merge_reason = (
            _merge_reason(units[-1], observation, unit_type, page_sizes) if units else None
        )
        if merge_reason:
            _merge_observation(units[-1], observation, merge_reason)
            continue
        units.append(_unit_from_observation(observation, len(units) + 1, unit_type, layout_role))

    _promote_table_heading_fragments(units, page_sizes, table_bboxes)
    _merge_heading_cluster_fragments(units, page_sizes, visual_bboxes)
    _renumber_units(units)
    return units, dict(sorted(ignored_counts.items()))


def _ordered_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        observations,
        key=lambda observation: (
            int(observation["page"]),
            _reading_order(observation),
            _bbox_top(observation.get("bbox")),
            _bbox_left(observation.get("bbox")),
            str(observation["observation_id"]),
        ),
    )


def _page_sizes(pages: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    return {
        int(page["page"]): {"width": float(page["width"]), "height": float(page["height"])}
        for page in pages
        if isinstance(page.get("page"), int)
        and isinstance(page.get("width"), int | float)
        and isinstance(page.get("height"), int | float)
    }


def _visual_bboxes(observations: list[dict[str, Any]]) -> dict[int, list[list[float]]]:
    return _region_bboxes(observations, {"image_region", "table_region"})


def _region_bboxes(
    observations: list[dict[str, Any]], kinds: set[str]
) -> dict[int, list[list[float]]]:
    grouped: dict[int, list[list[float]]] = {}
    for observation in observations:
        if observation.get("kind") not in kinds:
            continue
        bbox = observation.get("bbox")
        if _valid_bbox(bbox):
            grouped.setdefault(int(observation["page"]), []).append(
                [float(value) for value in bbox]
            )
    return grouped


def _visual_caption_title_ids(
    observations: list[dict[str, Any]],
    visual_bboxes: dict[int, list[list[float]]],
    page_sizes: dict[int, dict[str, float]],
) -> set[str]:
    ids: set[str] = set()
    text_observations_by_page: dict[int, list[dict[str, Any]]] = {}
    for observation in observations:
        if observation.get("kind") in {"text_region", "footnote_region"}:
            text_observations_by_page.setdefault(int(observation["page"]), []).append(
                observation
            )

    for page, text_observations in text_observations_by_page.items():
        visuals = visual_bboxes.get(page) or []
        if not visuals:
            continue
        page_size = page_sizes.get(page, {})
        for index, observation in enumerate(text_observations[:-1]):
            if observation.get("role_hint") != "title_text":
                continue
            if _near_visual_region(observation, visual_bboxes) and len(text_observations) > 1:
                ids.add(str(observation["observation_id"]))
                continue
            following = text_observations[index + 1]
            if following.get("role_hint") != "body_text":
                continue
            if not _caption_text_group(observation, following):
                continue
            if _visual_text_group(observation, following, visuals) or (
                _visual_dominant_annotation_page(text_observations, visuals, page_size)
            ):
                ids.add(str(observation["observation_id"]))
    return ids


def _caption_text_group(title: dict[str, Any], following: dict[str, Any]) -> bool:
    title_bbox = title.get("bbox")
    following_bbox = following.get("bbox")
    if not _valid_bbox(title_bbox) or not _valid_bbox(following_bbox):
        return False
    return (
        0 <= _vertical_gap(title_bbox, following_bbox) <= max(40.0, _height(title_bbox) * 2.0)
        and (
            _horizontal_overlap_ratio(title_bbox, following_bbox) >= 0.5
            or _left_delta(title_bbox, following_bbox) <= 32.0
        )
    )


def _visual_text_group(
    title: dict[str, Any],
    following: dict[str, Any],
    visual_bboxes: list[list[float]],
) -> bool:
    group_bbox = _union_bbox(title["bbox"], following["bbox"])
    return any(_near_visual_bbox(group_bbox, visual_bbox) for visual_bbox in visual_bboxes)


def _visual_dominant_annotation_page(
    text_observations: list[dict[str, Any]],
    visual_bboxes: list[list[float]],
    page_size: dict[str, float],
) -> bool:
    if len(visual_bboxes) >= 3:
        return True
    page_width = float(page_size.get("width") or 0.0)
    if page_width <= 0:
        return False
    body_widths = [
        _width(observation["bbox"])
        for observation in text_observations
        if observation.get("role_hint") == "body_text" and _valid_bbox(observation.get("bbox"))
    ]
    return bool(body_widths) and max(body_widths) <= page_width * 0.45


def _reading_order(observation: dict[str, Any]) -> int:
    attrs = observation.get("attrs") if isinstance(observation.get("attrs"), dict) else {}
    value = attrs.get("reading_order")
    return int(value) if isinstance(value, int) else 999999


def _unit_type(observation: dict[str, Any], caption_title_ids: set[str]) -> str | None:
    role_hint = observation["role_hint"]
    if role_hint == "title_text":
        if observation["observation_id"] in caption_title_ids:
            return "paragraph"
        return "heading"
    if role_hint == "body_text":
        return "paragraph"
    if role_hint == "list_text":
        return "list_item"
    if role_hint == "reference_text":
        return "list_item"
    if observation["kind"] == "footnote_region" or role_hint == "footnote_text":
        return "footnote"
    return None


def _promote_table_heading_fragments(
    units: list[dict[str, Any]],
    page_sizes: dict[int, dict[str, float]],
    table_bboxes: dict[int, list[list[float]]],
) -> None:
    units_by_page: dict[int, list[dict[str, Any]]] = {}
    for unit in units:
        units_by_page.setdefault(int(unit["page"]), []).append(unit)

    for page, page_units in units_by_page.items():
        tables = table_bboxes.get(page) or []
        if not tables:
            continue
        table_top = min(float(bbox[1]) for bbox in tables)
        page_size = page_sizes.get(page, {})
        page_width = float(page_size.get("width") or 0.0)
        if page_width <= 0:
            continue
        for index, unit in enumerate(page_units[1:], start=1):
            previous = page_units[index - 1]
            if _table_heading_fragment(unit, previous, table_top, page_width):
                unit["unit_type"] = "heading"
                unit["attrs"]["structure_promotion"] = "table_heading"


def _table_heading_fragment(
    unit: dict[str, Any],
    previous: dict[str, Any],
    table_top: float,
    page_width: float,
) -> bool:
    bbox = unit.get("bbox")
    previous_bbox = previous.get("bbox")
    if (
        unit.get("unit_type") != "paragraph"
        or previous.get("unit_type") != "heading"
        or not _valid_bbox(bbox)
        or not _valid_bbox(previous_bbox)
    ):
        return False
    page_center = page_width / 2.0
    unit_center = (float(bbox[0]) + float(bbox[2])) / 2.0
    return (
        float(bbox[3]) <= table_top
        and 0 <= _vertical_gap(previous_bbox, bbox) <= max(40.0, _height(previous_bbox) * 2.0)
        and _width(bbox) <= page_width * 0.35
        and abs(unit_center - page_center) <= page_width * 0.12
    )


def _merge_heading_cluster_fragments(
    units: list[dict[str, Any]],
    page_sizes: dict[int, dict[str, float]],
    visual_bboxes: dict[int, list[list[float]]],
) -> None:
    units_by_page: dict[int, list[dict[str, Any]]] = {}
    for unit in units:
        units_by_page.setdefault(int(unit["page"]), []).append(unit)

    for page, page_units in units_by_page.items():
        if visual_bboxes.get(page) or not _text_only_heading_cluster_page(page_units):
            continue
        page_size = page_sizes.get(page, {})
        page_width = float(page_size.get("width") or 0.0)
        page_height = float(page_size.get("height") or 0.0)
        heading_bboxes = [
            unit["bbox"]
            for unit in page_units
            if unit.get("unit_type") == "heading" and _valid_bbox(unit.get("bbox"))
        ]
        cluster_units = [
            unit
            for unit in page_units
            if unit.get("unit_type") == "heading"
            or (
                unit.get("unit_type") == "paragraph"
                and _heading_cluster_candidate(unit, heading_bboxes, page_width, page_height)
            )
        ]
        if len(cluster_units) < 2:
            continue
        keeper = cluster_units[0]
        keeper["unit_type"] = "heading"
        keeper["attrs"]["structure_promotion"] = "heading_cluster"
        for fragment in cluster_units[1:]:
            _merge_unit_fragment(keeper, fragment, "heading_cluster")
            units.remove(fragment)


def _text_only_heading_cluster_page(page_units: list[dict[str, Any]]) -> bool:
    unit_types = {str(unit.get("unit_type")) for unit in page_units}
    return (
        2 <= len(page_units) <= 4
        and "heading" in unit_types
        and unit_types <= {"heading", "paragraph"}
    )


def _heading_cluster_candidate(
    unit: dict[str, Any],
    heading_bboxes: list[list[float]],
    page_width: float,
    page_height: float,
) -> bool:
    bbox = unit.get("bbox")
    if not _valid_bbox(bbox) or not heading_bboxes or page_width <= 0 or page_height <= 0:
        return False
    page_center = page_width / 2.0
    unit_center = (float(bbox[0]) + float(bbox[2])) / 2.0
    width = _width(bbox)
    min_heading_top = min(float(heading[1]) for heading in heading_bboxes)
    max_heading_bottom = max(float(heading[3]) for heading in heading_bboxes)
    vertical_margin = page_height * 0.12
    return (
        width <= page_width * 0.55
        and abs(unit_center - page_center) <= page_width * 0.12
        and float(bbox[1]) >= min_heading_top - vertical_margin
        and float(bbox[3]) <= max_heading_bottom + vertical_margin
    )


def _merge_unit_fragment(unit: dict[str, Any], fragment: dict[str, Any], merge_reason: str) -> None:
    text = str(fragment.get("text") or "")
    if text:
        unit["text"] = f"{unit['text']}\n{text}" if unit["text"] else text
    bbox = fragment.get("bbox")
    if _valid_bbox(unit.get("bbox")) and _valid_bbox(bbox):
        unit["bbox"] = _union_bbox(unit["bbox"], bbox)
    for page in fragment.get("pages") or []:
        if page not in unit["pages"]:
            unit["pages"].append(page)
    unit["spans"].extend(deepcopy(fragment.get("spans") or []))
    unit["observation_ids"].extend(fragment.get("observation_ids") or [])
    for role_hint in fragment.get("role_hints") or []:
        if role_hint not in unit["role_hints"]:
            unit["role_hints"].append(role_hint)
    unit["parser_payloads"].extend(deepcopy(fragment.get("parser_payloads") or []))
    unit["attrs"].setdefault("merge_reasons", []).append(merge_reason)
    _merge_unit_attrs(unit["attrs"], fragment.get("attrs") or {})


def _merge_unit_attrs(attrs: dict[str, Any], fragment_attrs: dict[str, Any]) -> None:
    inline_runs = fragment_attrs.get("inline_runs")
    if isinstance(inline_runs, list):
        attrs.setdefault("inline_runs", []).extend(deepcopy(inline_runs))
    note_refs = fragment_attrs.get("note_refs")
    if isinstance(note_refs, list):
        attrs.setdefault("note_refs", []).extend(deepcopy(note_refs))


def _renumber_units(units: list[dict[str, Any]]) -> None:
    for index, unit in enumerate(units, start=1):
        unit["unit_id"] = f"tu{index:06d}"


def _unit_from_observation(
    observation: dict[str, Any],
    index: int,
    unit_type: str,
    layout_role: str | None = None,
) -> dict[str, Any]:
    bbox = deepcopy(observation.get("bbox"))
    attrs = _unit_attrs(observation)
    if layout_role:
        attrs["layout_role"] = layout_role
    return {
        "unit_id": f"tu{index:06d}",
        "unit_type": unit_type,
        "text": str(observation.get("text") or ""),
        "page": observation["page"],
        "pages": [observation["page"]],
        "bbox": bbox,
        "spans": _observation_spans(observation),
        "observation_ids": [observation["observation_id"]],
        "role_hints": [observation["role_hint"]],
        "attrs": attrs,
        "parser_payloads": [deepcopy(observation.get("parser_payload") or {})],
    }


def _observation_spans(observation: dict[str, Any]) -> list[dict[str, Any]]:
    spans = observation.get("spans")
    if isinstance(spans, list) and spans:
        return deepcopy(spans)
    bbox = observation.get("bbox")
    if _valid_bbox(bbox):
        return [{"page": observation["page"], "bbox": deepcopy(bbox)}]
    return []


def _unit_attrs(observation: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    observation_attrs = observation.get("attrs")
    if not isinstance(observation_attrs, dict):
        return attrs
    inline_runs = observation_attrs.get("inline_runs")
    if isinstance(inline_runs, list):
        attrs["inline_runs"] = deepcopy(inline_runs)
    note_refs = observation_attrs.get("note_refs")
    if isinstance(note_refs, list):
        attrs["note_refs"] = deepcopy(note_refs)
    return attrs


def _merge_reason(
    previous_unit: dict[str, Any],
    observation: dict[str, Any],
    unit_type: str,
    page_sizes: dict[int, dict[str, float]],
) -> str | None:
    if unit_type != "paragraph" or previous_unit["unit_type"] != "paragraph":
        return None
    if previous_unit["page"] == observation["page"]:
        if _same_page_short_line_group_merge(previous_unit, observation, page_sizes):
            return "same_page_short_line_group"
        return (
            "same_page_geometry_continuation"
            if _same_page_merge(previous_unit, observation)
            else None
        )
    return (
        "cross_page_boundary_continuation"
        if _cross_page_merge(previous_unit, observation, page_sizes)
        else None
    )


def _same_page_merge(previous_unit: dict[str, Any], observation: dict[str, Any]) -> bool:
    previous_bbox = previous_unit.get("bbox")
    bbox = observation.get("bbox")
    if not _valid_bbox(previous_bbox) or not _valid_bbox(bbox):
        return False
    return (
        _vertical_gap(previous_bbox, bbox) <= _max_vertical_gap(previous_bbox)
        and _vertical_gap(previous_bbox, bbox) >= 0
        and _left_delta(previous_bbox, bbox) <= _max_left_delta(previous_bbox)
        and _horizontal_overlap_ratio(previous_bbox, bbox) >= 0.6
    )


def _same_page_short_line_group_merge(
    previous_unit: dict[str, Any],
    observation: dict[str, Any],
    page_sizes: dict[int, dict[str, float]],
) -> bool:
    previous_bbox = _last_bbox_for_page(previous_unit, int(observation["page"]))
    bbox = observation.get("bbox")
    page_width = float(page_sizes.get(int(observation["page"]), {}).get("width") or 0.0)
    if not _valid_bbox(previous_bbox) or not _valid_bbox(bbox) or page_width <= 0:
        return False
    max_line_width = page_width * 0.55
    return (
        0 <= _vertical_gap(previous_bbox, bbox) <= max(36.0, _height(previous_bbox) * 2.0)
        and _width(previous_bbox) <= max_line_width
        and _width(bbox) <= max_line_width
        and (
            _right_delta(previous_bbox, bbox) <= max(24.0, page_width * 0.03)
            or _center_delta(previous_bbox, bbox) <= max(24.0, page_width * 0.03)
            or _left_delta(previous_bbox, bbox) <= max(24.0, page_width * 0.03)
        )
    )


def _cross_page_merge(
    previous_unit: dict[str, Any],
    observation: dict[str, Any],
    page_sizes: dict[int, dict[str, float]],
) -> bool:
    previous_page = _last_page(previous_unit)
    page = int(observation["page"])
    if previous_page + 1 != page:
        return False
    previous_bbox = _last_bbox_for_page(previous_unit, previous_page)
    bbox = observation.get("bbox")
    previous_height = page_sizes.get(previous_page, {}).get("height")
    current_height = page_sizes.get(page, {}).get("height")
    if (
        not _valid_bbox(previous_bbox)
        or not _valid_bbox(bbox)
        or previous_height is None
        or current_height is None
    ):
        return False
    return (
        _near_page_bottom(previous_bbox, previous_height)
        and _near_page_top(bbox, current_height)
        and _left_delta(previous_bbox, bbox) <= _max_left_delta(previous_bbox)
        and _horizontal_overlap_ratio(previous_bbox, bbox) >= 0.6
    )


def _merge_observation(
    unit: dict[str, Any], observation: dict[str, Any], merge_reason: str
) -> None:
    text = str(observation.get("text") or "")
    if text:
        unit["text"] = f"{unit['text']}\n{text}" if unit["text"] else text
    bbox = observation.get("bbox")
    if unit["page"] == observation["page"] and _valid_bbox(unit.get("bbox")) and _valid_bbox(bbox):
        unit["bbox"] = _union_bbox(unit["bbox"], bbox)
    page = int(observation["page"])
    if page not in unit["pages"]:
        unit["pages"].append(page)
    unit["spans"].extend(_observation_spans(observation))
    unit["observation_ids"].append(observation["observation_id"])
    if observation["role_hint"] not in unit["role_hints"]:
        unit["role_hints"].append(observation["role_hint"])
    unit["parser_payloads"].append(deepcopy(observation.get("parser_payload") or {}))
    unit["attrs"].setdefault("merge_reasons", []).append(merge_reason)
    _merge_attrs(unit["attrs"], observation)


def _merge_attrs(attrs: dict[str, Any], observation: dict[str, Any]) -> None:
    observation_attrs = observation.get("attrs")
    if not isinstance(observation_attrs, dict):
        return
    inline_runs = observation_attrs.get("inline_runs")
    if isinstance(inline_runs, list):
        attrs.setdefault("inline_runs", []).extend(deepcopy(inline_runs))
    note_refs = observation_attrs.get("note_refs")
    if isinstance(note_refs, list):
        attrs.setdefault("note_refs", []).extend(deepcopy(note_refs))


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )


def _bbox_top(value: Any) -> float:
    return float(value[1]) if _valid_bbox(value) else 999999.0


def _bbox_left(value: Any) -> float:
    return float(value[0]) if _valid_bbox(value) else 999999.0


def _last_page(unit: dict[str, Any]) -> int:
    return int(unit.get("pages", [unit["page"]])[-1])


def _last_bbox_for_page(unit: dict[str, Any], page: int) -> Any:
    for span in reversed(unit.get("spans") or []):
        if (
            isinstance(span, dict)
            and int(span.get("page", page)) == page
            and _valid_bbox(span.get("bbox"))
        ):
            return span["bbox"]
    if int(unit["page"]) == page:
        return unit.get("bbox")
    return None


def _vertical_gap(left: list[float], right: list[float]) -> float:
    return float(right[1]) - float(left[3])


def _max_vertical_gap(bbox: list[float]) -> float:
    return min(32.0, max(24.0, (float(bbox[3]) - float(bbox[1])) * 1.5))


def _left_delta(left: list[float], right: list[float]) -> float:
    return abs(float(left[0]) - float(right[0]))


def _max_left_delta(bbox: list[float]) -> float:
    return max(24.0, (float(bbox[2]) - float(bbox[0])) * 0.08)


def _right_delta(left: list[float], right: list[float]) -> float:
    return abs(float(left[2]) - float(right[2]))


def _center_delta(left: list[float], right: list[float]) -> float:
    return abs(((float(left[0]) + float(left[2])) / 2) - ((float(right[0]) + float(right[2])) / 2))


def _height(bbox: list[float]) -> float:
    return float(bbox[3]) - float(bbox[1])


def _width(bbox: list[float]) -> float:
    return float(bbox[2]) - float(bbox[0])


def _near_page_bottom(bbox: list[float], page_height: float) -> bool:
    return float(bbox[3]) >= page_height * 0.88


def _near_page_top(bbox: list[float], page_height: float) -> bool:
    return float(bbox[1]) <= page_height * 0.15


def _horizontal_overlap_ratio(left: list[float], right: list[float]) -> float:
    overlap = max(0.0, min(float(left[2]), float(right[2])) - max(float(left[0]), float(right[0])))
    width = min(float(left[2]) - float(left[0]), float(right[2]) - float(right[0]))
    if width <= 0:
        return 0.0
    return overlap / width


def _near_visual_region(
    observation: dict[str, Any],
    visual_bboxes: dict[int, list[list[float]]],
) -> bool:
    bbox = observation.get("bbox")
    if observation.get("role_hint") != "title_text" or not _valid_bbox(bbox):
        return False
    text_bbox = [float(value) for value in bbox]
    for visual_bbox in visual_bboxes.get(int(observation["page"]), []):
        if _near_visual_bbox(text_bbox, visual_bbox):
            return True
    return False


def _near_visual_bbox(text_bbox: list[float], visual_bbox: list[float]) -> bool:
    vertical_gap = max(
        float(visual_bbox[1]) - float(text_bbox[3]),
        float(text_bbox[1]) - float(visual_bbox[3]),
        0.0,
    )
    horizontal_gap = max(
        float(visual_bbox[0]) - float(text_bbox[2]),
        float(text_bbox[0]) - float(visual_bbox[2]),
        0.0,
    )
    return (
        vertical_gap <= 64.0
        and (
            _horizontal_overlap_ratio(text_bbox, visual_bbox) >= 0.5
            or horizontal_gap <= 96.0
        )
    )


def _union_bbox(left: list[float], right: list[float]) -> list[float]:
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]
