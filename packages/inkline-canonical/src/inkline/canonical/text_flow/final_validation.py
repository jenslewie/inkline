from __future__ import annotations

from typing import Any

from inkline.canonical.artifact_dag.validation import (
    validate_exact_fields,
    validate_id_list,
    validate_non_empty_string,
)
from inkline.canonical.note_marker_review import validate_note_marker_review
from inkline.canonical.note_system import validate_note_system_review
from inkline.canonical.schema import ValidationError
from inkline.canonical.text_flow.validation import validate_text_flow
from inkline.canonical.visual_relations import validate_visual_relation_review

NOTE_REF_INLINE_RUN_FIELDS = {
    "type",
    "marker",
    "text",
    "source_page",
    "target_note_id",
    "resolution_status",
    "evidence_ids",
}


def validate_final_text_flow_artifact_links(
    text_flow: dict[str, Any],
    visual_relation_review: dict[str, Any],
    note_system_review: dict[str, Any],
    note_marker_review: dict[str, Any],
) -> None:
    """Validate final caption and note-ref declarations against pre-flow reviews."""

    validate_text_flow(text_flow)
    validate_visual_relation_review(visual_relation_review)
    validate_note_system_review(note_system_review)
    validate_note_marker_review(note_marker_review)
    doc_id = text_flow["metadata"]["doc_id"]
    for name, source in (
        ("VisualRelationReview", visual_relation_review),
        ("NoteSystemReview", note_system_review),
        ("NoteMarkerReview", note_marker_review),
    ):
        if source["metadata"]["doc_id"] != doc_id:
            raise ValidationError(f"{name} doc_id differs from final TextFlow")
    _validate_caption_units(text_flow, visual_relation_review)
    _validate_note_ref_runs(text_flow, note_marker_review)


def _validate_caption_units(
    text_flow: dict[str, Any], visual_relation_review: dict[str, Any]
) -> None:
    groups = {
        group["visual_group_id"]: set(group["caption_observation_ids"])
        for group in visual_relation_review["visual_groups"]
    }
    caption_ids = set().union(*groups.values()) if groups else set()
    asset_ids = {
        observation_id
        for group in visual_relation_review["visual_groups"]
        for observation_id in group["asset_observation_ids"]
    }
    materialized_caption_ids: set[str] = set()
    for unit in text_flow["text_units"]:
        unit_observation_ids = set(unit["observation_ids"])
        if unit_observation_ids & asset_ids:
            raise ValidationError("final TextFlow must not materialize visual assets as text")
        if unit["unit_type"] != "caption":
            if unit_observation_ids & caption_ids:
                raise ValidationError("visual caption observation has non-caption TextUnit type")
            continue
        group_id = unit["attrs"].get("visual_group_id")
        if not isinstance(group_id, str) or group_id not in groups:
            raise ValidationError("caption TextUnit requires known visual_group_id")
        if not unit_observation_ids or not unit_observation_ids <= groups[group_id]:
            raise ValidationError("caption TextUnit observations differ from visual group")
        if materialized_caption_ids & unit_observation_ids:
            raise ValidationError("caption observation is materialized more than once")
        materialized_caption_ids.update(unit_observation_ids)
    if materialized_caption_ids != caption_ids:
        raise ValidationError("final TextFlow must materialize every grouped caption observation")


def _validate_note_ref_runs(
    text_flow: dict[str, Any], note_marker_review: dict[str, Any]
) -> None:
    reference_markers = {
        marker["marker_evidence_id"]: marker
        for outcome in note_marker_review["outcomes"]
        for marker in outcome["markers"]
        if marker["marker_kind"] == "reference"
    }
    used_evidence: set[str] = set()
    for unit in text_flow["text_units"]:
        runs = unit["attrs"].get("inline_runs", [])
        if not isinstance(runs, list):
            raise ValidationError("TextFlow inline_runs must be list")
        for run in runs:
            if not isinstance(run, dict) or run.get("type") != "note_ref":
                continue
            validate_exact_fields(run, NOTE_REF_INLINE_RUN_FIELDS, "note_ref inline run")
            marker = validate_non_empty_string(run["marker"], "note_ref inline run.marker")
            if not isinstance(run["text"], str):
                raise ValidationError("note_ref inline run.text must be string")
            if type(run["source_page"]) is not int or run["source_page"] not in unit["pages"]:
                raise ValidationError("note_ref inline run source_page differs from TextUnit")
            if run["target_note_id"] is not None or run["resolution_status"] != "unresolved":
                raise ValidationError("final TextFlow note_ref must remain unresolved")
            evidence_ids = set(
                validate_id_list(
                    run["evidence_ids"], "note_ref inline run.evidence_ids", required=True
                )
            )
            if not evidence_ids <= set(reference_markers):
                raise ValidationError("note_ref inline run references unknown marker evidence")
            if any(reference_markers[evidence_id]["marker"] != marker for evidence_id in evidence_ids):
                raise ValidationError("note_ref marker differs from marker review")
            if used_evidence & evidence_ids:
                raise ValidationError("reference marker evidence is used by multiple inline runs")
            used_evidence.update(evidence_ids)
    if used_evidence != set(reference_markers):
        raise ValidationError("final TextFlow must materialize every reviewed reference marker")
