"""Lossless merge primitives shared by TextFlow reconcilers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, TypeGuard


def merge_records(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    reason: str,
    joiner: str,
    interruptions: list[dict[str, Any]],
    boundary_evidence: dict[str, Any] | None = None,
) -> None:
    """Merge right into left while preserving all source and audit evidence."""

    left_ids = _string_list(left.get("observation_ids"))
    right_ids = _string_list(right.get("observation_ids"))
    event = {
        "reason": reason,
        "left_page": _boundary_page(left, from_right=True),
        "right_page": _boundary_page(right, from_right=False),
        "left_observation_ids": deepcopy(left_ids),
        "right_observation_ids": deepcopy(right_ids),
        "interrupting_observation_ids": [
            observation_id
            for record in interruptions
            for observation_id in _string_list(record.get("observation_ids"))
        ],
    }
    if boundary_evidence is not None:
        event["boundary_evidence"] = deepcopy(boundary_evidence)

    _merge_text(left, right, joiner)
    _extend_unique(left, right, "pages")
    _merge_bbox(left, right)
    _extend_collection(left, right, "spans")
    _extend_collection(left, right, "observation_ids")
    _extend_unique(left, right, "role_hints")
    _extend_collection(left, right, "parser_payloads")
    attrs = _attrs(left)
    source_attrs = _source_attrs(right)
    _merge_inline_runs(attrs, source_attrs, joiner=joiner)
    _merge_attrs(
        attrs,
        {field: value for field, value in source_attrs.items() if field != "inline_runs"},
    )
    attrs.setdefault("merge_events", []).append(event)


def _merge_text(left: dict[str, Any], right: dict[str, Any], joiner: str) -> None:
    left_text = str(left.get("text") or "")
    right_text = str(right.get("text") or "")
    if left_text and right_text:
        left["text"] = f"{left_text}{joiner}{right_text}"
    elif right_text:
        left["text"] = right_text
    else:
        left["text"] = left_text


def _extend_collection(left: dict[str, Any], right: dict[str, Any], field: str) -> None:
    target = left.get(field)
    if not isinstance(target, list):
        target = []
        left[field] = target
    source = right.get(field)
    if isinstance(source, list):
        target.extend(deepcopy(source))


def _extend_unique(left: dict[str, Any], right: dict[str, Any], field: str) -> None:
    target = left.get(field)
    if not isinstance(target, list):
        target = []
        left[field] = target
    source = right.get(field)
    if not isinstance(source, list):
        return
    for value in source:
        if value not in target:
            target.append(deepcopy(value))


def _merge_bbox(left: dict[str, Any], right: dict[str, Any]) -> None:
    if (
        _boundary_page(left, from_right=False) != _boundary_page(right, from_right=False)
        or not _valid_bbox(left.get("bbox"))
        or not _valid_bbox(right.get("bbox"))
    ):
        return
    left_bbox = left["bbox"]
    right_bbox = right["bbox"]
    left["bbox"] = [
        min(float(left_bbox[0]), float(right_bbox[0])),
        min(float(left_bbox[1]), float(right_bbox[1])),
        max(float(left_bbox[2]), float(right_bbox[2])),
        max(float(left_bbox[3]), float(right_bbox[3])),
    ]


def _attrs(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("attrs")
    if isinstance(value, dict):
        return value
    attrs: dict[str, Any] = {}
    record["attrs"] = attrs
    return attrs


def _source_attrs(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("attrs")
    return value if isinstance(value, dict) else {}


def _merge_attrs(target: dict[str, Any], source: dict[str, Any]) -> None:
    conflicts: list[dict[str, Any]] = []
    _merge_attr_mapping(target, source, path=(), conflicts=conflicts)
    if conflicts:
        target.setdefault("attribute_merge_conflicts", []).extend(conflicts)


def _merge_inline_runs(
    target: dict[str, Any],
    source: dict[str, Any],
    *,
    joiner: str,
) -> None:
    """Merge inline provenance while joining only a continuous text boundary."""

    source_runs = source.get("inline_runs")
    if not isinstance(source_runs, list):
        return
    target_runs = target.get("inline_runs")
    if not isinstance(target_runs, list):
        target["inline_runs"] = deepcopy(source_runs)
        return
    copied = deepcopy(source_runs)
    if (
        joiner == ""
        and target_runs
        and copied
        and _text_inline_run(target_runs[-1])
        and _text_inline_run(copied[0])
    ):
        target_runs[-1]["text"] = (
            str(target_runs[-1].get("text") or "")
            + str(copied[0].get("text") or "")
        )
        copied = copied[1:]
    target_runs.extend(copied)


def _text_inline_run(value: Any) -> TypeGuard[dict[str, Any]]:
    return (
        isinstance(value, dict)
        and value.get("type") == "text"
        and isinstance(value.get("text"), str)
    )


def _merge_attr_mapping(
    target: dict[str, Any],
    source: dict[str, Any],
    *,
    path: tuple[str, ...],
    conflicts: list[dict[str, Any]],
) -> None:
    for field, source_value in source.items():
        if field not in target:
            target[field] = deepcopy(source_value)
            continue
        target_value = target[field]
        if isinstance(target_value, list) and isinstance(source_value, list):
            target_value.extend(deepcopy(source_value))
        elif isinstance(target_value, dict) and isinstance(source_value, dict):
            _merge_attr_mapping(
                target_value,
                source_value,
                path=(*path, field),
                conflicts=conflicts,
            )
        elif target_value != source_value:
            conflicts.append(
                {
                    "path": ".".join((*path, field)),
                    "left": deepcopy(target_value),
                    "right": deepcopy(source_value),
                }
            )


def _boundary_page(record: dict[str, Any], *, from_right: bool) -> int | Any:
    pages = record.get("pages")
    if isinstance(pages, list) and pages:
        return pages[-1] if from_right else pages[0]
    return record.get("page")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _valid_bbox(value: Any) -> TypeGuard[list[float]]:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )
