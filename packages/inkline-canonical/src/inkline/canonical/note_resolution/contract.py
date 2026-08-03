from __future__ import annotations

NOTE_RESOLUTION_SCHEMA_NAME = "inkline_note_resolution"
NOTE_RESOLUTION_SCHEMA_VERSION = "0.2-shadow"

NOTE_RESOLUTION_SCOPES = {"page", "chapter", "book"}
NOTE_RESOLUTION_DECISION_SOURCES = {
    "unique_marker_within_confirmed_page_scope",
    "unique_marker_within_confirmed_chapter_scope",
    "unique_marker_within_confirmed_book_scope",
}

TOP_LEVEL_FIELDS = {"metadata", "relations", "unresolved_references"}
RELATION_FIELDS = {
    "relation_id",
    "reference_id",
    "source_text_unit_id",
    "source_inline_run_index",
    "source_section_id",
    "scope_section_id",
    "marker",
    "target_definition_id",
    "target_note_unit_id",
    "target_section_id",
    "note_system_id",
    "scope",
    "evidence_ids",
    "decision_source",
}
UNRESOLVED_REFERENCE_FIELDS = {
    "reference_id",
    "note_system_id",
    "candidate_definition_ids",
    "evidence_ids",
    "reason",
}
