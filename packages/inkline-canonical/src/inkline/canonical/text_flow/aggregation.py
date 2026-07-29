from __future__ import annotations

from copy import deepcopy
from typing import Any, TypeGuard


def aggregate_text_candidates(
    candidates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return homogeneous logical records without unit ids."""

    del pages
    records: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    protected_groups: dict[str, tuple[str, ...]] = {}
    for candidate in candidates:
        _record_protected_group(candidate, protected_groups)
        if records and _same_homogeneous_display_run(previous, candidate):
            _append_candidate(records[-1], candidate)
        else:
            records.append(_record_from_candidate(candidate))
        previous = candidate
    _materialize_exact_anchor_groups(records, protected_groups)
    return records


def materialize_text_units(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy logical records and assign contiguous final tu ids exactly once."""

    if any("unit_id" in record for record in records):
        raise ValueError("logical record already has unit_id")
    units = deepcopy(records)
    for index, unit in enumerate(units, start=1):
        unit["unit_id"] = f"tu{index:06d}"
    return units


def _record_protected_group(
    candidate: dict[str, Any], protected_groups: dict[str, tuple[str, ...]]
) -> None:
    group = candidate.get("protected_anchor_group")
    if not isinstance(group, list) or not all(isinstance(item, str) for item in group):
        return
    protected_groups[str(candidate["observation_id"])] = tuple(group)


def _same_homogeneous_display_run(
    previous: dict[str, Any] | None, candidate: dict[str, Any]
) -> bool:
    if previous is None or int(previous["page"]) != int(candidate["page"]):
        return False
    if previous.get("protected_anchor_group") or candidate.get("protected_anchor_group"):
        return False
    previous_decision = _layout_decision(previous)
    decision = _layout_decision(candidate)
    if previous_decision is None or decision is None:
        return False
    if (
        previous_decision.get("classified_type") != "display_block"
        or decision.get("classified_type") != "display_block"
        or previous_decision.get("status") != "resolved"
        or decision.get("status") != "resolved"
    ):
        return False
    previous_layout_form = previous_decision.get("layout_form")
    layout_form = decision.get("layout_form")
    previous_alignment = previous_decision.get("alignment")
    alignment = decision.get("alignment")
    if not all(
        isinstance(value, str) and value
        for value in (previous_layout_form, layout_form, previous_alignment, alignment)
    ):
        return False
    if previous_layout_form != layout_form or previous_alignment != alignment:
        return False
    run_ids = _run_observation_ids(decision)
    return run_ids is not None and run_ids == _run_observation_ids(previous_decision)


def _layout_decision(candidate: dict[str, Any]) -> dict[str, Any] | None:
    decision = candidate.get("layout_decision")
    return decision if isinstance(decision, dict) else None


def _run_observation_ids(decision: dict[str, Any]) -> list[str] | None:
    run_ids = decision.get("same_page_run_observation_ids")
    if not isinstance(run_ids, list) or not all(isinstance(value, str) for value in run_ids):
        return None
    return run_ids


def _record_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    decision = _layout_decision(candidate)
    if decision is None:
        raise ValueError("classified candidate is missing layout_decision")
    unit_type = str(decision["classified_type"])
    attrs = deepcopy(_attrs(candidate))
    alignment = decision.get("alignment")
    if unit_type == "display_block" and isinstance(alignment, str) and alignment:
        attrs["alignment"] = alignment
    if unit_type in {"paragraph", "display_block"}:
        attrs["layout_fragments"] = [_layout_fragment(candidate, decision)]
    return {
        "unit_type": unit_type,
        "text": str(candidate.get("text") or ""),
        "page": candidate["page"],
        "pages": [candidate["page"]],
        "bbox": deepcopy(candidate.get("bbox")),
        "spans": deepcopy(candidate.get("spans") or []),
        "observation_ids": [str(candidate["observation_id"])],
        "role_hints": [str(candidate.get("role_hint") or "")],
        "attrs": attrs,
        "parser_payloads": [deepcopy(candidate.get("parser_payload") or {})],
    }


def _attrs(candidate: dict[str, Any]) -> dict[str, Any]:
    attrs = candidate.get("attrs")
    return attrs if isinstance(attrs, dict) else {}


def _layout_fragment(candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": str(candidate["observation_id"]),
        "page": candidate["page"],
        "classified_type": decision["classified_type"],
        "status": decision["status"],
        "layout_form": decision["layout_form"],
        "signals": deepcopy(decision["signals"]),
    }


def _append_candidate(record: dict[str, Any], candidate: dict[str, Any]) -> None:
    source_text = str(candidate.get("text") or "")
    if source_text:
        target_text = str(record.get("text") or "")
        record["text"] = f"{target_text}\n{source_text}" if target_text else source_text
    page = candidate["page"]
    if page not in record["pages"]:
        record["pages"].append(page)
    candidate_bbox = candidate.get("bbox")
    if (
        int(record["page"]) == int(page)
        and _valid_bbox(record.get("bbox"))
        and _valid_bbox(candidate_bbox)
    ):
        record["bbox"] = _union_bbox(record["bbox"], candidate_bbox)
    record["spans"].extend(deepcopy(candidate.get("spans") or []))
    record["observation_ids"].append(str(candidate["observation_id"]))
    role_hint = str(candidate.get("role_hint") or "")
    if role_hint not in record["role_hints"]:
        record["role_hints"].append(role_hint)
    record["parser_payloads"].append(deepcopy(candidate.get("parser_payload") or {}))
    _merge_candidate_attrs(record["attrs"], _attrs(candidate))
    decision = _layout_decision(candidate)
    if record["unit_type"] in {"paragraph", "display_block"} and decision is not None:
        record["attrs"]["layout_fragments"].append(_layout_fragment(candidate, decision))


def _merge_candidate_attrs(target: dict[str, Any], source: dict[str, Any]) -> None:
    for field, value in source.items():
        if field == "layout_fragments":
            continue
        if field not in target:
            target[field] = deepcopy(value)
        elif isinstance(target[field], dict) and isinstance(value, dict):
            target[field].update(deepcopy(value))
        elif isinstance(target[field], list) and isinstance(value, list):
            target[field].extend(deepcopy(value))


def _materialize_exact_anchor_groups(
    records: list[dict[str, Any]], protected_groups: dict[str, tuple[str, ...]]
) -> None:
    for group in dict.fromkeys(protected_groups.values()):
        _materialize_exact_anchor_group(records, group, protected_groups)


def _materialize_exact_anchor_group(
    records: list[dict[str, Any]],
    group: tuple[str, ...],
    protected_groups: dict[str, tuple[str, ...]],
) -> None:
    positions = [
        index
        for index, record in enumerate(records)
        if any(observation_id in group for observation_id in record["observation_ids"])
    ]
    if not positions or positions != list(range(positions[0], positions[-1] + 1)):
        return
    fragments = records[positions[0] : positions[-1] + 1]
    observation_ids = [
        observation_id for fragment in fragments for observation_id in fragment["observation_ids"]
    ]
    if observation_ids != list(group) or any(
        protected_groups.get(observation_id) != group for observation_id in observation_ids
    ):
        return
    keeper = fragments[0]
    keeper["unit_type"] = "heading"
    for fragment in fragments[1:]:
        _append_record_fragment(keeper, fragment)
    records[positions[0] : positions[-1] + 1] = [keeper]


def _append_record_fragment(target: dict[str, Any], source: dict[str, Any]) -> None:
    source_text = str(source.get("text") or "")
    if source_text:
        target_text = str(target.get("text") or "")
        target["text"] = f"{target_text}\n{source_text}" if target_text else source_text
    for page in source["pages"]:
        if page not in target["pages"]:
            target["pages"].append(page)
    if _valid_bbox(target.get("bbox")) and _valid_bbox(source.get("bbox")):
        target["bbox"] = _union_bbox(target["bbox"], source["bbox"])
    target["spans"].extend(deepcopy(source["spans"]))
    target["observation_ids"].extend(source["observation_ids"])
    for role_hint in source["role_hints"]:
        if role_hint not in target["role_hints"]:
            target["role_hints"].append(role_hint)
    target["parser_payloads"].extend(deepcopy(source["parser_payloads"]))
    _merge_candidate_attrs(target["attrs"], source["attrs"])
    target["attrs"].pop("layout_fragments", None)


def _valid_bbox(value: Any) -> TypeGuard[list[float]]:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )


def _union_bbox(left: list[float], right: list[float]) -> list[float]:
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]
