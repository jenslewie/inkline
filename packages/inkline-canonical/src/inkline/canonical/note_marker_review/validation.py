from __future__ import annotations

from typing import Any

from inkline.canonical.artifact_dag.validation import (
    validate_bbox,
    validate_choice,
    validate_confidence,
    validate_exact_fields,
    validate_id_list,
    validate_metadata,
    validate_non_empty_string,
    validate_nullable_string,
    validate_ordered_ids,
    validate_string_choices,
)
from inkline.canonical.note_marker_review.contract import (
    MARKER_FIELDS,
    MARKER_OUTCOME_STATUSES,
    MARKER_REGION_KINDS,
    MARKER_REVIEW_REASONS,
    NOTE_MARKER_REVIEW_PLAN_SCHEMA_NAME,
    NOTE_MARKER_REVIEW_PLAN_SCHEMA_VERSION,
    NOTE_MARKER_REVIEW_SCHEMA_NAME,
    NOTE_MARKER_REVIEW_SCHEMA_VERSION,
    OUTCOME_FIELDS,
    PLAN_TOP_LEVEL_FIELDS,
    REVIEW_REGION_FIELDS,
    REVIEW_REQUEST_FIELDS,
    REVIEW_TOP_LEVEL_FIELDS,
)
from inkline.canonical.observed.index import ObservedIndex
from inkline.canonical.schema import ValidationError


def validate_note_marker_review_plan(plan: dict[str, Any]) -> None:
    """Validate bounded review work and the explicit note-system partition."""

    validate_exact_fields(plan, PLAN_TOP_LEVEL_FIELDS, "note_marker_review_plan")
    validate_metadata(
        plan["metadata"],
        schema_name=NOTE_MARKER_REVIEW_PLAN_SCHEMA_NAME,
        schema_version=NOTE_MARKER_REVIEW_PLAN_SCHEMA_VERSION,
        path="note_marker_review_plan.metadata",
    )
    requests = validate_ordered_ids(
        plan["review_requests"],
        id_field="review_request_id",
        prefix="nmp",
        path="note_marker_review_plan.review_requests",
    )
    request_systems: set[str] = set()
    for index, request in enumerate(requests):
        path = f"note_marker_review_plan.review_requests[{index}]"
        validate_exact_fields(request, REVIEW_REQUEST_FIELDS, path)
        request_systems.add(
            validate_non_empty_string(request["note_system_id"], f"{path}.note_system_id")
        )
        validate_choice(request["region_kind"], MARKER_REGION_KINDS, f"{path}.region_kind")
        _validate_regions(request["regions"], path)
        validate_string_choices(request["reasons"], MARKER_REVIEW_REASONS, f"{path}.reasons")
        validate_id_list(request["evidence_ids"], f"{path}.evidence_ids", required=True)
    not_required = set(
        validate_id_list(
            plan["not_required_note_system_ids"],
            "note_marker_review_plan.not_required_note_system_ids",
        )
    )
    unresolved = set(
        validate_id_list(
            plan["unresolved_note_system_ids"],
            "note_marker_review_plan.unresolved_note_system_ids",
        )
    )
    if request_systems & not_required or request_systems & unresolved or not_required & unresolved:
        raise ValidationError("note systems must occupy one marker-plan state")


