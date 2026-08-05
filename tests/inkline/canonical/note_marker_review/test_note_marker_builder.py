from __future__ import annotations

from inkline.canonical import (
    ValidationError,
    build_observed_index,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.note_marker_review import (
    build_note_marker_review,
    build_note_marker_review_plan,
)


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
        [
            make_observed_page(1, width=100, height=100),
            make_observed_page(2, width=100, height=100),
        ],
        [
            make_observation(
                "obs000001",
                "footnote_region",
                page=1,
                bbox=[0, 80, 100, 100],
                text="1 Note definition",
                role_hint="footnote_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[0, 0, 100, 20],
                text="Body reference 1 here",
                role_hint="body_text",
                attrs={"note_refs": [{"marker": "1", "source": "parser"}]},
            ),
            make_observation(
                "obs000003",
                "text_region",
                page=2,
                bbox=[0, 0, 100, 20],
                text="Ordinary body",
                role_hint="body_text",
            ),
        ],
    )
    index = build_observed_index(observed)
    layout = {
        "metadata": {"doc_id": "sample"},
        "pages": [
            {"page": 1, "page_size": {"width": 100, "height": 100}},
            {"page": 2, "page_size": {"width": 100, "height": 100}},
        ],
    }
    systems = {
        "metadata": {"doc_id": "sample"},
        "evidence": [
            {
                "evidence_id": "nse000001",
                "observation_ids": ["obs000001"],
                "pages": [1],
            }
        ],
        "note_systems": [
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
        ],
        "unresolved_system_candidates": [],
    }
    page_assets = {
        "images": [
            {"image_id": "page-0001-review", "source": {"page": 1}},
            {"image_id": "page-0002-review", "source": {"page": 2}},
        ]
    }
    return index, layout, systems, page_assets


def test_plan_is_deterministic_and_reviews_explicit_definition_and_reference_regions() -> None:
    index, layout, systems, _ = _sources()

    first = build_note_marker_review_plan(index, layout, systems)
    second = build_note_marker_review_plan(index, layout, systems)

    assert first == second
    assert [request["region_kind"] for request in first["review_requests"]] == [
        "definition",
        "reference",
    ]
    assert first["review_requests"][0]["regions"][0]["observation_ids"] == ["obs000001"]
    assert first["review_requests"][1]["regions"][0]["observation_ids"] == ["obs000002"]
    assert first["not_required_note_system_ids"] == []
    assert first["unresolved_note_system_ids"] == []


def test_chapter_plan_keeps_cross_page_reference_candidates_and_all_parser_shapes() -> None:
    observed = make_observed_document(
        {
            "doc_id": "chapter-sample",
            "title": "Chapter sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [
            make_observed_page(1, width=100, height=100),
            make_observed_page(2, width=100, height=100),
        ],
        [
            make_observation(
                "obs000001",
                "footnote_region",
                page=1,
                bbox=[0, 80, 100, 100],
                text="1 Note definition",
                role_hint="footnote_text",
            ),
            make_observation(
                "obs000002",
                "footnote_region",
                page=2,
                bbox=[0, 0, 100, 20],
                text="Reference marker",
                role_hint="reference_text",
            ),
            make_observation(
                "obs000003",
                "image_region",
                page=2,
                bbox=[0, 20, 100, 40],
                attrs={"inline_runs": [{"type": "note_ref", "marker": "1"}]},
            ),
        ],
    )
    index = build_observed_index(observed)
    layout = {
        "metadata": {"doc_id": "chapter-sample"},
        "pages": [
            {"page": 1, "page_size": {"width": 100, "height": 100}},
            {"page": 2, "page_size": {"width": 100, "height": 100}},
        ],
    }
    systems = {
        "metadata": {"doc_id": "chapter-sample"},
        "evidence": [
            {"evidence_id": "nse000001", "observation_ids": ["obs000001"], "pages": [1]}
        ],
        "note_systems": [
            {
                "note_system_id": "ns000001",
                "kind": "chapter_endnote",
                "definition_ranges": [[1, 1]],
                "reference_scope": "chapter",
                "marker_styles": ["numeric"],
                "reset_policy": "chapter",
                "evidence_ids": ["nse000001"],
                "confidence": "high",
            }
        ],
        "unresolved_system_candidates": [],
    }

    plan = build_note_marker_review_plan(index, layout, systems)

    reference_request = plan["review_requests"][1]
    assert reference_request["region_kind"] == "reference"
    assert [region["page"] for region in reference_request["regions"]] == [2, 2]
    assert [
        observation_id
        for region in reference_request["regions"]
        for observation_id in region["observation_ids"]
    ] == ["obs000002", "obs000003"]


