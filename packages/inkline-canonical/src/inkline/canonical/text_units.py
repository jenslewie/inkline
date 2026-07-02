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

    for observation in _ordered_observations(document["observations"]):
        layout_role = None
        unit_type = _unit_type(observation, visual_bboxes)
        if observation["role_hint"] == "title_text" and _near_visual_region(
            observation, visual_bboxes
        ):
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
    grouped: dict[int, list[list[float]]] = {}
    for observation in observations:
        if observation.get("kind") not in {"image_region", "table_region"}:
            continue
        bbox = observation.get("bbox")
        if _valid_bbox(bbox):
            grouped.setdefault(int(observation["page"]), []).append(
                [float(value) for value in bbox]
            )
    return grouped


def _reading_order(observation: dict[str, Any]) -> int:
    attrs = observation.get("attrs") if isinstance(observation.get("attrs"), dict) else {}
    value = attrs.get("reading_order")
    return int(value) if isinstance(value, int) else 999999


def _unit_type(
    observation: dict[str, Any], visual_bboxes: dict[int, list[list[float]]]
) -> str | None:
    role_hint = observation["role_hint"]
    if role_hint == "title_text":
        if _near_visual_region(observation, visual_bboxes):
            return "paragraph"
        return "heading"
    if role_hint == "body_text":
        return "paragraph"
    if role_hint == "list_text":
        return "list_item"
    if observation["kind"] == "footnote_region" or role_hint == "footnote_text":
        return "footnote"
    return None


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
        and "paragraph" in unit_types
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
    if merge_reason in {"cross_page_boundary_continuation", "same_page_short_line_group"}:
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
        vertical_gap = max(
            float(visual_bbox[1]) - float(text_bbox[3]),
            float(text_bbox[1]) - float(visual_bbox[3]),
            0.0,
        )
        if vertical_gap <= 64.0 and _horizontal_overlap_ratio(text_bbox, visual_bbox) >= 0.5:
            return True
    return False


def _union_bbox(left: list[float], right: list[float]) -> list[float]:
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]
