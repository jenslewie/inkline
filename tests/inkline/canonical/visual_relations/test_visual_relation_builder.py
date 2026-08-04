from __future__ import annotations

import json
from pathlib import Path

import pytest

from inkline.canonical import (
    build_observed_index,
    build_page_layout_analysis,
    build_table_flow,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.visual_relations import build_visual_relation_review


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
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation("obs000001", "image_region", page=1, bbox=[100, 100, 500, 500]),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[540, 340, 850, 370],
                text="A caption title",
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                page=1,
                bbox=[540, 380, 850, 450],
                text="The adjacent caption body.",
                role_hint="body_text",
            ),
        ],
    )
    return (
        build_observed_index(observed),
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1, "body_lane": [80, 900]}]},
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1, "text_flow_action": "include"}]},
        {
            "metadata": {"doc_id": "sample"},
            "tables": [],
            "unresolved_table_observation_runs": [],
            "excluded_table_observation_runs": [],
        },
        {"images": [{"image_id": "page-0001-review", "source": {"page": 1}}]},
    )


def test_no_model_keeps_same_page_candidate_as_explicit_unresolved_evidence() -> None:
    review = build_visual_relation_review(*_sources())

    assert review["visual_groups"] == []
    assert review["unpaired_asset_observation_ids"] == []
    assert review["unresolved_candidates"] == [
        {
            "candidate_id": "vrc000001",
            "asset_observation_ids": ["obs000001"],
            "caption_observation_ids": ["obs000002", "obs000003"],
            "physical_pages": [1],
            "evidence_ids": ["vre000001"],
            "reason": "model_not_run",
        }
    ]
    assert review["evidence"][0]["page_asset_ids"] == ["page-0001-review"]
    assert review["evidence"][0]["model_name"] is None


def test_parser_parent_groups_without_model_and_excludes_table_caption() -> None:
    index, layout, page_review, table_flow, page_assets = _sources()
    source = index.observations_by_id["obs000002"]
    # This fixture is intentionally rebuilt: ObservedIndex itself stays read-only.
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "x",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation("obs000001", "image_region", page=1, bbox=[100, 100, 500, 500]),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[540, 340, 850, 370],
                text="caption",
                role_hint="caption_text",
                attrs={
                    "visual_parent_observation_id": "obs000001",
                    "source_kind": "figure_caption",
                },
            ),
            make_observation(
                "obs000003",
                "text_region",
                page=1,
                bbox=[540, 380, 850, 450],
                text="table caption",
                role_hint="caption_text",
                attrs={"visual_parent_observation_id": "obs000001", "source_kind": "table_caption"},
            ),
            make_observation(
                "obs000004",
                "text_region",
                page=1,
                bbox=[540, 460, 850, 490],
                text="caption continuation",
                role_hint="caption_text",
                attrs={
                    "visual_parent_observation_id": "obs000001",
                    "source_kind": "figure_caption",
                },
            ),
        ],
    )
    del index, source
    review = build_visual_relation_review(
        build_observed_index(observed),
        layout,
        page_review,
        {**table_flow, "tables": [{"caption_observation_ids": ["obs000003"]}]},
        page_assets,
    )

    assert review["visual_groups"][0]["caption_observation_ids"] == [
        "obs000002",
        "obs000004",
    ]
    assert review["visual_groups"][0]["decision_source"] == "parser_provenance"
    assert "obs000003" not in json.dumps(review)


def test_direct_table_caption_parent_is_not_a_visual_endpoint_without_materialized_table_flow() -> None:
    observed = make_observed_document(
        {
            "doc_id": "fixture",
            "title": "Fixture",
            "language": "en",
            "source_file": "fixture.pdf",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation("obs000001", "image_region", page=1, bbox=[100, 100, 500, 500]),
            make_observation("obs000002", "table_region", page=1, bbox=[100, 550, 500, 800]),
            make_observation(
                "obs000003",
                "text_region",
                page=1,
                bbox=[100, 810, 500, 840],
                text="Table caption",
                role_hint="caption_text",
                attrs={
                    "source_kind": "table_caption",
                    "visual_parent_observation_id": "obs000002",
                },
            ),
        ],
    )
    requests: list[dict] = []
    review = build_visual_relation_review(
        build_observed_index(observed),
        {"metadata": {"doc_id": "fixture"}, "pages": [{"page": 1, "body_lane": [80, 900]}]},
        {"metadata": {"doc_id": "fixture"}, "pages": [{"page": 1, "text_flow_action": "include"}]},
        {
            "metadata": {"doc_id": "fixture"},
            "tables": [],
            "unresolved_table_observation_runs": [],
            "excluded_table_observation_runs": [],
        },
        {"images": [{"image_id": "fixture-page", "source": {"page": 1}}]},
        review_callback=lambda request: requests.append(request)
        or {
            "groups": [],
            "unpaired_asset_observation_ids": ["obs000001"],
            "unpaired_caption_observation_ids": [],
        },
        model_name="fake",
    )

    assert review["visual_groups"] == []
    assert "obs000003" not in json.dumps(review)
    assert requests[0]["candidate_observation_ids"] == ["obs000001"]