def validate_note_marker_review_plan_against_sources(
    plan: dict[str, Any],
    observed_index: ObservedIndex,
    page_layout: dict[str, Any],
    note_system_review: dict[str, Any],
) -> None:
    """Validate complete note-system coverage and bounded source regions."""

    validate_note_marker_review_plan(plan)
    doc_id = plan["metadata"]["doc_id"]
    for name, source_doc_id in (
        ("ObservedIndex", observed_index.doc_id),
        ("PageLayoutAnalysis", page_layout.get("metadata", {}).get("doc_id")),
        ("NoteSystemReview", note_system_review.get("metadata", {}).get("doc_id")),
    ):
        if source_doc_id != doc_id:
            raise ValidationError(f"{name} doc_id differs from NoteMarkerReviewPlan")
    known_systems = {
        system["note_system_id"] for system in note_system_review.get("note_systems", [])
    }
    planned_systems = {
        request["note_system_id"] for request in plan["review_requests"]
    } | set(plan["not_required_note_system_ids"]) | set(plan["unresolved_note_system_ids"])
    if planned_systems != known_systems:
        raise ValidationError("NoteMarkerReviewPlan must partition every note system")
    known_pages = set(observed_index.page_numbers)
    known_observations = observed_index.observations_by_id
    for request in plan["review_requests"]:
        for region in request["regions"]:
            if region["page"] not in known_pages:
                raise ValidationError("marker review region references unknown page")
            for observation_id in region["observation_ids"]:
                observation = known_observations.get(observation_id)
                if observation is None or observation.get("page") != region["page"]:
                    raise ValidationError("marker review region observation is invalid")


def validate_note_marker_review(review: dict[str, Any]) -> None:
    """Validate per-request result states and localized marker evidence."""

    validate_exact_fields(review, REVIEW_TOP_LEVEL_FIELDS, "note_marker_review")
    validate_metadata(
        review["metadata"],
        schema_name=NOTE_MARKER_REVIEW_SCHEMA_NAME,
        schema_version=NOTE_MARKER_REVIEW_SCHEMA_VERSION,
        path="note_marker_review.metadata",
    )
    outcomes = review["outcomes"]
    if not isinstance(outcomes, list):
        raise ValidationError("note_marker_review.outcomes must be list")
    request_ids: set[str] = set()
    marker_index = 0
    for index, outcome in enumerate(outcomes):
        path = f"note_marker_review.outcomes[{index}]"
        validate_exact_fields(outcome, OUTCOME_FIELDS, path)
        request_id = validate_non_empty_string(
            outcome["review_request_id"], f"{path}.review_request_id"
        )
        if request_id in request_ids:
            raise ValidationError("NoteMarkerReview must have one outcome per request")
        request_ids.add(request_id)
        status = validate_choice(
            outcome["status"], MARKER_OUTCOME_STATUSES, f"{path}.status"
        )
        markers, marker_index = _validate_markers(outcome["markers"], marker_index, path)
        failure_reason = validate_nullable_string(
            outcome["failure_reason"], f"{path}.failure_reason"
        )
        model_name = validate_nullable_string(outcome["model_name"], f"{path}.model_name")
        prompt_version = validate_nullable_string(
            outcome["prompt_version"], f"{path}.prompt_version"
        )
        _validate_outcome_state(
            status, markers, failure_reason, model_name, prompt_version, path
        )


def validate_note_marker_review_against_plan(
    review: dict[str, Any],
    plan: dict[str, Any],
    observed_index: ObservedIndex,
) -> None:
    """Validate request coverage, region containment, text anchors, and provenance."""

    validate_note_marker_review(review)
    validate_note_marker_review_plan(plan)
    if review["metadata"]["doc_id"] != plan["metadata"]["doc_id"]:
        raise ValidationError("NoteMarkerReview and plan doc_id values differ")
    requests = {
        request["review_request_id"]: request for request in plan["review_requests"]
    }
    outcomes = {outcome["review_request_id"]: outcome for outcome in review["outcomes"]}
    if set(outcomes) != set(requests):
        raise ValidationError("NoteMarkerReview must cover every planned request exactly once")
    for request_id, outcome in outcomes.items():
        request = requests[request_id]
        for marker in outcome["markers"]:
            if marker["note_system_id"] != request["note_system_id"]:
                raise ValidationError("marker evidence note_system_id differs from plan")
            if marker["marker_kind"] != request["region_kind"]:
                raise ValidationError("marker evidence kind differs from planned region")
            _validate_marker_against_regions(marker, request["regions"])
            observation = observed_index.observations_by_id.get(marker["observation_id"])
            if observation is None or observation.get("page") != marker["page"]:
                raise ValidationError("marker evidence observation is invalid")
            adjacent_text = marker["adjacent_text"]
            if adjacent_text and adjacent_text not in str(observation.get("text") or ""):
                raise ValidationError("marker adjacent_text is not anchored in observation")


