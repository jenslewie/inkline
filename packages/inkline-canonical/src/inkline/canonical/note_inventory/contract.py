from __future__ import annotations

NOTE_INVENTORY_SCHEMA_NAME = "inkline_note_inventory"
NOTE_INVENTORY_SCHEMA_VERSION = "0.2-shadow"

NOTE_INVENTORY_ISSUE_KINDS = {
    "duplicate_definition",
    "orphan_definition",
    "orphan_reference",
    "ambiguous_system",
    "unreviewed_marker",
}

TOP_LEVEL_FIELDS = {
    "metadata",
    "definitions",
    "unresolved_definitions",
    "references",
    "note_groups",
    "unresolved_cases",
}
UNRESOLVED_DEFINITION_STATUSES = {"not_planned", "absent", "not_run", "failed", "unresolved"}
UNRESOLVED_DEFINITION_FIELDS = {
    "candidate_id",
    "text_unit_id",
    "physical_page",
    "note_system_id",
    "marker_review_request_id",
    "marker_review_status",
    "evidence_ids",
    "reason",
}
DEFINITION_FIELDS = {
    "definition_id",
    "text_unit_id",
    "physical_page",
    "note_system_id",
    "marker",
    "normalized_marker",
    "note_group_id",
    "evidence_ids",
}
REFERENCE_FIELDS = {
    "reference_id",
    "text_unit_id",
    "inline_run_index",
    "physical_page",
    "note_system_id",
    "marker",
    "normalized_marker",
    "evidence_ids",
}
NOTE_GROUP_FIELDS = {
    "note_group_id",
    "note_system_id",
    "heading_text_unit_ids",
    "definition_ids",
    "physical_ranges",
    "evidence_ids",
}
UNRESOLVED_CASE_FIELDS = {
    "case_id",
    "kind",
    "definition_ids",
    "reference_ids",
    "evidence_ids",
    "reason",
}

NOTE_REF_INLINE_RUN_FIELDS = {
    "type",
    "marker",
    "text",
    "source_page",
    "target_note_id",
    "resolution_status",
    "evidence_ids",
}
