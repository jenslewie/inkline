"""Deterministic planning and bounded execution for note marker review."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from inkline.canonical.artifact_dag.validation import validate_bbox
from inkline.canonical.note_marker_review.contract import (
    NOTE_MARKER_REVIEW_PLAN_SCHEMA_NAME,
    NOTE_MARKER_REVIEW_PLAN_SCHEMA_VERSION,
    NOTE_MARKER_REVIEW_SCHEMA_NAME,
    NOTE_MARKER_REVIEW_SCHEMA_VERSION,
)
from inkline.canonical.note_marker_review.llm import (
    NOTE_MARKER_REVIEW_PROMPT_VERSION,
    build_note_marker_review_request,
    normalize_note_marker_review_response,
)
from inkline.canonical.note_marker_review.validation import (
    validate_note_marker_review_against_plan,
    validate_note_marker_review_plan,
    validate_note_marker_review_plan_against_sources,
)
from inkline.canonical.observed.index import ObservedIndex
from inkline.canonical.schema import ValidationError

ReviewCallback = Callable[[dict[str, Any]], Any]


def build_note_marker_review_plan(  # noqa: PLR0914
    observed_index: ObservedIndex,
    page_layout: Mapping[str, Any],
    note_system_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Build deterministic definition/reference requests from upstream evidence."""

    doc_id = observed_index.doc_id
    if page_layout.get("metadata", {}).get("doc_id") != doc_id:
        raise ValidationError("PageLayoutAnalysis doc_id differs from NoteMarkerReviewPlan")
    if note_system_review.get("metadata", {}).get("doc_id") != doc_id:
        raise ValidationError("NoteSystemReview doc_id differs from NoteMarkerReviewPlan")
    layout_pages = _layout_pages(page_layout)
    known_pages = set(observed_index.page_numbers)
    evidence_by_id = {
        evidence.get("evidence_id"): evidence
        for evidence in note_system_review.get("evidence", [])
        if isinstance(evidence, Mapping)
    }
    requests: list[dict[str, Any]] = []
    not_required: list[str] = []
    unresolved: list[str] = []
    next_request = 1
    for system in note_system_review.get("note_systems", []):
        if not isinstance(system, Mapping):
            raise ValidationError("NoteSystemReview note_systems must contain objects")
        system_id = system.get("note_system_id")
        if not isinstance(system_id, str) or not system_id:
            raise ValidationError("NoteSystemReview note system id is invalid")
        scope = system.get("reference_scope")
        pages = _range_pages(system.get("definition_ranges"))
        if scope == "unresolved" or not pages or not set(pages) <= known_pages | layout_pages:
            unresolved.append(system_id)
            continue
        definition_pages = [
            page for page in pages if page in known_pages and page in layout_pages
        ]
        candidate_pages = (
            definition_pages
            if scope == "page" or system.get("kind") == "page_footnote"
            else sorted(known_pages & layout_pages)
        )
        definition_observations = _observations_for_pages(
            observed_index, definition_pages, _is_definition_observation
        )
        reference_observations = _observations_for_pages(
            observed_index, candidate_pages, _is_reference_observation
        )
        system_evidence = _system_evidence_ids(system, evidence_by_id)
        made_request = False
        if definition_observations:
            requests.append(
                _request(
                    next_request,
                    system_id,
                    "definition",
                    definition_observations,
                    system_evidence,
                    reference_observations,
                )
            )
            next_request += 1
            made_request = True
        if reference_observations:
            requests.append(
                _request(
                    next_request,
                    system_id,
                    "reference",
                    reference_observations,
                    system_evidence,
                    definition_observations,
                )
            )
            next_request += 1
            made_request = True
        if not made_request:
            not_required.append(system_id)
    plan = {
        "metadata": {
            "schema_name": NOTE_MARKER_REVIEW_PLAN_SCHEMA_NAME,
            "schema_version": NOTE_MARKER_REVIEW_PLAN_SCHEMA_VERSION,
            "doc_id": doc_id,
        },
        "review_requests": requests,
        "not_required_note_system_ids": not_required,
        "unresolved_note_system_ids": unresolved,
    }
    validate_note_marker_review_plan_against_sources(
        plan, observed_index, page_layout, note_system_review
    )
    return plan


