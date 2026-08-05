from __future__ import annotations

import json

import pytest

from inkline.canonical import (
    build_observed_index,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.note_system import build_note_system_review


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
            make_observation("obs000001", "footnote_region", page=1, bbox=[0, 80, 100, 100]),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[0, 82, 100, 95],
                text="A structural note definition.",
                role_hint="footnote_text",
            ),
        ],
    )
    return (
        build_observed_index(observed),
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]},
        {"metadata": {"doc_id": "sample"}, "toc_entries": []},
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1, "text_flow_action": "include"}]},
        {"images": [{"image_id": "page-0001-review", "source": {"page": 1}}]},
    )


def test_no_model_materializes_explicit_page_footnote_system_deterministically() -> None:
    first = build_note_system_review(*_sources())
    second = build_note_system_review(*_sources())

    assert first["note_systems"] == [
        {
            "note_system_id": "ns000001",
            "kind": "page_footnote",
            "definition_ranges": [[1, 1]],
            "reference_scope": "page",
            "marker_styles": ["unknown"],
            "reset_policy": "page",
            "evidence_ids": ["nse000001"],
            "confidence": "high",
        }
    ]
    assert first["unresolved_system_candidates"] == []
    assert first["evidence"][0]["decision_source"] == "structural_rule"
    assert first["evidence"][0]["page_asset_ids"] == []
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_bounded_callback_may_emit_only_a_system_for_the_supplied_candidate() -> None:
    requests: list[dict] = []

    def callback(request: dict) -> dict:
        requests.append(request)
        return {
            "systems": [
                {
                    "kind": "page_footnote",
                    "definition_ranges": [[1, 1]],
                    "reference_scope": "page",
                    "marker_styles": ["numeric"],
                    "reset_policy": "page",
                    "confidence": "high",
                }
            ]
        }

    review = build_note_system_review(
        *_sources(), review_callback=callback, model_name="fake-model"
    )

    assert review["unresolved_system_candidates"] == []
    assert review["note_systems"][0]["note_system_id"] == "ns000001"
    assert review["evidence"][0]["decision_source"] == "bounded_multimodal_review"
    assert review["evidence"][0]["page_asset_ids"] == ["page-0001-review"]
    assert requests[0]["pages"] == [1]
    assert requests[0]["observation_ids"] == ["obs000001", "obs000002"]
    assert requests[0]["page_asset_ids"] == ["page-0001-review"]


def test_failed_or_invalid_callback_never_promotes_structural_candidates() -> None:
    review = build_note_system_review(
        *_sources(),
        review_callback=lambda _request: {"systems": [{"kind": "book_endnote"}]},
        model_name="fake",
    )

    assert review["note_systems"] == []
    assert review["unresolved_system_candidates"][0]["reason"] == "model_unavailable_or_invalid"


def test_empty_bounded_model_decision_remains_explicitly_unresolved() -> None:
    review = build_note_system_review(
        *_sources(), review_callback=lambda _request: {"systems": []}, model_name="fake"
    )

    assert review["note_systems"] == []
    assert review["evidence"][0]["decision_source"] == "bounded_multimodal_review"
    assert review["unresolved_system_candidates"][0]["reason"] == "model_did_not_confirm_system"


def test_each_of_two_bounded_model_systems_has_its_own_evidence_owner() -> None:
    def callback(_request: dict) -> dict:
        return {
            "systems": [
                {
                    "kind": "page_footnote",
                    "definition_ranges": [[1, 1]],
                    "reference_scope": "page",
                    "marker_styles": ["numeric"],
                    "reset_policy": "page",
                    "confidence": "high",
                },
                {
                    "kind": "page_footnote",
                    "definition_ranges": [[1, 1]],
                    "reference_scope": "page",
                    "marker_styles": ["symbol"],
                    "reset_policy": "page",
                    "confidence": "medium",
                },
            ]
        }

    review = build_note_system_review(*_sources(), review_callback=callback, model_name="fake")

    assert [system["evidence_ids"] for system in review["note_systems"]] == [
        ["nse000001"],
        ["nse000002"],
    ]


def test_enabled_callback_without_page_asset_is_not_claimed_as_callback_failure() -> None:
    index, layout, skeleton, page_review, _page_assets = _sources()
    calls: list[dict] = []

    review = build_note_system_review(
        index,
        layout,
        skeleton,
        page_review,
        {"images": []},
        review_callback=lambda request: calls.append(request) or {"systems": []},
        model_name="fake",
    )

    assert calls == []
    assert review["unresolved_system_candidates"][0]["reason"] == "model_not_run"


def test_builder_never_mutates_observed_index() -> None:
    index, *sources = _sources()
    before = tuple(index.observations_by_id["obs000002"]["bbox"])

    build_note_system_review(index, *sources)

    assert tuple(index.observations_by_id["obs000002"]["bbox"]) == before
    with pytest.raises(TypeError):
        index.observations_by_id["obs000002"]["attrs"]["changed"] = True