def test_marker_review_callback_receives_one_bounded_request_and_found_marker() -> None:
    index, layout, systems, assets = _sources()
    plan = build_note_marker_review_plan(index, layout, systems)
    requests: list[dict] = []

    def callback(request: dict) -> dict:
        requests.append(request)
        if request["region_kind"] == "definition":
            return {
                "markers": [
                    {
                        "marker": "1",
                        "page": 1,
                        "observation_id": "obs000001",
                        "bbox": [0, 80, 5, 85],
                        "adjacent_text": "1 Note",
                        "confidence": "high",
                    }
                ]
            }
        return {"markers": []}

    review = build_note_marker_review(
        index, assets, plan, review_callback=callback, model_name="test-model"
    )

    assert len(requests) == 2
    assert requests[0]["review_request_id"] == "nmp000001"
    assert requests[0]["regions"] == plan["review_requests"][0]["regions"]
    assert requests[0]["observation_ids"] == ["obs000001"]
    assert requests[0]["page_asset_ids"] == ["page-0001-review"]
    assert review["outcomes"][0]["status"] == "found"
    assert review["outcomes"][1]["status"] == "absent"


def test_plan_partitions_no_candidate_and_unresolved_systems_once() -> None:
    index, layout, systems, _ = _sources()
    systems["note_systems"].extend(
        [
            {
                "note_system_id": "ns000002",
                "kind": "page_footnote",
                "definition_ranges": [[2, 2]],
                "reference_scope": "page",
                "marker_styles": ["numeric"],
                "reset_policy": "page",
                "evidence_ids": [],
                "confidence": "medium",
            },
            {
                "note_system_id": "ns000003",
                "kind": "book_endnote",
                "definition_ranges": [[2, 2]],
                "reference_scope": "unresolved",
                "marker_styles": ["unknown"],
                "reset_policy": "unknown",
                "evidence_ids": [],
                "confidence": "low",
            },
        ]
    )

    plan = build_note_marker_review_plan(index, layout, systems)

    assert plan["not_required_note_system_ids"] == ["ns000002"]
    assert plan["unresolved_note_system_ids"] == ["ns000003"]
    request_systems = {request["note_system_id"] for request in plan["review_requests"]}
    assert request_systems == {"ns000001"}
    assert request_systems.isdisjoint(plan["not_required_note_system_ids"])
    assert request_systems.isdisjoint(plan["unresolved_note_system_ids"])


def test_marker_review_keeps_not_run_failed_and_unresolved_distinct() -> None:
    index, layout, systems, assets = _sources()
    plan = build_note_marker_review_plan(index, layout, systems)

    not_run = build_note_marker_review(index, assets, plan)
    assert {outcome["status"] for outcome in not_run["outcomes"]} == {"not_run"}

    failed = build_note_marker_review(
        index,
        assets,
        plan,
        review_callback=lambda _request: (_ for _ in ()).throw(RuntimeError("timeout")),
        model_name="test-model",
    )
    assert {outcome["status"] for outcome in failed["outcomes"]} == {"failed"}
    assert all(outcome["failure_reason"] for outcome in failed["outcomes"])

    unresolved = build_note_marker_review(
        index,
        assets,
        plan,
        review_callback=lambda _request: {"not_markers": []},
        model_name="test-model",
    )
    assert {outcome["status"] for outcome in unresolved["outcomes"]} == {"unresolved"}


def test_marker_review_rejects_invalid_adjacent_anchor_and_out_of_region_asset() -> None:
    index, layout, systems, assets = _sources()
    plan = build_note_marker_review_plan(index, layout, systems)
    review = build_note_marker_review(
        index,
        assets,
        plan,
        review_callback=lambda request: {
            "markers": [
                {
                    "marker": "1",
                    "page": 1,
                    "observation_id": "obs000001",
                    "bbox": [0, 80, 5, 85],
                    "adjacent_text": "1 Note",
                    "confidence": "high",
                }
            ]
        }
        if request["region_kind"] == "definition"
        else {"markers": []},
        model_name="test-model",
    )
    review["outcomes"][0]["markers"][0]["adjacent_text"] = "not in source"

    try:
        from inkline.canonical.note_marker_review import validate_note_marker_review_against_plan

        validate_note_marker_review_against_plan(review, plan, index, assets)
    except ValidationError:
        pass
    else:
        raise AssertionError("invalid marker evidence must be rejected")
