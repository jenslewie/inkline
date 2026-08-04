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
    page_layout = {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]}
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


def test_visual_relation_review_rejects_evidence_observation_outside_evidence_pages() -> None:
    review = _review()
    review["evidence"][0]["pages"] = [2]

    with pytest.raises(ValidationError, match="evidence observation"):
        validate_visual_relation_review_against_sources(review, *_sources())


def test_visual_relation_review_rejects_unresolved_pages_that_differ_from_endpoints() -> None:
    review = _review()
    group = review["visual_groups"].pop()
    review["unresolved_candidates"] = [
        {
            "candidate_id": "vrc000001",
            "asset_observation_ids": group["asset_observation_ids"],
            "caption_observation_ids": group["caption_observation_ids"],
            "physical_pages": [2],
            "evidence_ids": group["evidence_ids"],
            "reason": "ambiguous_caption",
        }
    ]

    with pytest.raises(ValidationError, match="unresolved candidate page provenance"):
        validate_visual_relation_review_against_sources(review, *_sources())


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


def test_visual_relation_review_rejects_direct_table_caption_without_materialized_table_flow() -> None:
    observed = make_observed_document(
        {
            "doc_id": "fixture",
            "title": "Fixture",
            "language": "en",
            "source_file": "fixture.pdf",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=100, height=100)],
        [
            make_observation("obs000001", "image_region", page=1, bbox=[0, 0, 40, 40]),
            make_observation("obs000002", "table_region", page=1, bbox=[0, 50, 40, 80]),
            make_observation(
                "obs000003",
                "text_region",
                page=1,
                bbox=[0, 81, 40, 90],
                text="Table caption",
                role_hint="caption_text",
                attrs={
                    "source_kind": "table_caption",
                    "visual_parent_observation_id": "obs000002",
                },
            ),
        ],
    )
    review = _review()
    review["metadata"]["doc_id"] = "fixture"
    review["evidence"][0]["observation_ids"] = ["obs000001", "obs000003"]
    review["visual_groups"][0]["caption_observation_ids"] = ["obs000003"]
    sources = (
        build_observed_index(observed),
        {"metadata": {"doc_id": "fixture"}, "pages": [{"page": 1}]},
        {"metadata": {"doc_id": "fixture"}, "pages": [{"page": 1}]},
        {"images": [{"image_id": "page-0001-review", "source": {"page": 1}}]},
    )

    with pytest.raises(ValidationError, match="ineligible"):
        validate_visual_relation_review_against_sources(
            review,
            *sources,
            table_flow={
                "metadata": {"doc_id": "fixture"},
                "tables": [],
                "unresolved_table_observation_runs": [],
                "excluded_table_observation_runs": [],
            },
        )


def test_visual_relation_review_rejects_unpaired_endpoint_without_evidence_coverage() -> None:
    review = _review()
    review["visual_groups"] = []
    review["unpaired_asset_observation_ids"] = ["obs000001"]
    review["evidence"][0]["observation_ids"] = ["obs000002"]

    with pytest.raises(ValidationError, match="unpaired visual endpoints must be covered"):
        validate_visual_relation_review_against_sources(review, *_sources())


def test_deterministic_candidate_evidence_cannot_claim_model_provenance() -> None:
    review = _review()
    review["visual_groups"] = []
    review["evidence"][0]["kind"] = "deterministic_candidate"

    with pytest.raises(ValidationError, match="deterministic candidate must not claim model"):
        validate_visual_relation_review(review)


def test_deterministic_candidate_evidence_cannot_prove_group() -> None:
    review = _review()
    review["evidence"][0]["kind"] = "deterministic_candidate"
    review["evidence"][0]["model_name"] = None
    review["evidence"][0]["prompt_version"] = None

    with pytest.raises(ValidationError, match="cannot prove a visual group"):
        validate_visual_relation_review(review)


def test_visual_relation_review_rejects_extra_evidence_page() -> None:
    review = _review()
    review["evidence"][0]["pages"] = [1, 999]

    with pytest.raises(ValidationError, match="evidence page provenance"):
        validate_visual_relation_review_against_sources(review, *_sources())


def test_visual_relation_review_rejects_fabricated_parser_provenance() -> None:
    review = _review()
    review["evidence"][0].update(
        {
            "kind": "parser_provenance",
            "page_asset_ids": [],
            "model_name": None,
            "prompt_version": None,
        }
    )
    review["visual_groups"][0]["decision_source"] = "parser_provenance"

    with pytest.raises(ValidationError, match="parser provenance"):
        validate_visual_relation_review_against_sources(review, *_sources())


def test_visual_relation_review_rejects_parser_group_with_unlinked_claimed_asset() -> None:
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
            make_observation("obs000002", "image_region", page=1, bbox=[50, 0, 90, 40]),
            make_observation(
                "obs000003",
                "text_region",
                page=1,
                bbox=[0, 41, 40, 50],
                text="Caption",
                role_hint="caption_text",
                attrs={"visual_parent_observation_id": "obs000001"},
            ),
        ],
    )
    review = {
        "metadata": {
            "schema_name": "inkline_visual_relation_review",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "evidence": [
            {
                "evidence_id": "vre000001",
                "kind": "parser_provenance",
                "observation_ids": ["obs000001", "obs000002", "obs000003"],
                "pages": [1],
                "page_asset_ids": [],
                "model_name": None,
                "prompt_version": None,
            }
        ],
        "visual_groups": [
            {
                "visual_group_id": "vg000001",
                "asset_observation_ids": ["obs000001", "obs000002"],
                "caption_observation_ids": ["obs000003"],
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
    sources = (
        build_observed_index(observed),
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]},
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]},
        {"images": []},
    )

    with pytest.raises(ValidationError, match="parser provenance"):
        validate_visual_relation_review_against_sources(review, *sources)
