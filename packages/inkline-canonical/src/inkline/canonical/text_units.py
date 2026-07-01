from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from inkline.canonical.observed import validate_observed_document

TEXT_UNIT_TYPES = {"heading", "paragraph", "list_item", "footnote"}


def build_text_units(document: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    validate_observed_document(document)
    units: list[dict[str, Any]] = []
    ignored_counts: Counter[str] = Counter()

    for observation in _ordered_observations(document["observations"]):
        unit_type = _unit_type(observation)
        if unit_type is None:
            ignored_counts[str(observation["kind"])] += 1
            continue
        if units and _can_merge(units[-1], observation, unit_type):
            _merge_observation(units[-1], observation)
            continue
        units.append(_unit_from_observation(observation, len(units) + 1, unit_type))

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


def _reading_order(observation: dict[str, Any]) -> int:
    attrs = observation.get("attrs") if isinstance(observation.get("attrs"), dict) else {}
    value = attrs.get("reading_order")
    return int(value) if isinstance(value, int) else 999999


def _unit_type(observation: dict[str, Any]) -> str | None:
    role_hint = observation["role_hint"]
    if role_hint == "title_text":
        return "heading"
    if role_hint == "body_text":
        return "paragraph"
    if role_hint == "list_text":
        return "list_item"
    if observation["kind"] == "footnote_region" or role_hint == "footnote_text":
        return "footnote"
    return None


def _unit_from_observation(
    observation: dict[str, Any], index: int, unit_type: str
) -> dict[str, Any]:
    bbox = deepcopy(observation.get("bbox"))
    return {
        "unit_id": f"tu{index:06d}",
        "unit_type": unit_type,
        "text": str(observation.get("text") or ""),
        "page": observation["page"],
        "pages": [observation["page"]],
        "bbox": bbox,
        "spans": deepcopy(observation.get("spans") or []),
        "observation_ids": [observation["observation_id"]],
        "role_hints": [observation["role_hint"]],
        "attrs": _unit_attrs(observation),
        "parser_payloads": [deepcopy(observation.get("parser_payload") or {})],
    }


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


def _can_merge(
    previous_unit: dict[str, Any], observation: dict[str, Any], unit_type: str
) -> bool:
    if unit_type != "paragraph" or previous_unit["unit_type"] != "paragraph":
        return False
    if previous_unit["page"] != observation["page"]:
        return False
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


def _merge_observation(unit: dict[str, Any], observation: dict[str, Any]) -> None:
    text = str(observation.get("text") or "")
    if text:
        unit["text"] = f"{unit['text']}\n{text}" if unit["text"] else text
    bbox = observation.get("bbox")
    if _valid_bbox(unit.get("bbox")) and _valid_bbox(bbox):
        unit["bbox"] = _union_bbox(unit["bbox"], bbox)
    unit["spans"].extend(deepcopy(observation.get("spans") or []))
    unit["observation_ids"].append(observation["observation_id"])
    if observation["role_hint"] not in unit["role_hints"]:
        unit["role_hints"].append(observation["role_hint"])
    unit["parser_payloads"].append(deepcopy(observation.get("parser_payload") or {}))
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
    return isinstance(value, list) and len(value) == 4 and all(
        isinstance(number, int | float) for number in value
    )


def _bbox_top(value: Any) -> float:
    return float(value[1]) if _valid_bbox(value) else 999999.0


def _bbox_left(value: Any) -> float:
    return float(value[0]) if _valid_bbox(value) else 999999.0


def _vertical_gap(left: list[float], right: list[float]) -> float:
    return float(right[1]) - float(left[3])


def _max_vertical_gap(bbox: list[float]) -> float:
    return max(24.0, (float(bbox[3]) - float(bbox[1])) * 1.5)


def _left_delta(left: list[float], right: list[float]) -> float:
    return abs(float(left[0]) - float(right[0]))


def _max_left_delta(bbox: list[float]) -> float:
    return max(24.0, (float(bbox[2]) - float(bbox[0])) * 0.08)


def _horizontal_overlap_ratio(left: list[float], right: list[float]) -> float:
    overlap = max(0.0, min(float(left[2]), float(right[2])) - max(float(left[0]), float(right[0])))
    width = min(float(left[2]) - float(left[0]), float(right[2]) - float(right[0]))
    if width <= 0:
        return 0.0
    return overlap / width


def _union_bbox(left: list[float], right: list[float]) -> list[float]:
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]
