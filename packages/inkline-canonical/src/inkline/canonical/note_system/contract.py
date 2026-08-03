from __future__ import annotations

NOTE_SYSTEM_REVIEW_SCHEMA_NAME = "inkline_note_system_review"
NOTE_SYSTEM_REVIEW_SCHEMA_VERSION = "0.2-shadow"

NOTE_SYSTEM_KINDS = {"page_footnote", "chapter_endnote", "book_endnote"}
NOTE_REFERENCE_SCOPES = {"page", "chapter", "book", "unresolved"}
NOTE_RESET_POLICIES = {"page", "chapter", "book", "unknown"}
NOTE_MARKER_STYLES = {
    "numeric",
    "circled_numeric",
    "symbol",
    "alphabetic",
    "roman",
    "mixed",
    "unknown",
}
NOTE_SYSTEM_EVIDENCE_SOURCES = {"structural_rule", "bounded_multimodal_review"}

TOP_LEVEL_FIELDS = {
    "metadata",
    "evidence",
    "note_systems",
    "unresolved_system_candidates",
}
EVIDENCE_FIELDS = {
    "evidence_id",
    "observation_ids",
    "pages",
    "skeleton_entry_indexes",
    "decision_source",
    "page_asset_ids",
    "model_name",
    "prompt_version",
}
NOTE_SYSTEM_FIELDS = {
    "note_system_id",
    "kind",
    "definition_ranges",
    "reference_scope",
    "marker_styles",
    "reset_policy",
    "evidence_ids",
    "confidence",
}
UNRESOLVED_SYSTEM_FIELDS = {
    "candidate_id",
    "pages",
    "observation_ids",
    "evidence_ids",
    "reason",
}