def _validate_regions(value: Any, request_path: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{request_path}.regions must be non-empty list")
    for index, region in enumerate(value):
        path = f"{request_path}.regions[{index}]"
        validate_exact_fields(region, REVIEW_REGION_FIELDS, path)
        if type(region["page"]) is not int or region["page"] <= 0:
            raise ValidationError(f"{path}.page is invalid")
        validate_bbox(region["bbox"], f"{path}.bbox")
        validate_id_list(region["observation_ids"], f"{path}.observation_ids", required=True)


def _validate_markers(
    value: Any, marker_index: int, outcome_path: str
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list):
        raise ValidationError(f"{outcome_path}.markers must be list")
    for local_index, marker in enumerate(value):
        path = f"{outcome_path}.markers[{local_index}]"
        validate_exact_fields(marker, MARKER_FIELDS, path)
        marker_index += 1
        if marker["marker_evidence_id"] != f"nmr{marker_index:06d}":
            raise ValidationError("marker evidence ids must be ordered contiguous nmr ids")
        validate_non_empty_string(marker["note_system_id"], f"{path}.note_system_id")
        validate_choice(marker["marker_kind"], MARKER_REGION_KINDS, f"{path}.marker_kind")
        validate_non_empty_string(marker["marker"], f"{path}.marker")
        if type(marker["page"]) is not int or marker["page"] <= 0:
            raise ValidationError(f"{path}.page is invalid")
        validate_non_empty_string(marker["observation_id"], f"{path}.observation_id")
        validate_bbox(marker["bbox"], f"{path}.bbox")
        if not isinstance(marker["adjacent_text"], str):
            raise ValidationError(f"{path}.adjacent_text must be string")
        validate_id_list(marker["evidence_ids"], f"{path}.evidence_ids", required=True)
        validate_confidence(marker["confidence"], f"{path}.confidence")
    return value, marker_index


def _validate_outcome_state(
    status: str,
    markers: list[dict[str, Any]],
    failure_reason: str | None,
    model_name: str | None,
    prompt_version: str | None,
    path: str,
) -> None:
    if status == "found" and not markers:
        raise ValidationError(f"{path} found status requires marker evidence")
    if status != "found" and markers:
        raise ValidationError(f"{path} non-found status must not contain markers")
    if status == "failed" and failure_reason is None:
        raise ValidationError(f"{path} failed status requires failure_reason")
    if status != "failed" and failure_reason is not None:
        raise ValidationError(f"{path} failure_reason is only valid for failed status")
    if status == "not_run":
        if model_name is not None or prompt_version is not None:
            raise ValidationError(f"{path} not_run status must not claim model provenance")
    elif model_name is None or prompt_version is None:
        raise ValidationError(f"{path} executed status requires model provenance")


def _validate_marker_against_regions(
    marker: dict[str, Any], regions: list[dict[str, Any]]
) -> None:
    marker_bbox = marker["bbox"]
    for region in regions:
        if (
            region["page"] == marker["page"]
            and marker["observation_id"] in region["observation_ids"]
            and _bbox_contains(region["bbox"], marker_bbox)
        ):
            return
    raise ValidationError("marker evidence lies outside planned region")


def _bbox_contains(container: list[float], nested: list[float]) -> bool:
    return (
        float(container[0]) <= float(nested[0])
        and float(container[1]) <= float(nested[1])
        and float(container[2]) >= float(nested[2])
        and float(container[3]) >= float(nested[3])
    )
