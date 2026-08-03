from __future__ import annotations

import pytest

from inkline.canonical import ValidationError
from inkline.canonical.note_inventory import (
    validate_note_inventory,
    validate_note_inventory_against_sources,
)


def _inventory() -> dict:
    return {
        "metadata": {
            "schema_name": "inkline_note_inventory",
            "schema_version": "0.2-shadow",
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
        "unresolved_definitions": [],
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


def test_note_inventory_accepts_explicit_unresolved_definition_partition() -> None:
    inventory = _inventory()
    validate_note_inventory(inventory)


def test_note_inventory_rejects_duplicate_unresolved_footnote_unit() -> None:
    inventory = _inventory()
    inventory["unresolved_definitions"] = [
        {
            "candidate_id": "ndc000001",
            "text_unit_id": "tu000003",
            "physical_page": 3,
            "note_system_id": None,
            "marker_review_request_id": None,
            "marker_review_status": "not_planned",
            "evidence_ids": ["nse000001"],
            "reason": "marker_not_planned",
        },
        {
            "candidate_id": "ndc000002",
            "text_unit_id": "tu000003",
            "physical_page": 3,
            "note_system_id": None,
            "marker_review_request_id": None,
            "marker_review_status": "not_planned",
            "evidence_ids": ["nse000001"],
            "reason": "marker_not_planned",
        },
    ]

    with pytest.raises(ValidationError, match="one TextUnit cannot have multiple unresolved"):
        validate_note_inventory(inventory)


@pytest.mark.parametrize("collection", ["note_groups", "unresolved_cases"])
def test_note_inventory_rejects_fabricated_nonrecord_evidence_against_sources(
    collection: str,
) -> None:
    inventory, text_flow, systems, plan, markers = _source_artifacts()
    inventory[collection][0]["evidence_ids"] = ["fabricated"]

    with pytest.raises(ValidationError, match="unknown note evidence"):
        validate_note_inventory_against_sources(inventory, text_flow, systems, plan, markers)


def _source_artifacts() -> tuple[dict, dict, dict, dict, dict]:
    inventory = _inventory()
    inventory["definitions"][0]["text_unit_id"] = "tu000001"
    inventory["definitions"][0]["physical_page"] = 1
    inventory["definitions"][0]["note_group_id"] = "ng000001"
    inventory["definitions"][0]["evidence_ids"] = ["nmr000001"]
    inventory["note_groups"][0]["evidence_ids"] = ["nmr000001"]
    inventory["note_groups"][0]["physical_ranges"] = [[1, 1]]
    inventory["unresolved_cases"] = [
        {
            "case_id": "niu000001",
            "kind": "orphan_definition",
            "definition_ids": ["nd000001"],
            "reference_ids": [],
            "evidence_ids": ["nmr000001"],
            "reason": "requires_manual_review",
        }
    ]
    text_flow = {
        "metadata": {
            "schema_name": "inkline_text_flow",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "text_units": [
            {
                "unit_id": "tu000001",
                "unit_type": "footnote",
                "text": "1. Note",
                "page": 1,
                "pages": [1],
                "bbox": [0, 0, 10, 10],
                "spans": [],
                "observation_ids": ["obs000001"],
                "role_hints": ["footnote_text"],
                "attrs": {"merge_events": []},
                "parser_payloads": [],
            }
        ],
        "ignored_observation_counts": {},
        "provenance": {
            "observed_schema_name": "inkline_observed_document",
            "observed_schema_version": "0.1-shadow",
            "skeleton_schema_name": "inkline_book_skeleton",
            "skeleton_schema_version": "0.2-shadow",
            "page_review_schema_name": "inkline_page_review",
            "page_review_schema_version": "1.4-shadow",
            "page_layout_schema_name": "inkline_page_layout_analysis",
            "page_layout_schema_version": "0.1-shadow",
            "included_pages": [1],
            "excluded_pages": [],
            "direct_anchor_group_count": 0,
        },
    }
    systems = {
        "metadata": {"doc_id": "sample"},
        "note_systems": [{"note_system_id": "ns000001"}],
        "evidence": [{"evidence_id": "nse000001"}],
    }
    plan = {"metadata": {"doc_id": "sample"}, "review_requests": []}
    markers = {
        "metadata": {"doc_id": "sample"},
        "outcomes": [
            {
                "review_request_id": "nmp000001",
                "markers": [{"marker_evidence_id": "nmr000001"}],
            }
        ],
    }
    return inventory, text_flow, systems, plan, markers
