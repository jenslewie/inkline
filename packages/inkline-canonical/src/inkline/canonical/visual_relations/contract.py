from __future__ import annotations

VISUAL_RELATION_REVIEW_SCHEMA_NAME = "inkline_visual_relation_review"
VISUAL_RELATION_REVIEW_SCHEMA_VERSION = "0.1-shadow"

VISUAL_DECISION_SOURCES = {"parser_provenance", "bounded_multimodal_review"}
VISUAL_EVIDENCE_KINDS = {
    "parser_provenance",
    "bounded_multimodal_review",
    "deterministic_candidate",
}

TOP_LEVEL_FIELDS = {
    "metadata",
    "evidence",
    "visual_groups",
    "unpaired_asset_observation_ids",
    "unpaired_caption_observation_ids",
    "unresolved_candidates",
}
EVIDENCE_FIELDS = {
    "evidence_id",
    "kind",
    "observation_ids",
    "pages",
    "page_asset_ids",
    "model_name",
    "prompt_version",
}
VISUAL_GROUP_FIELDS = {
    "visual_group_id",
    "asset_observation_ids",
    "caption_observation_ids",
    "relation_type",
    "physical_pages",
    "evidence_ids",
    "decision_source",
    "confidence",
}
UNRESOLVED_CANDIDATE_FIELDS = {
    "candidate_id",
    "asset_observation_ids",
    "caption_observation_ids",
    "physical_pages",
    "evidence_ids",
    "reason",
}
