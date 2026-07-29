from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, TypeGuard

from inkline.canonical.observed.index import ObservedIndex, build_observed_index
from inkline.canonical.observed.page_roles import page_roles_by_page
from inkline.canonical.text_flow.aggregation import (
    aggregate_text_candidates,
    materialize_text_units,
)
from inkline.canonical.text_flow.candidates import build_text_candidates
from inkline.canonical.text_flow.contract import TEXT_FLOW_SCHEMA_NAME, TEXT_FLOW_SCHEMA_VERSION
from inkline.canonical.text_flow.layout import classify_text_candidates_by_layout
from inkline.canonical.text_flow.reconcile import reconcile_text_flow_records
from inkline.canonical.text_flow.validation import validate_text_flow_against_sources

NON_TEXT_BRIDGE_PAGE_ROLES = {"visual_page", "blank_page"}
TEXT_FLOW_BRIDGE_PAGE_ROLES = {"text_flow_page"}
_MIN_FIRST_LINE_INDENT = 8.0


def build_text_flow(
    observed_document: dict[str, Any],
    skeleton: dict[str, Any],
    page_review: dict[str, Any],
    page_layout: dict[str, Any],
    *,
    observed_index: ObservedIndex | None = None,
) -> dict[str, Any]:
    """Build the one authoritative, reviewed and Skeleton-aware TextUnit sequence."""

    index = observed_index or build_observed_index(observed_document)
    included_pages = {
        int(record["page"])
        for record in page_review.get("pages") or []
        if isinstance(record, dict) and record.get("text_flow_action") == "include"
    }
    anchor_groups = _direct_anchor_map(skeleton, included_pages)
    candidates, ignored_counts = build_text_candidates(
        observed_document,
        included_pages=included_pages,
        anchor_groups_by_observation_id=anchor_groups,
    )
    classified = classify_text_candidates_by_layout(
        candidates,
        observed_document["pages"],
        page_layout=page_layout,
    )
    records = aggregate_text_candidates(classified, observed_document["pages"])
    records = reconcile_text_flow_records(
        records,
        observed_document["pages"],
        page_layout,
    )
    final_units = materialize_text_units(records)
    metadata_sources = {
        "observed": observed_document["metadata"],
        "skeleton": skeleton["metadata"],
        "page_review": page_review["metadata"],
        "page_layout": page_layout["metadata"],
    }
    all_pages = set(index.page_numbers)
    flow = {
        "metadata": {
            "schema_name": TEXT_FLOW_SCHEMA_NAME,
            "schema_version": TEXT_FLOW_SCHEMA_VERSION,
            "doc_id": index.doc_id,
        },
        "text_units": final_units,
        "ignored_observation_counts": ignored_counts,
        "provenance": {
            "observed_schema_name": metadata_sources["observed"]["schema_name"],
            "observed_schema_version": metadata_sources["observed"]["schema_version"],
            "skeleton_schema_name": metadata_sources["skeleton"]["schema_name"],
            "skeleton_schema_version": metadata_sources["skeleton"]["schema_version"],
            "page_review_schema_name": metadata_sources["page_review"]["schema_name"],
            "page_review_schema_version": metadata_sources["page_review"]["schema_version"],
            "page_layout_schema_name": metadata_sources["page_layout"]["schema_name"],
            "page_layout_schema_version": metadata_sources["page_layout"]["schema_version"],
            "included_pages": sorted(included_pages),
            "excluded_pages": sorted(all_pages - included_pages),
            "direct_anchor_group_count": len(set(anchor_groups.values())),
        },
    }
    validate_text_flow_against_sources(
        flow,
        observed_document,
        skeleton,
        page_review,
        page_layout,
        observed_index=index,
    )
    return flow


