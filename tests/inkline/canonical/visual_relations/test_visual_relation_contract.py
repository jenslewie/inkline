from __future__ import annotations

from copy import deepcopy

import pytest

from inkline.canonical import (
    ValidationError,
    build_observed_index,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.visual_relations import (
    validate_visual_relation_review,
    validate_visual_relation_review_against_sources,
)


def _review() -> dict:
    return {
        "metadata": {
            "schema_name": "inkline_visual_relation_review",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "evidence": [
            {
                "evidence_id": "vre000001",
                "kind": "bounded_multimodal_review",
                "observation_ids": ["obs000001", "obs000002"],
                "pages": [1],
                "page_asset_ids": ["page-0001-review"],
                "model_name": "test-model",
                "prompt_version": "visual-relation-v1",
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
                "decision_source": "bounded_multimodal_review",
                "confidence": "high",
            }
        ],
        "unpaired_asset_observation_ids": [],
        "unpaired_caption_observation_ids": [],
        "unresolved_candidates": [],
    }


def _sources() -> tuple:
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=100, height=100)],
        [
            make_observation("obs000001", "image_region", page=1, bbox=[0, 0, 40, 40]),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[0, 41, 40, 50],
                text="Caption",
                role_hint="caption_text",
            ),
        ],
    )
    page_layout = {"metadata": {"doc_id": "sample"}}
    page_review = {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]}
    page_assets = {
        "images": [
            {
                "image_id": "page-0001-review",
                "source": {"page": 1},
            }
        ]
    }
    return build_observed_index(observed), page_layout, page_review, page_assets


def test_visual_relation_review_accepts_same_page_group() -> None:
    validate_visual_relation_review_against_sources(_review(), *_sources())


def test_visual_relation_review_rejects_duplicate_endpoint_ownership() -> None:
    review = _review()
    duplicate = deepcopy(review["visual_groups"][0])
    duplicate["visual_group_id"] = "vg000002"
    review["visual_groups"].append(duplicate)

    with pytest.raises(ValidationError, match="one group owner"):
        validate_visual_relation_review(review)


def test_visual_relation_review_rejects_table_owned_caption() -> None:
    table_flow = {
        "tables": [{"caption_observation_ids": ["obs000002"]}],
    }

    with pytest.raises(ValidationError, match="already owned by TableFlow"):
        validate_visual_relation_review_against_sources(
            _review(), *_sources(), table_flow=table_flow
        )
