from __future__ import annotations

from copy import deepcopy
from typing import Any, TypeGuard

from inkline.canonical.observed.schema import validate_observed_document

TEXT_UNIT_TYPES = {"heading", "paragraph", "display_block", "list_item", "footnote"}
_MIN_FIRST_LINE_INDENT = 8.0


def build_text_units(
    document: dict[str, Any],
    *,
    included_pages: set[int] | None = None,
    anchor_groups_by_observation_id: dict[str, tuple[str, ...]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from inkline.canonical.text_flow.candidates import build_text_candidates

    validate_observed_document(document)
    units: list[dict[str, Any]] = []
    page_sizes = _page_sizes(document["pages"])
    effective_included_pages = (
        included_pages
        if included_pages is not None
        else {int(observation["page"]) for observation in document["observations"]}
    )
    observations = [
        observation
        for observation in document["observations"]
        if int(observation["page"]) in effective_included_pages
    ]
    visual_bboxes = _visual_bboxes(observations)
    table_bboxes = _region_bboxes(observations, {"table_region"})
    candidates, ignored_counts = build_text_candidates(
        document,
        included_pages=effective_included_pages,
        anchor_groups_by_observation_id=anchor_groups_by_observation_id or {},
    )

    for candidate in candidates:
        unit_type = _legacy_unit_type(candidate["candidate_type"])
        merge_reason = (
            _merge_reason(units[-1], candidate, unit_type, page_sizes) if units else None
        )
        if merge_reason:
            _merge_candidate(units[-1], candidate, merge_reason)
            continue
        units.append(_unit_from_candidate(candidate, len(units) + 1, unit_type))

    _promote_table_heading_fragments(units, page_sizes, table_bboxes)
    _merge_direct_anchor_fragments(units, anchor_groups_by_observation_id or {})
    _merge_heading_cluster_fragments(
        units,
        page_sizes,
        visual_bboxes,
        anchor_groups_by_observation_id or {},
    )
    _renumber_units(units)
    return units, ignored_counts


def _legacy_unit_type(candidate_type: str) -> str:
    return "paragraph" if candidate_type == "body_text" else candidate_type


def _merge_direct_anchor_fragments(
    units: list[dict[str, Any]],
    anchor_groups_by_observation_id: dict[str, tuple[str, ...]],
) -> None:
    """Materialize each protected direct title anchor as one exact heading unit."""

    groups = list(dict.fromkeys(anchor_groups_by_observation_id.values()))
    for group in groups:
        group_ids = set(group)
        fragments = [
            unit
            for unit in units
            if set(unit.get("observation_ids") or [])
            and set(unit.get("observation_ids") or []) <= group_ids
        ]
        covered = {
            observation_id
            for fragment in fragments
            for observation_id in fragment.get("observation_ids") or []
        }
        if covered != group_ids or not fragments:
            continue
        keeper = fragments[0]
        keeper["unit_type"] = "heading"
        keeper["attrs"]["structure_promotion"] = "direct_skeleton_anchor"
        for fragment in fragments[1:]:
            _merge_unit_fragment(keeper, fragment, "direct_skeleton_anchor")
            units.remove(fragment)


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
    anchor_groups_by_observation_id: dict[str, tuple[str, ...]],
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
        for contiguous_cluster in _contiguous_heading_clusters(
            page_units, heading_bboxes, page_width, page_height
        ):
            for cluster in _protected_heading_clusters(
                contiguous_cluster, anchor_groups_by_observation_id
            ):
                if len(cluster) < 2:
                    continue
                keeper = cluster[0]
                keeper["unit_type"] = "heading"
                keeper["attrs"]["structure_promotion"] = "heading_cluster"
                for fragment in cluster[1:]:
                    _merge_unit_fragment(keeper, fragment, "heading_cluster")
                    units.remove(fragment)


def _contiguous_heading_clusters(
    page_units: list[dict[str, Any]],
    heading_bboxes: list[list[float]],
    page_width: float,
    page_height: float,
) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for unit in page_units:
        candidate = unit.get("unit_type") == "heading" or (
            unit.get("unit_type") == "paragraph"
            and _heading_cluster_candidate(unit, heading_bboxes, page_width, page_height)
        )
        if candidate:
            current.append(unit)
            continue
        if len(current) >= 2:
            clusters.append(current)
        current = []
    if len(current) >= 2:
        clusters.append(current)
    return clusters


def _protected_heading_clusters(
    cluster_units: list[dict[str, Any]],
    anchor_groups_by_observation_id: dict[str, tuple[str, ...]],
) -> list[list[dict[str, Any]]]:
    protected_keys = {
        anchor_groups_by_observation_id[observation_id]
        for unit in cluster_units
        for observation_id in unit.get("observation_ids") or []
        if observation_id in anchor_groups_by_observation_id
    }
    if not protected_keys:
        return [cluster_units]
    clusters: list[list[dict[str, Any]]] = []
    by_key: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for unit in cluster_units:
        keys = {
            anchor_groups_by_observation_id[observation_id]
            for observation_id in unit.get("observation_ids") or []
            if observation_id in anchor_groups_by_observation_id
        }
        if len(keys) != 1:
            clusters.append([unit])
            continue
        key = next(iter(keys))
        cluster = by_key.setdefault(key, [])
        if not cluster:
            clusters.append(cluster)
        cluster.append(unit)
    return clusters


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


def _unit_from_candidate(
    candidate: dict[str, Any],
    index: int,
    unit_type: str,
) -> dict[str, Any]:
    return {
        "unit_id": f"tu{index:06d}",
        "unit_type": unit_type,
        "text": candidate["text"],
        "page": candidate["page"],
        "pages": [candidate["page"]],
        "bbox": deepcopy(candidate["bbox"]),
        "spans": deepcopy(candidate["spans"]),
        "observation_ids": [candidate["observation_id"]],
        "role_hints": [candidate["role_hint"]],
        "attrs": deepcopy(candidate["attrs"]),
        "parser_payloads": [deepcopy(candidate["parser_payload"])],
    }


def _merge_reason(
    previous_unit: dict[str, Any],
    candidate: dict[str, Any],
    unit_type: str,
    page_sizes: dict[int, dict[str, float]],
) -> str | None:
    if unit_type != "paragraph" or previous_unit["unit_type"] != "paragraph":
        return None
    if previous_unit["page"] == candidate["page"]:
        if _same_page_short_line_group_merge(previous_unit, candidate, page_sizes):
            return "same_page_short_line_group"
        return (
            "same_page_geometry_continuation"
            if _same_page_merge(previous_unit, candidate)
            else None
        )
    return (
        "cross_page_boundary_continuation"
        if _cross_page_merge(previous_unit, candidate, page_sizes)
        else None
    )


def _same_page_merge(previous_unit: dict[str, Any], candidate: dict[str, Any]) -> bool:
    previous_bbox = previous_unit.get("bbox")
    bbox = candidate.get("bbox")
    if not _valid_bbox(previous_bbox) or not _valid_bbox(bbox):
        return False
    return (
        _vertical_gap(previous_bbox, bbox) <= _max_vertical_gap(previous_bbox)
        and _vertical_gap(previous_bbox, bbox) >= 0
        and _left_delta(previous_bbox, bbox) <= _max_left_delta(previous_bbox)
        and _horizontal_overlap_ratio(previous_bbox, bbox) >= 0.6
    )


def _same_page_short_line_group_merge(
    previous_unit: dict[str, Any], candidate: dict[str, Any],
    page_sizes: dict[int, dict[str, float]],
) -> bool:
    previous_bbox = _last_bbox_for_page(previous_unit, int(candidate["page"]))
    bbox = candidate.get("bbox")
    page_width = float(page_sizes.get(int(candidate["page"]), {}).get("width") or 0.0)
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
    previous_unit: dict[str, Any], candidate: dict[str, Any],
    page_sizes: dict[int, dict[str, float]],
) -> bool:
    previous_page = _last_page(previous_unit)
    page = int(candidate["page"])
    if previous_page + 1 != page:
        return False
    previous_bbox = _last_bbox_for_page(previous_unit, previous_page)
    bbox = candidate.get("bbox")
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
        and _horizontal_overlap_ratio(previous_bbox, bbox) >= 0.6
        and _cross_page_text_flow_continues(previous_bbox, bbox, candidate)
    )


