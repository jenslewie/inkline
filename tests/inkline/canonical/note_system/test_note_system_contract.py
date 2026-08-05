from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, cast

import pytest

from inkline.canonical import (
    ValidationError,
    build_observed_index,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.note_system import (
    validate_note_system_review,
    validate_note_system_review_against_sources,
)


def _review() -> dict:
    return {
        "metadata": {
            "schema_name": "inkline_note_system_review",
            "schema_version": "0.2-shadow",
            "doc_id": "sample",
        },
        "evidence": [
            {
                "evidence_id": "nse000001",
                "observation_ids": ["obs000001"],
                "pages": [10],
                "skeleton_entry_indexes": [2],
                "decision_source": "structural_rule",
                "page_asset_ids": [],
                "model_name": None,
                "prompt_version": None,
            },
            {
                "evidence_id": "nse000002",
                "observation_ids": ["obs000002"],
                "pages": [20],
                "skeleton_entry_indexes": [3],
                "decision_source": "structural_rule",
                "page_asset_ids": [],
                "model_name": None,
                "prompt_version": None,
            },
        ],
        "note_systems": [
            {
                "note_system_id": "ns000001",
                "kind": "page_footnote",
                "definition_ranges": [[10, 10]],
                "reference_scope": "page",
                "marker_styles": ["circled_numeric"],
                "reset_policy": "page",
                "evidence_ids": ["nse000001"],
                "confidence": "high",
            },
            {
                "note_system_id": "ns000002",
                "kind": "chapter_endnote",
                "definition_ranges": [[20, 21]],
                "reference_scope": "chapter",
                "marker_styles": ["numeric"],
                "reset_policy": "chapter",
                "evidence_ids": ["nse000002"],
                "confidence": "high",
            },
        ],
        "unresolved_system_candidates": [],
    }


def test_note_system_review_allows_mixed_systems_as_separate_records() -> None:
    validate_note_system_review(_review())


def test_note_system_review_rejects_incompatible_scope() -> None:
    review = _review()
    review["note_systems"][0]["reference_scope"] = "book"

    with pytest.raises(ValidationError, match="incompatible"):
        validate_note_system_review(review)


def test_note_system_review_allows_distinct_systems_on_same_physical_page() -> None:
    review = _review()
    review["note_systems"][1]["definition_ranges"] = [[10, 10]]

    validate_note_system_review(review)


def test_note_system_review_requires_explicit_page_asset_and_model_provenance() -> None:
    review = _review()
    evidence = review["evidence"][0]
    evidence.update(
        {
            "page_asset_ids": ["page-0010-review"],
            "model_name": "test-model",
            "prompt_version": "note-system-v1",
        }
    )
    evidence["decision_source"] = "bounded_multimodal_review"

    validate_note_system_review(review)


def test_source_validation_accepts_frozen_mappings_and_sequences() -> None:
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(10, width=100, height=100)],
        [make_observation("obs000001", "footnote_region", page=10, bbox=[0, 80, 100, 100])],
    )
    review = _review()
    review["evidence"] = [{**review["evidence"][0], "pages": [10]}]
    review["note_systems"] = [{**review["note_systems"][0], "definition_ranges": [[10, 10]]}]
    review["unresolved_system_candidates"] = []

    validate_note_system_review_against_sources(
        cast(Mapping[str, Any], _freeze(review)),
        build_observed_index(observed),
        cast(
            Mapping[str, Any],
            _freeze({"metadata": {"doc_id": "sample"}, "pages": [{"page": 10}]}),
        ),
        cast(
            Mapping[str, Any],
            _freeze({"metadata": {"doc_id": "sample"}, "toc_entries": [{"entry_index": 2}]}),
        ),
        cast(
            Mapping[str, Any],
            _freeze(
            {
                "metadata": {"doc_id": "sample"},
                "pages": [{"page": 10, "text_flow_action": "include"}],
            }
            ),
        ),
        cast(Mapping[str, Any], _freeze({"images": []})),
    )


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(nested) for key, nested in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(nested) for nested in value)
    return value
