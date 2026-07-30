from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from inkline.canonical import build_page_layout_analysis, make_observed_page
from inkline.canonical.text_flow.candidates import build_text_candidates
from inkline.canonical.text_flow.layout import classify_text_candidates_by_layout

ROOT = Path(__file__).resolve().parents[4]
SILK_ROAD_OBSERVED = ROOT / "data/outputs/golden/observed/丝绸之路新史_observed.json"
LAYOUT_DECISION_FIELDS = {
    "classified_type",
    "status",
    "layout_form",
    "alignment",
    "signals",
    "profile_source",
    "same_page_run_observation_ids",
    "cross_page_transitions",
}


def _silk_road_decisions(pages: set[int]) -> dict[str, dict[str, Any]]:
    observed = json.loads(SILK_ROAD_OBSERVED.read_text(encoding="utf-8"))
    context_pages = pages | {page + 1 for page in pages}
    candidates, _ignored = build_text_candidates(
        observed,
        included_pages=context_pages,
        anchor_groups_by_observation_id={},
    )
    classified = classify_text_candidates_by_layout(
        candidates,
        observed["pages"],
        page_layout=build_page_layout_analysis(observed),
    )
    return {
        candidate["observation_id"]: candidate["layout_decision"]
        for candidate in classified
        if int(candidate["page"]) in pages
    }


def _body_candidate(
    observation_id: str,
    *,
    page: int,
    bbox: list[float] | None,
) -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "candidate_type": "body_text",
        "text": "Body",
        "page": page,
        "bbox": bbox,
        "spans": [],
        "role_hint": "body_text",
        "attrs": {},
        "parser_payload": {},
        "protected_anchor_group": None,
    }


def _reference_candidate(
    observation_id: str,
    *,
    page: int,
    bbox: list[float],
    marker_sequence: list[str] | None,
) -> dict[str, Any]:
    parser_raw: dict[str, Any] = {}
    if marker_sequence is not None:
        parser_raw["_middle_page_inline_markers"] = marker_sequence
    return {
        **_body_candidate(observation_id, page=page, bbox=bbox),
        "candidate_type": "list_item",
        "role_hint": "reference_text",
        "parser_payload": {"raw_type": "ref_text", "raw": parser_raw},
    }


def _page_layout_without_profile() -> dict[str, Any]:
    return {
        "metadata": {
            "schema_name": "inkline_page_layout_analysis",
            "schema_version": "0.1-shadow",
            "doc_id": "book",
        },
        "book_layout_profile": {
            "profile_scope": "book",
            "source_page_count": 0,
            "body_width": None,
            "indent_unit": None,
            "line_height": None,
            "normal_gap_y": None,
            "display_gap_y": None,
        },
        "pages": [
            {
                "page": 1,
                "page_size": {"width": 1000.0, "height": 1000.0},
                "body_lane": None,
                "visual_regions": [],
                "coverage": {"profile_status": "paragraph_without_profile"},
                "role_signals": {
                    "kind_counts": {},
                    "role_hint_counts": {},
                    "content_count": 0,
                    "text_count": 0,
                    "visual_count": 0,
                    "body_zone_footnote_count": 0,
                    "visual_area_ratio": 0.0,
                    "text_area_ratio": 0.0,
                    "centered_text_ratio": 0.0,
                    "tall_text_count": 0,
                },
            }
        ],
        "audit": {},
    }


def _page_layout_with_profile() -> dict[str, Any]:
    page_layout = _page_layout_without_profile()
    page_layout["book_layout_profile"] = {
        "profile_scope": "book",
        "source_page_count": 1,
        "body_width": 800.0,
        "indent_unit": 50.0,
        "line_height": 30.0,
        "normal_gap_y": 10.0,
        "display_gap_y": 40.0,
    }
    page_layout["pages"][0]["body_lane"] = {
        "profile_scope": "page",
        "profile_source": "local",
        "page_width": 1000.0,
        "page_height": 1000.0,
        "body_left": 100.0,
        "body_right": 900.0,
        "body_width": 800.0,
        "book_body_width": 800.0,
        "body_width_delta": 0.0,
        "indent_unit": 50.0,
        "line_height": 30.0,
        "normal_gap_y": 10.0,
        "display_gap_y": 40.0,
        "reference_fragment_count": 2,
    }
    page_layout["pages"][0]["coverage"] = {"profile_status": "profiled"}
    return page_layout


def _page_layout_for_pages(page_count: int) -> dict[str, Any]:
    page_layout = _page_layout_with_profile()
    page_layout["book_layout_profile"]["source_page_count"] = page_count
    template = page_layout["pages"][0]
    page_layout["pages"] = []
    for page in range(1, page_count + 1):
        record = json.loads(json.dumps(template))
        record["page"] = page
        page_layout["pages"].append(record)
    return page_layout


