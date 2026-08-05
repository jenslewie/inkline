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
from inkline.canonical.note_marker_review import (
    validate_note_marker_review,
    validate_note_marker_review_against_plan,
    validate_note_marker_review_plan,
    validate_note_marker_review_plan_against_sources,
)


def _plan() -> dict:
    return {
        "metadata": {
            "schema_name": "inkline_note_marker_review_plan",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "review_requests": [
            {
                "review_request_id": "nmp000001",
                "note_system_id": "ns000001",
                "region_kind": "reference",
                "regions": [
                    {
                        "page": 1,
                        "bbox": [0, 0, 100, 100],
                        "observation_ids": ["obs000001"],
                    }
                ],
                "reasons": ["reference_candidate_without_definition_marker"],
                "evidence_ids": ["nse000001"],
            }
        ],
        "not_required_note_system_ids": [],
        "unresolved_note_system_ids": [],
    }


def _review(status: str = "found") -> dict:
    markers = (
        [
            {
                "marker_evidence_id": "nmr000001",
                "note_system_id": "ns000001",
                "marker_kind": "reference",
                "marker": "1",
                "page": 1,
                "observation_id": "obs000001",
                "bbox": [1, 1, 5, 5],
                "adjacent_text": "body",
                "evidence_ids": ["nse000001"],
                "confidence": "high",
            }
        ]
        if status == "found"
        else []
    )
    return {
        "metadata": {
            "schema_name": "inkline_note_marker_review",
            "schema_version": "0.2-shadow",
            "doc_id": "sample",
        },
        "outcomes": [
            {
                "review_request_id": "nmp000001",
                "status": status,
                "markers": markers,
                "failure_reason": "model_timeout" if status == "failed" else None,
                "model_name": None if status == "not_run" else "test-model",
                "prompt_version": None if status == "not_run" else "note-marker-v1",
                "page_asset_ids": [] if status == "not_run" else ["page-0001-review"],
            }
        ],
    }


def _index():
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
            make_observation(
                "obs000001",
                "text_region",
                text="body text",
                page=1,
                bbox=[0, 0, 100, 20],
            )
        ],
    )
    return build_observed_index(observed)


def test_marker_plan_requires_bounded_regions() -> None:
    validate_note_marker_review_plan(_plan())


def test_marker_review_distinguishes_not_run_failed_and_absent() -> None:
    for status in ("not_run", "failed", "absent", "unresolved"):
        validate_note_marker_review(_review(status))


def test_marker_review_outcomes_require_page_asset_provenance() -> None:
    review = _review()
    validate_note_marker_review(review)


def test_marker_review_rejects_marker_outside_planned_region() -> None:
    review = _review()
    review["outcomes"][0]["markers"][0]["bbox"] = [101, 101, 110, 110]

    with pytest.raises(ValidationError, match="outside planned region"):
        validate_note_marker_review_against_plan(
            review,
            _plan(),
            _index(),
            {"images": [{"image_id": "page-0001-review", "source": {"page": 1}}]},
        )


def test_marker_source_validation_accepts_frozen_mappings_and_rejects_observation_escape() -> None:
    review = _review()
    review["outcomes"][0]["markers"][0]["bbox"] = [50, 50, 60, 60]

    with pytest.raises(ValidationError, match="outside"):
        validate_note_marker_review_against_plan(
            cast(dict[str, Any], _freeze(review)),
            cast(dict[str, Any], _freeze(_plan())),
            _index(),
            cast(dict[str, Any], _freeze({"images": [{"image_id": "page-0001-review", "source": {"page": 1}}]})),
        )


def test_marker_source_validation_rejects_known_style_mismatch() -> None:
    review = _review()
    review["outcomes"][0]["markers"][0]["marker"] = "*"
    systems = {
        "metadata": {"doc_id": "sample"},
        "note_systems": [{"note_system_id": "ns000001", "marker_styles": ["numeric"]}],
    }

    with pytest.raises(ValidationError, match="marker style"):
        validate_note_marker_review_against_plan(
            review,
            _plan(),
            _index(),
            {"images": [{"image_id": "page-0001-review", "source": {"page": 1}}]},
            note_system_review=systems,
        )


def test_marker_source_validation_rejects_empty_adjacent_text() -> None:
    review = _review()
    review["outcomes"][0]["markers"][0]["adjacent_text"] = ""

    with pytest.raises(ValidationError, match="adjacent_text"):
        validate_note_marker_review_against_plan(
            review,
            _plan(),
            _index(),
            {"images": [{"image_id": "page-0001-review", "source": {"page": 1}}]},
        )


def test_marker_plan_source_validation_rejects_evidence_from_another_system() -> None:
    plan = _plan()
    plan["review_requests"][0]["evidence_ids"] = ["nse000002"]
    systems = {
        "metadata": {"doc_id": "sample"},
        "evidence": [
            {"evidence_id": "nse000001", "observation_ids": ["obs000001"], "pages": [1]},
            {"evidence_id": "nse000002", "observation_ids": ["obs000001"], "pages": [1]},
        ],
        "note_systems": [
            {
                "note_system_id": "ns000001",
                "evidence_ids": ["nse000001"],
                "definition_ranges": [[1, 1]],
                "reference_scope": "page",
            }
        ],
    }

    with pytest.raises(ValidationError, match="evidence"):
        validate_note_marker_review_plan_against_sources(
            plan,
            _index(),
            {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]},
            systems,
        )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(nested) for key, nested in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(nested) for nested in value)
    return value
