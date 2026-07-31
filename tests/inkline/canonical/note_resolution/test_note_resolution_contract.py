from __future__ import annotations

import pytest

from inkline.canonical import ValidationError
from inkline.canonical.note_resolution import (
    validate_note_resolution,
    validate_note_resolution_against_sources,
)


def _resolution() -> dict:
    return {
        "metadata": {
            "schema_name": "inkline_note_resolution",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "relations": [
            {
                "relation_id": "nrel000001",
                "reference_id": "nr000001",
                "source_text_unit_id": "tu000001",
                "source_inline_run_index": 0,
                "source_section_id": "s000001",
                "scope_section_id": "s000000",
                "marker": "1",
                "target_definition_id": "nd000001",
                "target_note_unit_id": "tu000002",
                "target_section_id": "s000001",
                "note_system_id": "ns000001",
                "scope": "chapter",
                "evidence_ids": ["nmr000001", "nmr000002"],
                "decision_source": "unique_marker_within_confirmed_chapter_scope",
            }
        ],
        "unresolved_references": [],
    }


def test_note_resolution_accepts_immutable_relation_artifact() -> None:
    validate_note_resolution(_resolution())


def test_note_resolution_rejects_resolved_target_written_into_unresolved_record() -> None:
    resolution = _resolution()
    resolution["unresolved_references"] = [
        {
            "reference_id": "nr000001",
            "note_system_id": "ns000001",
            "candidate_definition_ids": ["nd000001"],
            "evidence_ids": ["nmr000001"],
            "reason": "ambiguous_target",
        }
    ]

    with pytest.raises(ValidationError, match="both resolved and unresolved"):
        validate_note_resolution(resolution)


def test_chapter_resolution_uses_confirmed_common_scope_ancestor() -> None:
    inventory = {
        "metadata": {"doc_id": "sample"},
        "references": [
            {
                "reference_id": "nr000001",
                "text_unit_id": "tu000001",
                "inline_run_index": 0,
                "physical_page": 1,
                "note_system_id": "ns000001",
                "marker": "1",
                "normalized_marker": "1",
            }
        ],
        "definitions": [
            {
                "definition_id": "nd000001",
                "text_unit_id": "tu000002",
                "physical_page": 2,
                "note_system_id": "ns000001",
                "normalized_marker": "1",
            }
        ],
    }
    section_map = _section_map_with_sibling_members()
    resolution = _resolution()
    resolution["relations"][0]["target_section_id"] = "s000002"

    validate_note_resolution_against_sources(resolution, inventory, section_map)

    invalid = resolution
    invalid["relations"][0]["scope_section_id"] = "s000001"
    with pytest.raises(ValidationError, match="scope ancestor"):
        validate_note_resolution_against_sources(invalid, inventory, section_map)


def _section_map_with_sibling_members() -> dict:
    sections = []
    for index, parent, level, page, unit_ids in (
        (0, None, 1, [1, 2], []),
        (1, "s000000", 2, [1, 1], ["tu000001"]),
        (2, "s000000", 2, [2, 2], ["tu000002"]),
    ):
        sections.append(
            {
                "section_id": f"s{index:06d}",
                "title": f"Section {index}",
                "level": level,
                "parent_section_id": parent,
                "skeleton_entry_index": index,
                "anchor_evidence_ids": [f"sa{index:06d}"],
                "title_text_unit_ids": [],
                "physical_ranges": [page],
                "text_unit_ids": unit_ids,
                "table_ids": [],
                "visual_group_ids": [],
                "note_group_ids": [],
                "attached_visual_pages": [],
                "evidence_ids": [f"sa{index:06d}"],
                "decision_source": "structural_rule",
                "confidence": "high",
            }
        )
    return {
        "metadata": {
            "schema_name": "inkline_section_map",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "sections": sections,
        "page_placements": [],
        "resource_placements": [
            {
                "resource_type": "text_unit",
                "resource_id": unit_id,
                "placement": "section_member",
                "section_id": section_id,
                "reason": "confirmed_membership",
                "evidence_ids": [unit_id],
                "decision_source": "structural_rule",
                "confidence": "high",
            }
            for unit_id, section_id in (
                ("tu000001", "s000001"),
                ("tu000002", "s000002"),
            )
        ],
    }
