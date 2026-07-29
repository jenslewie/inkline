from __future__ import annotations

import json
from pathlib import Path
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
    candidates, _ignored = build_text_candidates(
        observed,
        included_pages=pages,
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