def test_direct_table_caption_parent_is_not_promoted_as_an_adjacent_visual_caption() -> None:
    observed = make_observed_document(
        {
            "doc_id": "fixture",
            "title": "Fixture",
            "language": "en",
            "source_file": "fixture.pdf",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation("obs000001", "image_region", page=1, bbox=[100, 100, 500, 500]),
            make_observation("obs000002", "table_region", page=1, bbox=[100, 600, 500, 800]),
            make_observation(
                "obs000003",
                "text_region",
                page=1,
                bbox=[100, 510, 500, 540],
                text="Figure caption",
                role_hint="caption_text",
                attrs={
                    "source_kind": "figure_caption",
                    "visual_parent_observation_id": "obs000001",
                },
            ),
            make_observation(
                "obs000004",
                "text_region",
                page=1,
                bbox=[100, 550, 500, 580],
                text="Table caption",
                role_hint="caption_text",
                attrs={
                    "source_kind": "table_caption",
                    "visual_parent_observation_id": "obs000002",
                },
            ),
        ],
    )
    requests: list[dict] = []
    review = build_visual_relation_review(
        build_observed_index(observed),
        {"metadata": {"doc_id": "fixture"}, "pages": [{"page": 1, "body_lane": [80, 900]}]},
        {"metadata": {"doc_id": "fixture"}, "pages": [{"page": 1, "text_flow_action": "include"}]},
        {
            "metadata": {"doc_id": "fixture"},
            "tables": [],
            "unresolved_table_observation_runs": [],
            "excluded_table_observation_runs": [],
        },
        {"images": [{"image_id": "fixture-page", "source": {"page": 1}}]},
        review_callback=lambda request: requests.append(request)
        or {
            "groups": [],
            "unpaired_asset_observation_ids": [],
            "unpaired_caption_observation_ids": request["caption_observation_ids"],
        },
        model_name="fake",
    )

    assert review["visual_groups"][0]["caption_observation_ids"] == ["obs000003"]
    assert "obs000004" not in json.dumps(review)
    assert requests == []


def test_bounded_callback_can_group_only_supplied_same_page_endpoints() -> None:
    seen = []

    def callback(request: dict) -> dict:
        seen.append(request)
        return {
            "groups": [
                {
                    "asset_observation_ids": ["obs000001"],
                    "caption_observation_ids": ["obs000002", "obs000003"],
                    "confidence": "high",
                }
            ],
            "unpaired_asset_observation_ids": [],
            "unpaired_caption_observation_ids": [],
        }

    review = build_visual_relation_review(*_sources(), review_callback=callback, model_name="fake")

    assert seen[0]["page"] == 1
    assert seen[0]["page_asset_id"] == "page-0001-review"
    assert seen[0]["candidate_observation_ids"] == ["obs000001", "obs000002", "obs000003"]
    assert seen[0]["candidates"] == [
        {
            "observation_id": "obs000001",
            "kind": "image_region",
            "role_hint": "unknown",
            "bbox": [100, 100, 500, 500],
            "text": "",
        },
        {
            "observation_id": "obs000002",
            "kind": "text_region",
            "role_hint": "title_text",
            "bbox": [540, 340, 850, 370],
            "text": "A caption title",
        },
        {
            "observation_id": "obs000003",
            "kind": "text_region",
            "role_hint": "body_text",
            "bbox": [540, 380, 850, 450],
            "text": "The adjacent caption body.",
        },
    ]
    assert review["visual_groups"][0]["decision_source"] == "bounded_multimodal_review"
    assert review["unresolved_candidates"] == []


def test_multiple_images_are_one_ambiguous_candidate_without_a_model() -> None:
    index, layout, page_review, table_flow, page_assets = _sources()
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "x",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation("obs000001", "image_region", page=1, bbox=[100, 100, 400, 500]),
            make_observation("obs000004", "image_region", page=1, bbox=[500, 100, 900, 500]),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[200, 520, 800, 550],
                text="Caption",
                role_hint="caption_text",
            ),
        ],
    )
    del index
    review = build_visual_relation_review(
        build_observed_index(observed), layout, page_review, table_flow, page_assets
    )

    assert review["unresolved_candidates"][0]["asset_observation_ids"] == ["obs000001", "obs000004"]
    assert review["unresolved_candidates"][0]["caption_observation_ids"] == ["obs000002"]


def test_no_model_output_is_canonical_json_deterministic() -> None:
    first = build_visual_relation_review(*_sources())
    second = build_visual_relation_review(*_sources())

    assert json.dumps(
        first, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) == json.dumps(second, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_unique_exact_parser_caption_text_groups_without_parent_link() -> None:
    index, layout, page_review, table_flow, page_assets = _sources()
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "x",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "image_region",
                page=1,
                bbox=[100, 100, 500, 500],
                parser_payload={"raw": {"content": {"image_caption": ["exact"]}}},
            ),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[540, 340, 850, 370],
                text="exact",
                role_hint="caption_text",
            ),
        ],
    )
    del index

    review = build_visual_relation_review(
        build_observed_index(observed), layout, page_review, table_flow, page_assets
    )

    assert review["visual_groups"][0]["caption_observation_ids"] == ["obs000002"]
    assert review["visual_groups"][0]["decision_source"] == "parser_provenance"