def _decision(classified: list[dict[str, Any]], observation_id: str) -> dict[str, Any]:
    return next(
        candidate["layout_decision"]
        for candidate in classified
        if candidate["observation_id"] == observation_id
    )


def _terminal_right_aligned_candidate_with_body_on_next_page() -> SimpleNamespace:
    candidates = [
        _body_candidate("obs000001", page=1, bbox=[100, 100, 900, 750]),
        _body_candidate("obs000002", page=1, bbox=[600, 820, 900, 850]),
        _body_candidate("obs000003", page=2, bbox=[100, 100, 900, 300]),
    ]
    pages = [make_observed_page(page, width=1000, height=1000) for page in (1, 2)]
    return SimpleNamespace(
        candidates=candidates,
        pages=pages,
        page_layout=_page_layout_for_pages(2),
    )


def _classify_three_page_display_fixture() -> list[dict[str, Any]]:
    candidates = [
        _body_candidate("obs000001", page=1, bbox=[100, 100, 900, 650]),
        _body_candidate("obs000002", page=1, bbox=[180, 700, 850, 900]),
        _body_candidate("obs000003", page=2, bbox=[180, 100, 850, 900]),
        _body_candidate("obs000004", page=3, bbox=[180, 100, 850, 300]),
        _body_candidate("obs000005", page=3, bbox=[100, 350, 900, 600]),
    ]
    pages = [make_observed_page(page, width=1000, height=1000) for page in (1, 2, 3)]
    return classify_text_candidates_by_layout(
        candidates,
        pages,
        page_layout=_page_layout_for_pages(3),
    )


def test_same_page_layout_separates_body_intro_from_short_display_run() -> None:
    decisions = _silk_road_decisions({292})
    assert decisions["obs002504"]["classified_type"] == "paragraph"
    assert decisions["obs002505"]["classified_type"] == "display_block"
    assert decisions["obs002506"]["classified_type"] == "display_block"
    assert decisions["obs002504"]["same_page_run_observation_ids"] == ["obs002504"]
    assert decisions["obs002505"]["same_page_run_observation_ids"] == [
        "obs002505",
        "obs002506",
    ]


def test_page_159_quote_and_following_body_intro_receive_distinct_types() -> None:
    decisions = _silk_road_decisions({159})
    assert decisions["obs001363"]["classified_type"] == "display_block"
    assert decisions["obs001364"]["classified_type"] == "paragraph"


def test_uncertain_body_candidate_is_independent_paragraph() -> None:
    candidate = _body_candidate("obs000001", page=1, bbox=None)
    classified = classify_text_candidates_by_layout(
        [candidate],
        [make_observed_page(1, width=1000, height=1000)],
        page_layout=_page_layout_without_profile(),
    )
    decision = classified[0]["layout_decision"]
    assert set(decision) == LAYOUT_DECISION_FIELDS
    assert decision["classified_type"] == "paragraph"
    assert decision["status"] == "uncertain"
    assert decision["same_page_run_observation_ids"] == ["obs000001"]
    assert "missing_bbox" in decision["signals"]


def test_non_body_candidate_keeps_explicit_structural_role() -> None:
    candidate = {
        **_body_candidate("obs000002", page=1, bbox=[100, 100, 900, 130]),
        "candidate_type": "heading",
        "role_hint": "title_text",
        "protected_anchor_group": ["obs000002"],
    }
    classified = classify_text_candidates_by_layout(
        [candidate],
        [make_observed_page(1, width=1000, height=1000)],
        page_layout=_page_layout_without_profile(),
    )
    decision = classified[0]["layout_decision"]
    assert set(decision) == LAYOUT_DECISION_FIELDS
    assert decision["classified_type"] == "heading"
    assert decision["status"] == "resolved"
    assert decision["signals"] == ["explicit_structural_role"]


def test_parser_marked_trailing_reference_block_is_classified_as_footnotes() -> None:
    markers = ["1", "2"]
    candidates = [
        _body_candidate("body", page=1, bbox=[100, 100, 900, 500]),
        _reference_candidate(
            "note-1",
            page=1,
            bbox=[100, 650, 900, 720],
            marker_sequence=markers,
        ),
        _reference_candidate(
            "note-2",
            page=1,
            bbox=[100, 730, 900, 800],
            marker_sequence=markers,
        ),
    ]

    classified = classify_text_candidates_by_layout(
        candidates,
        [make_observed_page(1, width=1000, height=1000)],
        page_layout=_page_layout_with_profile(),
    )

    note_decisions = [_decision(classified, observation_id) for observation_id in ("note-1", "note-2")]
    assert all(decision["classified_type"] == "footnote" for decision in note_decisions)
    assert all(
        decision["signals"] == ["parser_marked_trailing_page_reference_block"]
        for decision in note_decisions
    )
    assert all(
        decision["same_page_run_observation_ids"] == ["note-1", "note-2"]
        for decision in note_decisions
    )