def _cross_page_text_flow_continues(
    previous_bbox: list[float], bbox: list[float], candidate: dict[str, Any]
) -> bool:
    if _next_candidate_starts_new_paragraph(candidate):
        return False
    if _next_candidate_starts_continuation(candidate):
        return True
    return _left_delta(previous_bbox, bbox) <= _max_left_delta(previous_bbox)


def _next_candidate_starts_new_paragraph(candidate: dict[str, Any]) -> bool:
    metrics = _candidate_text_line_metrics(candidate)
    if not metrics:
        return False
    line_count = _metric_int(metrics, "line_count")
    if line_count is not None and line_count < 2:
        return False
    indent = _metric_float(metrics, "first_line_indent")
    char_width = _metric_float(metrics, "char_width")
    if indent is None:
        return False
    threshold = max(_MIN_FIRST_LINE_INDENT, (char_width or 10.0) * 1.15)
    return indent >= threshold


def _next_candidate_starts_continuation(candidate: dict[str, Any]) -> bool:
    metrics = _candidate_text_line_metrics(candidate)
    if not metrics:
        return False
    line_count = _metric_int(metrics, "line_count")
    if line_count is not None and line_count < 2:
        return False
    indent = _metric_float(metrics, "first_line_indent")
    char_width = _metric_float(metrics, "char_width")
    if indent is None:
        return False
    threshold = max(6.0, (char_width or 10.0) * 0.75)
    return abs(indent) <= threshold