def build_note_marker_review(  # noqa: PLR0914
    observed_index: ObservedIndex,
    page_assets: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    review_callback: ReviewCallback | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Execute each planned request once, retaining explicit outcome states."""

    plan_value = _mutable(plan)
    validate_note_marker_review_plan(plan_value)
    assets_by_page, assets_by_id = _page_assets(page_assets)
    outcomes: list[dict[str, Any]] = []
    marker_index = 1
    for request in plan_value["review_requests"]:
        request_pages = _ordered_unique(region["page"] for region in request["regions"])
        page_asset_ids = [
            asset_id
            for page in request_pages
            for asset_id in assets_by_page.get(page, [])
        ]
        base = {
            "review_request_id": request["review_request_id"],
            "markers": [],
            "failure_reason": None,
            "model_name": None,
            "prompt_version": None,
            "page_asset_ids": page_asset_ids,
        }
        if review_callback is None or not model_name or not page_asset_ids:
            outcomes.append({**base, "status": "not_run", "page_asset_ids": []})
            continue
        observation_ids = [
            observation_id
            for region in request["regions"]
            for observation_id in region["observation_ids"]
        ]
        observations = {
            observation_id: observed_index.observations_by_id[observation_id]
            for observation_id in observation_ids
        }
        callback_request = build_note_marker_review_request(
            {**request, "page_asset_ids": page_asset_ids},
            observations=list(observations.values()),
        )
        try:
            response = normalize_note_marker_review_response(
                review_callback(callback_request), request=request, observations=observations
            )
        except Exception:
            outcomes.append(
                {
                    **base,
                    "status": "failed",
                    "model_name": model_name,
                    "prompt_version": NOTE_MARKER_REVIEW_PROMPT_VERSION,
                    "failure_reason": "model_unavailable_or_invalid",
                }
            )
            continue
        if response is None:
            outcomes.append(
                {
                    **base,
                    "status": "unresolved",
                    "model_name": model_name,
                    "prompt_version": NOTE_MARKER_REVIEW_PROMPT_VERSION,
                }
            )
            continue
        markers = []
        for marker in response["markers"]:
            markers.append(
                {
                    "marker_evidence_id": f"nmr{marker_index:06d}",
                    "note_system_id": request["note_system_id"],
                    "marker_kind": request["region_kind"],
                    **marker,
                }
            )
            marker_index += 1
        explicit_status = response.get("status")
        if markers:
            status = "found"
        elif explicit_status == "unresolved" or set(_asset_pages(page_asset_ids, assets_by_id)) != set(request_pages):
            status = "unresolved"
        else:
            status = "absent"
        outcomes.append(
            {
                **base,
                "status": status,
                "markers": markers,
                "model_name": model_name,
                "prompt_version": NOTE_MARKER_REVIEW_PROMPT_VERSION,
            }
        )
    review = {
        "metadata": {
            "schema_name": NOTE_MARKER_REVIEW_SCHEMA_NAME,
            "schema_version": NOTE_MARKER_REVIEW_SCHEMA_VERSION,
            "doc_id": observed_index.doc_id,
        },
        "outcomes": outcomes,
    }
    validate_note_marker_review_against_plan(review, plan_value, observed_index, page_assets)
    return review


def _request(
    number: int,
    system_id: str,
    region_kind: str,
    observations: Sequence[Mapping[str, Any]],
    evidence_ids: Sequence[str],
    counterpart: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    reasons = (
        ["definition_marker_unreadable"]
        if region_kind == "definition"
        else ["reference_candidate_without_definition_marker"]
    )
    if not counterpart:
        reasons.append(
            "definition_marker_without_reference_candidate"
            if region_kind == "definition"
            else "reference_candidate_without_definition_marker"
        )
    regions = [
        {
            "page": int(observation["page"]),
            "bbox": [float(value) for value in observation["bbox"]],
            "observation_ids": [str(observation["observation_id"])],
        }
        for observation in observations
    ]
    return {
        "review_request_id": f"nmp{number:06d}",
        "note_system_id": system_id,
        "region_kind": region_kind,
        "regions": regions,
        "reasons": list(dict.fromkeys(reasons)),
        "evidence_ids": list(evidence_ids),
    }


def _observations_for_pages(
    observed_index: ObservedIndex,
    pages: Sequence[int],
    predicate: Callable[[Mapping[str, Any]], bool],
) -> list[Mapping[str, Any]]:
    values: list[Mapping[str, Any]] = []
    for page in pages:
        for observation_id in observed_index.observation_ids_by_page.get(page, ()):
            observation = observed_index.observations_by_id[observation_id]
            if predicate(observation) and _valid_observation_bbox(observation):
                values.append(observation)
    return values


def _is_definition_observation(observation: Mapping[str, Any]) -> bool:
    return observation.get("kind") == "footnote_region" or observation.get("role_hint") == "footnote_text"


def _is_reference_observation(observation: Mapping[str, Any]) -> bool:
    if observation.get("role_hint") == "reference_text":
        return True
    attrs = observation.get("attrs")
    if not isinstance(attrs, Mapping):
        return False
    note_refs = attrs.get("note_refs")
    if isinstance(note_refs, Sequence) and not isinstance(note_refs, str | bytes) and note_refs:
        return True
    inline_runs = attrs.get("inline_runs")
    return (
        isinstance(inline_runs, Sequence)
        and not isinstance(inline_runs, str | bytes)
        and any(
            isinstance(run, Mapping) and run.get("type") == "note_ref"
            for run in inline_runs
        )
    )


def _range_pages(value: Any) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    pages: set[int] = set()
    for pair in value:
        if (
            isinstance(pair, Sequence)
            and not isinstance(pair, str | bytes)
            and len(pair) == 2
            and type(pair[0]) is int
            and type(pair[1]) is int
            and pair[0] <= pair[1]
        ):
            pages.update(range(pair[0], pair[1] + 1))
    return sorted(pages)


def _layout_pages(page_layout: Mapping[str, Any]) -> set[int]:
    return {
        record["page"]
        for record in page_layout.get("pages", ())
        if isinstance(record, Mapping) and type(record.get("page")) is int
    }


def _system_evidence_ids(
    system: Mapping[str, Any], evidence_by_id: Mapping[str | None, Mapping[str, Any]]
) -> list[str]:
    values = [
        evidence_id
        for evidence_id in system.get("evidence_ids", ())
        if isinstance(evidence_id, str) and evidence_id in evidence_by_id
    ]
    return values


def _valid_observation_bbox(observation: Mapping[str, Any]) -> bool:
    value = observation.get("bbox")
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return False
    try:
        validate_bbox(list(value), "observation.bbox")
    except ValidationError:
        return False
    return True


def _page_assets(
    page_assets: Mapping[str, Any],
) -> tuple[dict[int, list[str]], dict[str, Mapping[str, Any]]]:
    by_page: dict[int, list[str]] = {}
    by_id: dict[str, Mapping[str, Any]] = {}
    for record in page_assets.get("images", ()):
        if not isinstance(record, Mapping):
            continue
        image_id = record.get("image_id")
        source = record.get("source")
        page = source.get("page") if isinstance(source, Mapping) else None
        if not isinstance(image_id, str) or not image_id or type(page) is not int or page <= 0:
            continue
        if image_id in by_id:
            raise ValidationError("duplicate PageAssets image_id")
        by_id[image_id] = record
        by_page.setdefault(page, []).append(image_id)
    return by_page, by_id


def _asset_pages(asset_ids: Sequence[str], assets_by_id: Mapping[str, Mapping[str, Any]]) -> list[int]:
    pages: list[int] = []
    for asset_id in asset_ids:
        record = assets_by_id[asset_id]
        source = record.get("source")
        page = source.get("page") if isinstance(source, Mapping) else None
        if isinstance(page, int):
            pages.append(page)
    return pages


def _ordered_unique(values: Sequence[int] | Any) -> list[int]:
    result: list[int] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _mutable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_mutable(nested) for nested in value]
    return value