def finalize_text_units(
    text_units: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    page_role_records: list[dict[str, Any]],
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply logical paragraph boundaries and assign the final tu identity once."""

    observations_by_id = {
        str(observation["observation_id"]): observation for observation in observations
    }
    logical_units: list[dict[str, Any]] = []
    for unit in text_units:
        logical_units.extend(_logical_units_from_text_unit(unit, observations_by_id))
    logical_units = _merge_paragraphs_across_nontext_pages(logical_units, page_role_records, pages)
    for index, unit in enumerate(logical_units, start=1):
        unit["unit_id"] = f"tu{index:06d}"
        attrs = unit.get("attrs")
        if isinstance(attrs, dict):
            attrs.pop("source_text_unit_id", None)
            attrs.pop("source_text_unit_ids", None)
    return logical_units


def _direct_anchor_map(
    skeleton: dict[str, Any], included_pages: set[int]
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for entry in skeleton.get("toc_entries") or []:
        anchor = entry.get("selected_start_anchor")
        if (
            not isinstance(anchor, Mapping)
            or anchor.get("resolution_method") != "observed_title_match"
            or int(anchor["page"]) not in included_pages
        ):
            continue
        group = tuple(str(value) for value in anchor.get("title_observation_ids") or [])
        for observation_id in group:
            result[observation_id] = group
    return result


def _logical_units_from_text_unit(
    unit: dict[str, Any], observations_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    if unit.get("unit_type") != "paragraph":
        return [deepcopy(unit)]
    observation_ids = list(unit.get("observation_ids") or [])
    merge_reasons = list((unit.get("attrs") or {}).get("merge_reasons") or [])
    if not observation_ids or "same_page_geometry_continuation" not in merge_reasons:
        return [deepcopy(unit)]
    groups: list[list[str]] = [[observation_ids[0]]]
    group_merge_reasons: list[list[str]] = [[]]
    for index, observation_id in enumerate(observation_ids[1:]):
        reason = merge_reasons[index] if index < len(merge_reasons) else ""
        if reason == "same_page_geometry_continuation":
            groups.append([observation_id])
            group_merge_reasons.append([])
        else:
            groups[-1].append(observation_id)
            group_merge_reasons[-1].append(reason)
    return [
        _unit_from_observation_group(
            unit,
            group,
            group_merge_reasons[index],
            observations_by_id,
            logical_split_reason="same_page_geometry_continuation",
        )
        for index, group in enumerate(groups)
    ]


def _unit_from_observation_group(
    source_unit: dict[str, Any],
    observation_ids: list[str],
    merge_reasons: list[str],
    observations_by_id: dict[str, dict[str, Any]],
    *,
    logical_split_reason: str,
) -> dict[str, Any]:
    observations = [observations_by_id[observation_id] for observation_id in observation_ids]
    pages: list[int] = []
    spans: list[dict[str, Any]] = []
    parser_payloads: list[dict[str, Any]] = []
    role_hints: list[str] = []
    attrs: dict[str, Any] = {"logical_split_reason": logical_split_reason}
    if merge_reasons:
        attrs["merge_reasons"] = list(merge_reasons)
    bbox = None
    text_parts: list[str] = []
    for observation in observations:
        text = str(observation.get("text") or "")
        if text:
            text_parts.append(text)
        page = int(observation["page"])
        if page not in pages:
            pages.append(page)
        spans.extend(_observation_spans(observation))
        parser_payloads.append(deepcopy(observation.get("parser_payload") or {}))
        role_hint = str(observation.get("role_hint") or "")
        if role_hint and role_hint not in role_hints:
            role_hints.append(role_hint)
        _merge_observation_attrs(attrs, observation)
        observation_bbox = observation.get("bbox")
        if _valid_bbox(observation_bbox):
            bbox = (
                _union_bbox(bbox, observation_bbox)
                if bbox is not None
                else deepcopy(observation_bbox)
            )
    return {
        "unit_id": source_unit["unit_id"],
        "unit_type": source_unit["unit_type"],
        "text": "\n".join(text_parts),
        "page": pages[0],
        "pages": pages,
        "bbox": bbox,
        "spans": spans,
        "observation_ids": list(observation_ids),
        "role_hints": role_hints,
        "attrs": attrs,
        "parser_payloads": parser_payloads,
    }


def _merge_observation_attrs(attrs: dict[str, Any], observation: dict[str, Any]) -> None:
    observation_attrs = observation.get("attrs")
    if not isinstance(observation_attrs, dict):
        return
    metrics = observation_attrs.get("text_line_metrics")
    if isinstance(metrics, dict):
        attrs.setdefault("text_line_metrics_by_observation", {})[
            str(observation["observation_id"])
        ] = deepcopy(metrics)
    for field in ("inline_runs", "note_refs"):
        value = observation_attrs.get(field)
        if isinstance(value, list):
            attrs.setdefault(field, []).extend(deepcopy(value))


def _merge_paragraphs_across_nontext_pages(
    units: list[dict[str, Any]],
    page_role_records: list[dict[str, Any]],
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    roles_by_page = page_roles_by_page(page_role_records)
    page_sizes = {
        int(page["page"]): {"width": float(page["width"]), "height": float(page["height"])}
        for page in pages
    }
    merged: list[dict[str, Any]] = []
    for unit in units:
        if merged and _nontext_page_bridge_merge(merged[-1], unit, roles_by_page, page_sizes):
            _merge_unit(merged[-1], unit, "cross_nontext_page_boundary_continuation")
        else:
            merged.append(unit)
    return merged


def _nontext_page_bridge_merge(
    previous: dict[str, Any],
    current: dict[str, Any],
    roles_by_page: dict[int, dict[str, Any]],
    page_sizes: dict[int, dict[str, float]],
) -> bool:
    if previous.get("unit_type") != "paragraph" or current.get("unit_type") != "paragraph":
        return False
    if "\n" in str(previous.get("text") or "") or "\n" in str(current.get("text") or ""):
        return False
    previous_page = int((previous.get("pages") or [previous["page"]])[-1])
    current_page = int((current.get("pages") or [current["page"]])[0])
    if current_page <= previous_page + 1:
        return False
    if (
        str(roles_by_page.get(previous_page, {}).get("page_role") or "")
        not in TEXT_FLOW_BRIDGE_PAGE_ROLES
    ):
        return False
    if (
        str(roles_by_page.get(current_page, {}).get("page_role") or "")
        not in TEXT_FLOW_BRIDGE_PAGE_ROLES
    ):
        return False
    if not all(
        str(roles_by_page.get(page, {}).get("page_role") or "") in NON_TEXT_BRIDGE_PAGE_ROLES
        for page in range(previous_page + 1, current_page)
    ):
        return False
    previous_bbox = _last_span_bbox(previous)
    current_bbox = _first_span_bbox(current)
    previous_height = page_sizes.get(previous_page, {}).get("height")
    current_height = page_sizes.get(current_page, {}).get("height")
    if (
        not _valid_bbox(previous_bbox)
        or not _valid_bbox(current_bbox)
        or previous_height is None
        or current_height is None
    ):
        return False
    return (
        float(previous_bbox[3]) >= previous_height * 0.86
        and float(current_bbox[1]) <= current_height * 0.16
        and not _unit_starts_new_paragraph(current)
        and _left_delta(previous_bbox, current_bbox) <= _max_left_delta(previous_bbox)
        and _horizontal_overlap_ratio(previous_bbox, current_bbox) >= 0.6
    )


def _merge_unit(target: dict[str, Any], source: dict[str, Any], merge_reason: str) -> None:
    target_text = str(target.get("text") or "")
    source_text = str(source.get("text") or "")
    if source_text:
        target["text"] = f"{target_text}{source_text}" if target_text else source_text
    for page in source.get("pages") or []:
        if page not in target["pages"]:
            target["pages"].append(page)
    target["spans"].extend(deepcopy(source.get("spans") or []))
    target["observation_ids"].extend(source.get("observation_ids") or [])
    for role_hint in source.get("role_hints") or []:
        if role_hint not in target["role_hints"]:
            target["role_hints"].append(role_hint)
    target["parser_payloads"].extend(deepcopy(source.get("parser_payloads") or []))
    target_attrs = target.setdefault("attrs", {})
    source_attrs = source.get("attrs") or {}
    _merge_inline_attrs(target_attrs, source_attrs, target_text, source_text)
    target_attrs.setdefault("merge_reasons", []).append(merge_reason)


def _merge_inline_attrs(
    target_attrs: dict[str, Any],
    source_attrs: dict[str, Any],
    target_text: str,
    source_text: str,
) -> None:
    metrics = source_attrs.get("text_line_metrics_by_observation")
    if isinstance(metrics, dict):
        target_attrs.setdefault("text_line_metrics_by_observation", {}).update(deepcopy(metrics))
    inline_runs = source_attrs.get("inline_runs")
    if isinstance(inline_runs, list):
        if "inline_runs" not in target_attrs and target_text:
            target_attrs["inline_runs"] = [{"type": "text", "text": target_text}]
        target_attrs.setdefault("inline_runs", []).extend(deepcopy(inline_runs))
    elif "inline_runs" in target_attrs and source_text:
        target_attrs["inline_runs"].append({"type": "text", "text": source_text})
    note_refs = source_attrs.get("note_refs")
    if isinstance(note_refs, list):
        target_attrs.setdefault("note_refs", []).extend(deepcopy(note_refs))


def _first_span_bbox(unit: dict[str, Any]) -> Any:
    for span in unit.get("spans") or []:
        bbox = span.get("bbox") if isinstance(span, dict) else None
        if _valid_bbox(bbox):
            return bbox
    return unit.get("bbox")


def _last_span_bbox(unit: dict[str, Any]) -> Any:
    for span in reversed(unit.get("spans") or []):
        bbox = span.get("bbox") if isinstance(span, dict) else None
        if _valid_bbox(bbox):
            return bbox
    return unit.get("bbox")


def _unit_starts_new_paragraph(unit: dict[str, Any]) -> bool:
    observation_ids = list(unit.get("observation_ids") or [])
    attrs_value = unit.get("attrs")
    attrs = attrs_value if isinstance(attrs_value, dict) else {}
    metrics_by_observation = attrs.get("text_line_metrics_by_observation")
    if not observation_ids or not isinstance(metrics_by_observation, dict):
        return False
    metrics = metrics_by_observation.get(str(observation_ids[0]))
    if not isinstance(metrics, dict):
        return False
    line_count = _metric_int(metrics, "line_count")
    if line_count is not None and line_count < 2:
        return False
    indent = _metric_float(metrics, "first_line_indent")
    char_width = _metric_float(metrics, "char_width")
    return indent is not None and indent >= max(_MIN_FIRST_LINE_INDENT, (char_width or 10.0) * 1.15)


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


def _observation_spans(observation: dict[str, Any]) -> list[dict[str, Any]]:
    spans = observation.get("spans")
    if isinstance(spans, list) and spans:
        return deepcopy(spans)
    bbox = observation.get("bbox")
    if _valid_bbox(bbox):
        return [{"page": observation["page"], "bbox": deepcopy(bbox)}]
    return []


def _valid_bbox(value: Any) -> TypeGuard[list[float]]:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )


def _union_bbox(left: list[float] | None, right: list[float]) -> list[float]:
    if left is None:
        return deepcopy(right)
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]


def _left_delta(left: list[float], right: list[float]) -> float:
    return abs(float(left[0]) - float(right[0]))


def _max_left_delta(bbox: list[float]) -> float:
    return max(24.0, (float(bbox[2]) - float(bbox[0])) * 0.08)


def _horizontal_overlap_ratio(left: list[float], right: list[float]) -> float:
    overlap = max(0.0, min(float(left[2]), float(right[2])) - max(float(left[0]), float(right[0])))
    width = min(float(left[2]) - float(left[0]), float(right[2]) - float(right[0]))
    return overlap / width if width > 0 else 0.0
