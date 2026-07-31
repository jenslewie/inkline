from __future__ import annotations

import pytest

from inkline.canonical import ValidationError
from inkline.canonical.text_flow import validate_final_text_flow_artifact_links


def test_final_text_flow_rejects_grouped_caption_declared_as_display_block() -> None:
    flow = {
        "metadata": {
            "schema_name": "inkline_text_flow",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "text_units": [
            {
                "unit_id": "tu000001",
                "unit_type": "display_block",
                "text": "Caption",
                "page": 1,
                "pages": [1],
                "bbox": [0, 0, 10, 10],
                "spans": [],
                "observation_ids": ["obs000002"],
                "role_hints": ["caption_text"],
                "attrs": {
                    "layout_fragments": [
                        {
                            "observation_id": "obs000002",
                            "page": 1,
                            "classified_type": "display_block",
                            "status": "resolved",
                            "layout_form": "short_centered",
                            "signals": [],
                        }
                    ],
                    "merge_events": [],
                },
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
    visual = {
        "metadata": {
            "schema_name": "inkline_visual_relation_review",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "evidence": [
            {
                "evidence_id": "vre000001",
                "kind": "parser_provenance",
                "observation_ids": ["obs000001", "obs000002"],
                "pages": [1],
                "page_asset_ids": [],
                "model_name": None,
                "prompt_version": None,
            }
        ],
        "visual_groups": [
            {
                "visual_group_id": "vg000001",
                "asset_observation_ids": ["obs000001"],
                "caption_observation_ids": ["obs000002"],
                "relation_type": "caption_of",
                "physical_pages": [1],
                "evidence_ids": ["vre000001"],
                "decision_source": "parser_provenance",
                "confidence": "high",
            }
        ],
        "unpaired_asset_observation_ids": [],
        "unpaired_caption_observation_ids": [],
        "unresolved_candidates": [],
    }
    systems = {
        "metadata": {
            "schema_name": "inkline_note_system_review",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "evidence": [],
        "note_systems": [],
        "unresolved_system_candidates": [],
    }
    markers = {
        "metadata": {
            "schema_name": "inkline_note_marker_review",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "outcomes": [],
    }

    with pytest.raises(ValidationError, match="non-caption TextUnit"):
        validate_final_text_flow_artifact_links(flow, visual, systems, markers)