def test_unique_exact_parser_caption_object_groups_without_parent_link() -> None:
    index, layout, page_review, table_flow, page_assets = _sources()
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "x",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "image_region",
                page=1,
                bbox=[100, 100, 500, 500],
                parser_payload={
                    "raw": {"content": {"image_caption": [{"type": "text", "content": "exact"}]}}
                },
            ),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[540, 340, 850, 370],
                text="exact",
                role_hint="caption_text",
            ),
        ],
    )
    del index

    review = build_visual_relation_review(
        build_observed_index(observed), layout, page_review, table_flow, page_assets
    )

    assert review["visual_groups"][0]["caption_observation_ids"] == ["obs000002"]


def test_page_review_excluded_plate_remains_visual_candidate() -> None:
    index, layout, page_review, table_flow, page_assets = _sources()
    page_review["pages"][0]["text_flow_action"] = "exclude"

    review = build_visual_relation_review(index, layout, page_review, table_flow, page_assets)

    assert review["unresolved_candidates"][0]["physical_pages"] == [1]


def test_callback_unpaired_endpoints_are_covered_by_model_evidence() -> None:
    def callback(_request: dict) -> dict:
        return {
            "groups": [],
            "unpaired_asset_observation_ids": ["obs000001"],
            "unpaired_caption_observation_ids": ["obs000002", "obs000003"],
        }

    review = build_visual_relation_review(*_sources(), review_callback=callback, model_name="fake")

    assert review["unpaired_asset_observation_ids"] == ["obs000001"]
    assert review["evidence"][0]["kind"] == "bounded_multimodal_review"


def test_invalid_callback_response_stays_explicitly_unresolved() -> None:
    review = build_visual_relation_review(
        *_sources(),
        review_callback=lambda _request: {
            "groups": [
                {
                    "asset_observation_ids": ["unknown"],
                    "caption_observation_ids": [],
                    "confidence": "high",
                }
            ],
            "unpaired_asset_observation_ids": [],
            "unpaired_caption_observation_ids": [],
        },
        model_name="fake",
    )

    assert review["visual_groups"] == []
    assert review["unresolved_candidates"][0]["reason"] == "model_unavailable_or_invalid"


def test_callback_failure_and_missing_page_asset_are_honest_unresolved_states() -> None:
    def fails(_request: dict) -> dict:
        raise RuntimeError("transport unavailable")

    failed = build_visual_relation_review(*_sources(), review_callback=fails, model_name="fake")
    index, layout, page_review, table_flow, _assets = _sources()
    calls: list[dict] = []
    unavailable = build_visual_relation_review(
        index,
        layout,
        page_review,
        table_flow,
        {"images": []},
        review_callback=lambda request: calls.append(request) or {},
        model_name="fake",
    )

    assert failed["unresolved_candidates"][0]["reason"] == "model_unavailable_or_invalid"
    assert unavailable["unresolved_candidates"][0]["reason"] == "model_unavailable_or_invalid"
    assert calls == []


def test_builder_does_not_mutate_read_only_observed_index() -> None:
    index, *sources = _sources()
    before = tuple(index.observations_by_id["obs000001"]["bbox"])

    build_visual_relation_review(index, *sources)

    assert tuple(index.observations_by_id["obs000001"]["bbox"]) == before
    with pytest.raises(TypeError):
        index.observations_by_id["obs000001"]["attrs"]["changed"] = True


def test_accepted_page_25_forms_one_group_through_bounded_callback() -> None:
    root = Path(__file__).resolve().parents[4]
    observed = json.loads(
        (root / "data/outputs/golden/observed/丝绸之路新史_observed.json").read_text(
            encoding="utf-8"
        )
    )
    page_review = json.loads(
        (
            root / "data/outputs/golden/page-review/丝绸之路新史/丝绸之路新史_page_review.json"
        ).read_text(encoding="utf-8")
    )
    index = build_observed_index(observed)
    table_flow = build_table_flow(observed, index, page_review)
    layout = build_page_layout_analysis(observed, index)
    review = build_visual_relation_review(
        index,
        layout,
        page_review,
        table_flow,
        {"images": [{"image_id": "page-0025-review", "source": {"page": 25}}]},
        review_callback=lambda request: (
            {
                "groups": [
                    {
                        "asset_observation_ids": request["asset_observation_ids"],
                        "caption_observation_ids": request["caption_observation_ids"],
                        "confidence": "high",
                    }
                ],
                "unpaired_asset_observation_ids": [],
                "unpaired_caption_observation_ids": [],
            }
            if request["page"] == 25
            else {
                "groups": [],
                "unpaired_asset_observation_ids": request["asset_observation_ids"],
                "unpaired_caption_observation_ids": request["caption_observation_ids"],
            }
        ),
        model_name="fake",
    )

    group = next(
        item for item in review["visual_groups"] if "obs000253" in item["asset_observation_ids"]
    )
    assert group["caption_observation_ids"] == ["obs000254", "obs000255"]