def test_reference_list_without_complete_parser_marker_evidence_stays_list_items() -> None:
    candidates = [
        _body_candidate("body", page=1, bbox=[100, 100, 900, 500]),
        _reference_candidate(
            "reference",
            page=1,
            bbox=[100, 650, 900, 720],
            marker_sequence=None,
        ),
    ]

    classified = classify_text_candidates_by_layout(
        candidates,
        [make_observed_page(1, width=1000, height=1000)],
        page_layout=_page_layout_with_profile(),
    )

    assert _decision(classified, "reference")["classified_type"] == "list_item"


def test_structural_boundary_without_geometric_gap_does_not_create_display_gap() -> None:
    heading = {
        **_body_candidate("obs000003", page=1, bbox=[100, 100, 900, 130]),
        "candidate_type": "heading",
        "role_hint": "title_text",
        "protected_anchor_group": ["obs000003"],
    }
    inset_body = _body_candidate("obs000004", page=1, bbox=[200, 130, 800, 160])

    classified = classify_text_candidates_by_layout(
        [heading, inset_body],
        [make_observed_page(1, width=1000, height=1000)],
        page_layout=_page_layout_with_profile(),
    )

    decision = classified[1]["layout_decision"]
    assert decision["classified_type"] == "paragraph"
    assert "display_gap_before" not in decision["signals"]


def test_cross_page_joint_context_classifies_both_quote_fragments_before_merge() -> None:
    decisions = _silk_road_decisions({253, 254})
    left = decisions["obs002159"]
    right = decisions["obs002163"]
    assert left["classified_type"] == "display_block"
    assert right["classified_type"] == "display_block"
    assert left["cross_page_transitions"] == right["cross_page_transitions"]
    assert left["cross_page_transitions"][0]["left_page"] == 253
    assert left["cross_page_transitions"][0]["right_page"] == 254


def test_terminal_right_aligned_date_requires_structural_following_boundary() -> None:
    decisions = _silk_road_decisions({9})
    assert decisions["obs000111"]["classified_type"] == "display_block"
    assert "terminal_right_aligned_attribution" in decisions["obs000111"]["signals"]

    unbounded = _terminal_right_aligned_candidate_with_body_on_next_page()
    classified = classify_text_candidates_by_layout(
        unbounded.candidates,
        unbounded.pages,
        page_layout=unbounded.page_layout,
    )
    assert _decision(classified, "obs000002")["classified_type"] == "paragraph"


def test_three_page_joint_display_run_records_two_adjacent_transitions() -> None:
    classified = _classify_three_page_display_fixture()
    transitions = _decision(classified, "obs000002")["cross_page_transitions"]
    assert [(item["left_page"], item["right_page"]) for item in transitions] == [
        (1, 2),
        (2, 3),
    ]


def test_isolated_cross_page_set_off_candidates_do_not_invent_outer_gaps() -> None:
    candidates = [
        _body_candidate("obs000001", page=1, bbox=[180, 700, 850, 900]),
        _body_candidate("obs000002", page=2, bbox=[180, 100, 850, 300]),
    ]
    pages = [make_observed_page(page, width=1000, height=1000) for page in (1, 2)]

    classified = classify_text_candidates_by_layout(
        candidates,
        pages,
        page_layout=_page_layout_for_pages(2),
    )

    assert _decision(classified, "obs000001")["cross_page_transitions"] == []
    assert _decision(classified, "obs000002")["cross_page_transitions"] == []


def test_terminal_right_aligned_without_preceding_gap_is_uncertain_paragraph() -> None:
    candidates = [
        _body_candidate("obs000001", page=1, bbox=[100, 700, 900, 850]),
        _body_candidate("obs000002", page=1, bbox=[600, 850, 900, 900]),
        _body_candidate("obs000003", page=2, bbox=[100, 100, 900, 300]),
    ]
    pages = [make_observed_page(page, width=1000, height=1000) for page in (1, 2)]

    classified = classify_text_candidates_by_layout(
        candidates,
        pages,
        page_layout=_page_layout_for_pages(2),
    )

    decision = _decision(classified, "obs000002")
    assert decision["classified_type"] == "paragraph"
    assert "terminal_right_aligned_without_preceding_outer_gap" in decision["signals"]
    assert "terminal_right_aligned_without_structural_boundary" in decision["signals"]
    assert "display_gap_after" not in decision["signals"]


