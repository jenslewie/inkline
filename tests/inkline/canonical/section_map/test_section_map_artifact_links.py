from __future__ import annotations

import pytest

from inkline.canonical import ValidationError
from inkline.canonical.section_map import validate_section_map_artifact_links


def _section_map() -> dict:
    return {
        "metadata": {
            "schema_name": "inkline_section_map",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "sections": [
            {
                "section_id": "s000000",
                "title": "Chapter",
                "level": 1,
                "parent_section_id": None,
                "skeleton_entry_index": 0,
                "anchor_evidence_ids": ["sa000000"],
                "title_text_unit_ids": ["tu000001"],
                "physical_ranges": [[1, 1]],
                "text_unit_ids": ["tu000001"],
                "table_ids": ["tbl000001"],
                "visual_group_ids": ["vg000001"],
                "note_group_ids": ["ng000001"],
                "attached_visual_pages": [],
                "evidence_ids": ["sa000000", "tu000001"],
                "decision_source": "structural_rule",
                "confidence": "high",
            }
        ],
        "page_placements": [
            {
                "page": 1,
                "placement": "section_member",
                "section_id": "s000000",
                "reason": "confirmed_text_flow",
                "evidence_ids": ["tu000001"],
                "decision_source": "structural_rule",
                "confidence": "high",
            }
        ],
        "resource_placements": [
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "placement": "section_member",
                "section_id": "s000000",
                "reason": "confirmed_membership",
                "evidence_ids": [resource_id],
                "decision_source": "structural_rule",
                "confidence": "high",
            }
            for resource_type, resource_id in (
                ("text_unit", "tu000001"),
                ("table", "tbl000001"),
                ("visual_group", "vg000001"),
                ("note_group", "ng000001"),
            )
        ],
    }


def _sources() -> tuple[dict, dict, dict, dict]:
    metadata = {"doc_id": "sample"}
    text_flow = {"metadata": metadata, "text_units": [{"unit_id": "tu000001"}]}
    table_flow = {"metadata": metadata, "tables": [{"table_id": "tbl000001"}]}
    visual = {"metadata": metadata, "visual_groups": [{"visual_group_id": "vg000001"}]}
    inventory = {"metadata": metadata, "note_groups": [{"note_group_id": "ng000001"}]}
    return text_flow, table_flow, visual, inventory


def test_section_map_places_every_logical_resource_once() -> None:
    validate_section_map_artifact_links(_section_map(), *_sources())


def test_section_map_rejects_silent_resource_omission() -> None:
    section_map = _section_map()
    section_map["resource_placements"].pop()

    with pytest.raises(ValidationError, match="place every note_group"):
        validate_section_map_artifact_links(section_map, *_sources())
