from __future__ import annotations

from typing import Any

from inkline.canonical.artifact_dag.validation import (
    validate_choice,
    validate_confidence,
    validate_doc_ids,
    validate_exact_fields,
    validate_id_list,
    validate_metadata,
    validate_nullable_string,
    validate_ordered_ids,
    validate_pages,
    validate_ranges,
    validate_reason,
    validate_string_choices,
)
from inkline.canonical.note_system.contract import (
    EVIDENCE_FIELDS,
    NOTE_MARKER_STYLES,
    NOTE_REFERENCE_SCOPES,
    NOTE_RESET_POLICIES,
    NOTE_SYSTEM_EVIDENCE_SOURCES,
    NOTE_SYSTEM_FIELDS,
    NOTE_SYSTEM_KINDS,
    NOTE_SYSTEM_REVIEW_SCHEMA_NAME,
    NOTE_SYSTEM_REVIEW_SCHEMA_VERSION,
    TOP_LEVEL_FIELDS,
    UNRESOLVED_SYSTEM_FIELDS,
)
from inkline.canonical.observed.index import ObservedIndex
from inkline.canonical.schema import ValidationError

_KIND_SCOPE_POLICIES = {
    "page_footnote": {("page", "page")},
    "chapter_endnote": {("chapter", "chapter")},
    "book_endnote": {("book", "book"), ("chapter", "chapter")},
}


def validate_note_system_review(review: dict[str, Any]) -> None:
    """Validate separate, evidence-backed note-system declarations."""

    validate_exact_fields(review, TOP_LEVEL_FIELDS, "note_system_review")
    validate_metadata(
        review["metadata"],
        schema_name=NOTE_SYSTEM_REVIEW_SCHEMA_NAME,
        schema_version=NOTE_SYSTEM_REVIEW_SCHEMA_VERSION,
        path="note_system_review.metadata",
    )
    evidence_ids = _validate_evidence(review["evidence"])
    _validate_systems(review["note_systems"], evidence_ids)
    _validate_unresolved(review["unresolved_system_candidates"], evidence_ids)


def validate_note_system_review_against_sources(
    review: dict[str, Any],
    observed_index: ObservedIndex,
    page_layout: dict[str, Any],
    skeleton: dict[str, Any],
    page_review: dict[str, Any],
    page_assets: dict[str, Any],
) -> None:
    """Validate note-system evidence ids and ranges against immutable sources."""

    validate_note_system_review(review)
    doc_id = review["metadata"]["doc_id"]
    if observed_index.doc_id != doc_id:
        raise ValidationError("ObservedIndex doc_id differs from NoteSystemReview")
    validate_doc_ids(
        doc_id,
        {
            "PageLayoutAnalysis": page_layout,
            "BookSkeleton": skeleton,
            "PageReview": page_review,
        },
    )
    known_pages = set(observed_index.page_numbers)
    known_observations = set(observed_index.observations_by_id)
    known_entry_indexes = {
        entry.get("entry_index")
        for entry in skeleton.get("toc_entries", [])
        if isinstance(entry, dict)
    }
    assets_by_id = _page_assets_by_id(page_assets)
    for evidence in review["evidence"]:
        if not set(evidence["pages"]) <= known_pages:
            raise ValidationError("note-system evidence references unknown page")
        if not set(evidence["observation_ids"]) <= known_observations:
            raise ValidationError("note-system evidence references unknown observation")
        if any(
            observed_index.observations_by_id[observation_id].get("page")
            not in evidence["pages"]
            for observation_id in evidence["observation_ids"]
        ):
            raise ValidationError("note-system evidence observation differs from evidence pages")
        if not set(evidence["skeleton_entry_indexes"]) <= known_entry_indexes:
            raise ValidationError("note-system evidence references unknown Skeleton entry")
        for asset_id in evidence["page_asset_ids"]:
            if assets_by_id.get(asset_id) not in evidence["pages"]:
                raise ValidationError("note-system evidence references invalid PageAssets image")
    for candidate in review["unresolved_system_candidates"]:
        if any(
            observed_index.observations_by_id[observation_id].get("page")
            not in candidate["pages"]
            for observation_id in candidate["observation_ids"]
        ):
            raise ValidationError("unresolved note-system observation differs from candidate pages")
    for system in review["note_systems"]:
        pages = {
            page
            for start, end in system["definition_ranges"]
            for page in range(start, end + 1)
        }
        if not pages <= known_pages:
            raise ValidationError(
                f"note system references unknown definition page: {system['note_system_id']}"
            )