def test_terminal_mixed_alignment_short_line_cluster_is_display() -> None:
    candidates = [
        _body_candidate("body", page=1, bbox=[100, 100, 900, 500]),
        _body_candidate("left-1", page=1, bbox=[150, 525, 650, 545]),
        _body_candidate("left-2", page=1, bbox=[150, 560, 500, 580]),
        _body_candidate("right-1", page=1, bbox=[700, 610, 900, 630]),
        _body_candidate("right-2", page=1, bbox=[730, 645, 900, 665]),
    ]

    classified = classify_text_candidates_by_layout(
        candidates,
        [make_observed_page(1, width=1000, height=1000)],
        page_layout=_page_layout_with_profile(),
    )

    left_decisions = [_decision(classified, value) for value in ("left-1", "left-2")]
    right_decisions = [_decision(classified, value) for value in ("right-1", "right-2")]
    assert {decision["classified_type"] for decision in left_decisions} == {"display_block"}
    assert {decision["layout_form"] for decision in left_decisions} == {"short_line_group"}
    assert {decision["classified_type"] for decision in right_decisions} == {"display_block"}
    assert {decision["layout_form"] for decision in right_decisions} == {"attribution"}
    assert all(
        "terminal_right_aligned_without_structural_boundary" not in decision["signals"]
        for decision in right_decisions
    )


def test_terminal_attribution_does_not_promote_single_indented_body_fragment() -> None:
    candidates = [
        _body_candidate("body", page=1, bbox=[100, 100, 900, 500]),
        _body_candidate("indented-body", page=1, bbox=[150, 525, 650, 565]),
        _body_candidate("right-1", page=1, bbox=[700, 610, 900, 630]),
        _body_candidate("right-2", page=1, bbox=[730, 645, 900, 665]),
    ]

    classified = classify_text_candidates_by_layout(
        candidates,
        [make_observed_page(1, width=1000, height=1000)],
        page_layout=_page_layout_with_profile(),
    )

    assert _decision(classified, "indented-body")["classified_type"] == "paragraph"
    for observation_id in ("right-1", "right-2"):
        decision = _decision(classified, observation_id)
        assert decision["classified_type"] == "paragraph"
        assert "terminal_right_aligned_without_structural_boundary" in decision["signals"]


def test_terminal_attribution_rejects_heading_after_next_page_body() -> None:
    heading = {
        **_body_candidate("obs000004", page=2, bbox=[300, 300, 700, 340]),
        "candidate_type": "heading",
        "role_hint": "title_text",
        "protected_anchor_group": ["obs000004"],
    }
    candidates = [
        _body_candidate("obs000001", page=1, bbox=[100, 700, 900, 850]),
        _body_candidate("obs000002", page=1, bbox=[600, 870, 900, 900]),
        _body_candidate("obs000003", page=2, bbox=[100, 100, 900, 200]),
        heading,
    ]
    pages = [make_observed_page(page, width=1000, height=1000) for page in (1, 2)]
    page_layout = _page_layout_for_pages(2)
    page_layout["pages"][1]["role_signals"]["role_hint_counts"] = {
        "body_text": 1,
        "title_text": 1,
    }

    classified = classify_text_candidates_by_layout(
        candidates,
        pages,
        page_layout=page_layout,
    )

    decision = _decision(classified, "obs000002")
    assert decision["classified_type"] == "paragraph"
    assert "terminal_right_aligned_without_structural_boundary" in decision["signals"]


def test_terminal_attribution_rejects_next_page_caption_title() -> None:
    caption_title = {
        **_body_candidate("obs000003", page=2, bbox=[200, 100, 500, 140]),
        "role_hint": "title_text",
        "attrs": {"layout_role": "caption_candidate"},
    }
    candidates = [
        _body_candidate("obs000001", page=1, bbox=[100, 700, 900, 850]),
        _body_candidate("obs000002", page=1, bbox=[600, 870, 900, 900]),
        caption_title,
    ]
    pages = [make_observed_page(page, width=1000, height=1000) for page in (1, 2)]
    page_layout = _page_layout_for_pages(2)
    page_layout["pages"][1]["role_signals"]["role_hint_counts"] = {"title_text": 1}

    classified = classify_text_candidates_by_layout(
        candidates,
        pages,
        page_layout=page_layout,
    )

    decision = _decision(classified, "obs000002")
    assert decision["classified_type"] == "paragraph"
    assert "terminal_right_aligned_without_structural_boundary" in decision["signals"]
