from __future__ import annotations

NOTE_MARKER_REVIEW_PLAN_SCHEMA_NAME = "inkline_note_marker_review_plan"
NOTE_MARKER_REVIEW_PLAN_SCHEMA_VERSION = "0.1-shadow"
NOTE_MARKER_REVIEW_SCHEMA_NAME = "inkline_note_marker_review"
NOTE_MARKER_REVIEW_SCHEMA_VERSION = "0.2-shadow"

MARKER_REGION_KINDS = {"definition", "reference"}
MARKER_REVIEW_REASONS = {
    "definition_marker_unreadable",
    "definition_candidate_contains_multiple_markers",
    "definition_marker_without_reference_candidate",
    "reference_candidate_without_definition_marker",
    "marker_sequence_gap",
    "ambiguous_note_system",
    "parser_and_visual_evidence_conflict",
}
MARKER_OUTCOME_STATUSES = {"found", "absent", "not_run", "failed", "unresolved"}

PLAN_TOP_LEVEL_FIELDS = {
    "metadata",
    "review_requests",
    "not_required_note_system_ids",
    "unresolved_note_system_ids",
}
REVIEW_REQUEST_FIELDS = {
    "review_request_id",
    "note_system_id",
    "region_kind",
    "regions",
    "reasons",
    "evidence_ids",
}
REVIEW_REGION_FIELDS = {"page", "bbox", "observation_ids"}

REVIEW_TOP_LEVEL_FIELDS = {"metadata", "outcomes"}
OUTCOME_FIELDS = {
    "review_request_id",
    "status",
    "markers",
    "failure_reason",
    "model_name",
    "prompt_version",
    "page_asset_ids",
}
MARKER_FIELDS = {
    "marker_evidence_id",
    "note_system_id",
    "marker_kind",
    "marker",
    "page",
    "observation_id",
    "bbox",
    "adjacent_text",
    "evidence_ids",
    "confidence",
}