def _validate_evidence(value: Any) -> set[str]:
    records = validate_ordered_ids(
        value, id_field="evidence_id", prefix="nse", path="note_system_review.evidence"
    )
    evidence_ids: set[str] = set()
    for index, record in enumerate(records):
        path = f"note_system_review.evidence[{index}]"
        validate_exact_fields(record, EVIDENCE_FIELDS, path)
        validate_id_list(record["observation_ids"], f"{path}.observation_ids")
        validate_pages(record["pages"], f"{path}.pages", required=True)
        entry_indexes = record["skeleton_entry_indexes"]
        if (
            not isinstance(entry_indexes, list)
            or not all(type(item) is int and item >= 0 for item in entry_indexes)
            or entry_indexes != sorted(set(entry_indexes))
        ):
            raise ValidationError(f"{path}.skeleton_entry_indexes is invalid")
        validate_choice(
            record["decision_source"],
            NOTE_SYSTEM_EVIDENCE_SOURCES,
            f"{path}.decision_source",
        )
        asset_ids = validate_id_list(record["page_asset_ids"], f"{path}.page_asset_ids")
        model_name = validate_nullable_string(record["model_name"], f"{path}.model_name")
        prompt_version = validate_nullable_string(
            record["prompt_version"], f"{path}.prompt_version"
        )
        if record["decision_source"] == "bounded_multimodal_review":
            if not asset_ids or model_name is None or prompt_version is None:
                raise ValidationError(f"{path} model review requires assets and model provenance")
        elif asset_ids or model_name is not None or prompt_version is not None:
            raise ValidationError(f"{path} structural rule must not claim visual model provenance")
        evidence_ids.add(record["evidence_id"])
    return evidence_ids


def _validate_systems(value: Any, evidence_ids: set[str]) -> None:
    records = validate_ordered_ids(
        value, id_field="note_system_id", prefix="ns", path="note_system_review.note_systems"
    )
    for index, record in enumerate(records):
        path = f"note_system_review.note_systems[{index}]"
        validate_exact_fields(record, NOTE_SYSTEM_FIELDS, path)
        kind = validate_choice(record["kind"], NOTE_SYSTEM_KINDS, f"{path}.kind")
        validate_ranges(
            record["definition_ranges"], f"{path}.definition_ranges", required=True
        )
        scope = validate_choice(
            record["reference_scope"], NOTE_REFERENCE_SCOPES, f"{path}.reference_scope"
        )
        reset = validate_choice(
            record["reset_policy"], NOTE_RESET_POLICIES, f"{path}.reset_policy"
        )
        if scope == "unresolved":
            if reset != "unknown":
                raise ValidationError(f"{path} unresolved scope requires unknown reset policy")
        elif (scope, reset) not in _KIND_SCOPE_POLICIES[kind]:
            raise ValidationError(f"{path} has incompatible kind, scope, and reset policy")
        validate_string_choices(record["marker_styles"], NOTE_MARKER_STYLES, f"{path}.marker_styles")
        _validate_known_evidence(record["evidence_ids"], evidence_ids, path)
        validate_confidence(record["confidence"], f"{path}.confidence")


def _validate_unresolved(value: Any, evidence_ids: set[str]) -> None:
    records = validate_ordered_ids(
        value,
        id_field="candidate_id",
        prefix="nsc",
        path="note_system_review.unresolved_system_candidates",
    )
    for index, record in enumerate(records):
        path = f"note_system_review.unresolved_system_candidates[{index}]"
        validate_exact_fields(record, UNRESOLVED_SYSTEM_FIELDS, path)
        validate_pages(record["pages"], f"{path}.pages", required=True)
        validate_id_list(record["observation_ids"], f"{path}.observation_ids")
        _validate_known_evidence(record["evidence_ids"], evidence_ids, path)
        validate_reason(record["reason"], f"{path}.reason")


def _validate_known_evidence(value: Any, known: set[str], path: str) -> None:
    evidence = set(validate_id_list(value, f"{path}.evidence_ids", required=True))
    if not evidence <= known:
        raise ValidationError(f"{path}.evidence_ids contain unknown evidence")


def _page_assets_by_id(page_assets: dict[str, Any]) -> dict[str, int]:
    images = page_assets.get("images")
    if not isinstance(images, list):
        raise ValidationError("PageAssets images must be list")
    indexed: dict[str, int] = {}
    for image in images:
        source = image.get("source") if isinstance(image, dict) else None
        image_id = image.get("image_id") if isinstance(image, dict) else None
        page = source.get("page") if isinstance(source, dict) else None
        if not isinstance(image_id, str) or not image_id or type(page) is not int or page <= 0:
            raise ValidationError("PageAssets image record is invalid")
        if image_id in indexed:
            raise ValidationError("duplicate PageAssets image_id")
        indexed[image_id] = page
    return indexed
