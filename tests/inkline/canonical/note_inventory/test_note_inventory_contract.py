from __future__ import annotations

import pytest

from inkline.canonical import ValidationError
from inkline.canonical.note_inventory import validate_note_inventory


def _inventory() -> dict:
    return {
        "metadata": {
            "schema_name": "inkline_note_inventory",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "definitions": [
            {
                "definition_id": "nd000001",
                "text_unit_id": "tu000002",
                "physical_page": 2,
                "note_system_id": "ns000001",
                "marker": "1",
                "normalized_marker": "1",
                "note_group_id": "ng000001",
                "evidence_ids": ["nmr000002"],
            }
        ],
        "references": [
            {
                "reference_id": "nr000001",
                "text_unit_id": "tu000001",
                "inline_run_index": 0,
                "physical_page": 1,
                "note_system_id": "ns000001",
                "marker": "1",
                "normalized_marker": "1",
                "evidence_ids": ["nmr000001"],
            }
        ],
        "note_groups": [
            {
                "note_group_id": "ng000001",
                "note_system_id": "ns000001",
                "heading_text_unit_ids": [],
                "definition_ids": ["nd000001"],
                "physical_ranges": [[2, 2]],
                "evidence_ids": ["nmr000002"],
            }
        ],
        "unresolved_cases": [],
    }


def test_note_inventory_accepts_unresolved_reference_inventory() -> None:
    validate_note_inventory(_inventory())


def test_note_inventory_rejects_cross_system_group() -> None:
    inventory = _inventory()
    inventory["note_groups"][0]["note_system_id"] = "ns000002"

    with pytest.raises(ValidationError, match="crosses note systems"):
        validate_note_inventory(inventory)


def test_note_inventory_rejects_authoritative_targets() -> None:
    inventory = _inventory()
    inventory["references"][0]["target_note_unit_id"] = "tu000002"

    with pytest.raises(ValidationError, match="invalid fields"):
        validate_note_inventory(inventory)
