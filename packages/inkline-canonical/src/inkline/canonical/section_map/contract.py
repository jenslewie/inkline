from __future__ import annotations

from typing import Any

SECTION_MAP_SCHEMA_NAME = "inkline_section_map"
SECTION_MAP_SCHEMA_VERSION = "0.1-shadow"
SECTION_MAP_EVIDENCE_SCHEMA_NAME = "inkline_section_map_evidence"
SECTION_MAP_EVIDENCE_SCHEMA_VERSION = "0.1-shadow"

SECTION_MAP_START_METHODS = {"observed_title_match", "printed_page_offset", "unlocated"}
SECTION_MAP_TEXT_FLOW_STATUSES = {
    "mapped",
    "excluded_by_page_review",
    "not_applicable",
    "unlocated",
}

SECTION_MAP_PLACEMENTS = {"section_member", "standalone", "unresolved"}
SECTION_MAP_CONFIDENCES = {"high", "medium", "low"}
SECTION_MAP_DECISION_SOURCES = {"structural_rule", "bounded_llm_boundary_verifier"}

REQUIRED_TOP_LEVEL_FIELDS: dict[str, type[Any]] = {
    "metadata": dict,
    "sections": list,
    "page_placements": list,
}

REQUIRED_METADATA_FIELDS: dict[str, type[Any]] = {
    "schema_name": str,
    "schema_version": str,
    "doc_id": str,
}

REQUIRED_SECTION_FIELDS: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "section_id": str,
    "title": str,
    "level": int,
    "parent_section_id": (str, type(None)),
    "skeleton_entry_index": int,
    "anchor_evidence_ids": list,
    "title_text_unit_ids": list,
    "physical_ranges": list,
    "text_unit_ids": list,
    "attached_visual_pages": list,
    "evidence_ids": list,
    "decision_source": str,
    "confidence": str,
}

REQUIRED_PAGE_PLACEMENT_FIELDS: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "page": int,
    "placement": str,
    "section_id": (str, type(None)),
    "reason": str,
    "evidence_ids": list,
    "decision_source": str,
    "confidence": str,
}