def _candidate_text_line_metrics(candidate: dict[str, Any]) -> dict[str, Any] | None:
    attrs = candidate.get("attrs") if isinstance(candidate.get("attrs"), dict) else {}
    metrics_by_observation = attrs.get("text_line_metrics_by_observation")
    if not isinstance(metrics_by_observation, dict):
        return None
    metrics = metrics_by_observation.get(candidate["observation_id"])
    return metrics if isinstance(metrics, dict) else None


def _metric_float(metrics: dict[str, Any], key: str) -> float | None:
    try:
        return float(metrics[key])
    except (KeyError, TypeError, ValueError):
        return None


def _metric_int(metrics: dict[str, Any], key: str) -> int | None:
    try:
        return int(metrics[key])
    except (KeyError, TypeError, ValueError):
        return None


def _merge_candidate(
    unit: dict[str, Any], candidate: dict[str, Any], merge_reason: str
) -> None:
    target_text = str(unit.get("text") or "")
    text = str(candidate.get("text") or "")
    if text:
        unit["text"] = _join_merged_text(target_text, text, merge_reason)
    bbox = candidate.get("bbox")
    if unit["page"] == candidate["page"] and _valid_bbox(unit.get("bbox")) and _valid_bbox(bbox):
        unit["bbox"] = _union_bbox(unit["bbox"], bbox)
    page = int(candidate["page"])
    if page not in unit["pages"]:
        unit["pages"].append(page)
    unit["spans"].extend(deepcopy(candidate["spans"]))
    unit["observation_ids"].append(candidate["observation_id"])
    if candidate["role_hint"] not in unit["role_hints"]:
        unit["role_hints"].append(candidate["role_hint"])
    unit["parser_payloads"].append(deepcopy(candidate["parser_payload"]))
    unit["attrs"].setdefault("merge_reasons", []).append(merge_reason)
    _merge_attrs(unit["attrs"], candidate["attrs"], target_text=target_text, source_text=text)


def _join_merged_text(target_text: str, source_text: str, merge_reason: str) -> str:
    if not target_text:
        return source_text
    if merge_reason == "cross_page_boundary_continuation":
        return f"{target_text}{source_text}"
    return f"{target_text}\n{source_text}"


def _merge_attrs(
    attrs: dict[str, Any], candidate_attrs: dict[str, Any],
    *,
    target_text: str,
    source_text: str,
) -> None:
    text_line_metrics = candidate_attrs.get("text_line_metrics_by_observation")
    if isinstance(text_line_metrics, dict):
        attrs.setdefault("text_line_metrics_by_observation", {}).update(deepcopy(text_line_metrics))
    inline_runs = candidate_attrs.get("inline_runs")
    if isinstance(inline_runs, list):
        if "inline_runs" not in attrs and target_text:
            attrs["inline_runs"] = [{"type": "text", "text": target_text}]
        attrs.setdefault("inline_runs", []).extend(deepcopy(inline_runs))
    elif "inline_runs" in attrs and source_text:
        attrs["inline_runs"].append({"type": "text", "text": source_text})
    note_refs = candidate_attrs.get("note_refs")
    if isinstance(note_refs, list):
        attrs.setdefault("note_refs", []).extend(deepcopy(note_refs))


def _valid_bbox(value: Any) -> TypeGuard[list[float]]:
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
    return vertical_gap <= 64.0 and (
        _horizontal_overlap_ratio(text_bbox, visual_bbox) >= 0.5 or horizontal_gap <= 96.0
    )


def _union_bbox(left: list[float], right: list[float]) -> list[float]:
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]
