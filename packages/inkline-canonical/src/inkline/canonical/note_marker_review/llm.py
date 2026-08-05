"""Bounded transport shapes for NoteMarkerReview callbacks."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

NOTE_MARKER_REVIEW_PROMPT_VERSION = "note-marker-v1"


def build_note_marker_review_request(
    request: Mapping[str, Any],
    *,
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Expose exactly one planned request to a bounded marker recognizer."""

    regions = [_mutable(region) for region in request["regions"]]
    observation_records = [_mutable(observation) for observation in observations]
    observation_ids = _request_observation_ids(request)
    payload = {
        "review_request_id": request["review_request_id"],
        "note_system_id": request["note_system_id"],
        "region_kind": request["region_kind"],
        "regions": regions,
        "pages": _ordered_unique(region["page"] for region in regions),
        "observation_ids": observation_ids,
        "observations": observation_records,
        "page_asset_ids": list(request.get("page_asset_ids", [])),
    }
    payload["prompt_version"] = NOTE_MARKER_REVIEW_PROMPT_VERSION
    payload["prompt"] = _prompt(payload)
    return payload


def normalize_note_marker_review_response(
    value: Any,
    *,
    request: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Accept only complete marker decisions bounded by the supplied request."""

    if not isinstance(value, Mapping):
        return None
    if set(value) not in ({"markers"}, {"status", "markers"}):
        return None
    markers_value = value.get("markers")
    if not isinstance(markers_value, Sequence) or isinstance(markers_value, str | bytes):
        return None
    status = value.get("status")
    if status is not None and status not in {"found", "absent", "unresolved"}:
        return None
    expected_ids = set(_request_observation_ids(request))
    expected_pages = {
        region["page"] for region in request["regions"] if isinstance(region, Mapping)
    }
    normalized: list[dict[str, Any]] = []
    for marker in markers_value:
        normalized_marker = _normalize_marker(marker, request, observations, expected_ids)
        if normalized_marker is None:
            return None
        if normalized_marker["page"] not in expected_pages:
            return None
        normalized.append(normalized_marker)
    if status == "found" and not normalized:
        return None
    if status in {"absent", "unresolved"} and normalized:
        return None
    return {"status": status, "markers": normalized}


def _prompt(request: Mapping[str, Any]) -> str:
    return (
        "Review only this one planned note-marker request. Locate printed "
        f"{request['region_kind']} markers using only the supplied observations, "
        "regions, and page assets. Do not infer note targets, sections, chronology, "
        "or ids. Return JSON {'markers': [...]} with marker, page, observation_id, "
        "bbox, adjacent_text, and confidence; return an empty markers list only "
        "when the supplied assets cover every planned page and no marker is visible. "
        f"Request: {request['review_request_id']}; observations: "
        f"{json.dumps(request['observations'], ensure_ascii=False)}."
    )


def _normalize_marker(
    value: Any,
    request: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
    expected_ids: set[str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    allowed = {
        "marker",
        "page",
        "observation_id",
        "bbox",
        "adjacent_text",
        "confidence",
        "evidence_ids",
    }
    if not set(value) <= allowed or not {"marker", "page", "observation_id", "bbox", "adjacent_text", "confidence"} <= set(value):
        return None
    marker = value.get("marker")
    observation_id = value.get("observation_id")
    page = value.get("page")
    adjacent_text = value.get("adjacent_text")
    confidence = value.get("confidence")
    bbox = value.get("bbox")
    if (
        not isinstance(marker, str)
        or not marker
        or not isinstance(observation_id, str)
        or observation_id not in expected_ids
        or type(page) is not int
        or page <= 0
        or not isinstance(adjacent_text, str)
        or not adjacent_text
        or confidence not in {"low", "medium", "high"}
        or not _valid_bbox(bbox)
    ):
        return None
    observation = observations.get(observation_id)
    if observation is None or observation.get("page") != page:
        return None
    evidence_ids = value.get("evidence_ids", request["evidence_ids"])
    if (
        not isinstance(evidence_ids, Sequence)
        or isinstance(evidence_ids, str | bytes)
        or not evidence_ids
        or not all(isinstance(item, str) and item for item in evidence_ids)
        or len(evidence_ids) != len(set(evidence_ids))
        or not set(evidence_ids) <= set(request["evidence_ids"])
    ):
        return None
    assert isinstance(bbox, Sequence) and not isinstance(bbox, str | bytes)
    return {
        "marker": marker,
        "page": page,
        "observation_id": observation_id,
        "bbox": [float(coordinate) for coordinate in bbox],
        "adjacent_text": adjacent_text,
        "confidence": confidence,
        "evidence_ids": list(evidence_ids),
    }


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, str | bytes)
        and len(value) == 4
        and all(isinstance(coordinate, int | float) and not isinstance(coordinate, bool) and math.isfinite(float(coordinate)) for coordinate in value)
        and float(value[0]) <= float(value[2])
        and float(value[1]) <= float(value[3])
    )


def _ordered_unique(values: Sequence[int] | Any) -> list[int]:
    result: list[int] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _request_observation_ids(request: Mapping[str, Any]) -> list[str]:
    return [
        observation_id
        for region in request["regions"]
        for observation_id in region["observation_ids"]
    ]


def _mutable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_mutable(nested) for nested in value]
    return value
