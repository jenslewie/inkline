from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from inkline.canonical import build_page_layout_analysis
from inkline.canonical.text_flow.aggregation import (
    aggregate_text_candidates,
    materialize_text_units,
)
from inkline.canonical.text_flow.candidates import build_text_candidates
from inkline.canonical.text_flow.layout import classify_text_candidates_by_layout

ROOT = Path(__file__).resolve().parents[4]
SILK_ROAD_OBSERVED = ROOT / "data/outputs/golden/observed/丝绸之路新史_observed.json"


def _silk_road_observed() -> dict[str, Any]:
    return json.loads(SILK_ROAD_OBSERVED.read_text(encoding="utf-8"))


def _silk_road_pages() -> list[dict[str, Any]]:
    return _silk_road_observed()["pages"]


def _classified_page_292_candidates() -> list[dict[str, Any]]:
    observed = _silk_road_observed()
    candidates, _ignored = build_text_candidates(
        observed,
        included_pages={292},
        anchor_groups_by_observation_id={},
    )
    classified = classify_text_candidates_by_layout(
        candidates,
        observed["pages"],
        page_layout=build_page_layout_analysis(observed),
    )
    wanted = {"obs002504", "obs002505", "obs002506"}
    return [candidate for candidate in classified if candidate["observation_id"] in wanted]


def _classified_silk_road_chapter_title_candidates() -> list[dict[str, Any]]:
    observed = _silk_road_observed()
    group = ("obs000395", "obs000396", "obs000397")
    candidates, _ignored = build_text_candidates(
        observed,
        included_pages={42},
        anchor_groups_by_observation_id=dict.fromkeys(group, group),
    )
    classified = classify_text_candidates_by_layout(
        candidates,
        observed["pages"],
        page_layout=build_page_layout_analysis(observed),
    )
    return [candidate for candidate in classified if candidate["observation_id"] in group]


def _classified_candidate(
    observation_id: str,
    *,
    page: int = 1,
    candidate_type: str = "body_text",
    classified_type: str = "paragraph",
    status: str = "resolved",
    layout_form: str | None = None,
    alignment: str | None = None,
    run_ids: list[str] | None = None,
    protected_anchor_group: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "candidate_type": candidate_type,
        "text": f"text {observation_id}",
        "page": page,
        "bbox": [100, 100, 500, 130],
        "spans": [{"page": page, "bbox": [100, 100, 500, 130]}],
        "role_hint": "body_text" if candidate_type == "body_text" else "title_text",
        "attrs": {"inline_runs": [{"type": "text", "text": f"text {observation_id}"}]},
        "parser_payload": {"source": observation_id},
        "protected_anchor_group": protected_anchor_group,
        "layout_decision": {
            "classified_type": classified_type,
            "status": status,
            "layout_form": layout_form,
            "alignment": alignment,
            "signals": ["fixture_signal"],
            "profile_source": "local",
            "same_page_run_observation_ids": run_ids or [observation_id],
            "cross_page_transitions": [],
        },
    }


def _logical_record(unit_type: str, observation_ids: list[str]) -> dict[str, Any]:
    return {
        "unit_type": unit_type,
        "text": "text",
        "page": 1,
        "pages": [1],
        "bbox": [100, 100, 500, 130],
        "spans": [{"page": 1, "bbox": [100, 100, 500, 130]}],
        "observation_ids": observation_ids,
        "role_hints": ["body_text"],
        "attrs": {},
        "parser_payloads": [{}],
    }


def test_aggregation_never_combines_paragraph_and_display_candidates() -> None:
    candidates = _classified_page_292_candidates()
    records = aggregate_text_candidates(candidates, _silk_road_pages())
    by_observation = {
        observation_id: record
        for record in records
        for observation_id in record["observation_ids"]
    }
    assert by_observation["obs002504"] is not by_observation["obs002505"]
    assert by_observation["obs002505"] is by_observation["obs002506"]
    assert by_observation["obs002504"]["unit_type"] == "paragraph"
    assert by_observation["obs002505"]["unit_type"] == "display_block"
    assert all("unit_id" not in record for record in records)


def test_direct_anchor_group_materializes_as_one_exact_heading_record() -> None:
    records = aggregate_text_candidates(
        _classified_silk_road_chapter_title_candidates(),
        _silk_road_pages(),
    )
    heading = next(record for record in records if record["unit_type"] == "heading")
    assert heading["observation_ids"] == ["obs000395", "obs000396", "obs000397"]
    assert heading["text"] == "第一章\n楼兰\n中亚的十字路口"


def test_final_identity_is_assigned_once_after_aggregation() -> None:
    records = [_logical_record("paragraph", ["obs000001"])]
    units = materialize_text_units(records)
    assert units[0]["unit_id"] == "tu000001"
    assert "unit_id" not in records[0]
    with pytest.raises(ValueError, match="already has unit_id"):
        materialize_text_units(units)


def test_ordinary_paragraphs_stay_separate_even_when_their_boxes_are_close() -> None:
    candidates = [
        _classified_candidate("obs000001"),
        _classified_candidate("obs000002"),
    ]

    records = aggregate_text_candidates(candidates, [{"page": 1, "width": 1000, "height": 1000}])

    assert [record["observation_ids"] for record in records] == [
        ["obs000001"],
        ["obs000002"],
    ]


def test_display_aggregation_requires_resolved_compatible_run_membership() -> None:
    candidates = [
        _classified_candidate(
            "obs000001",
            classified_type="display_block",
            layout_form="set_off_prose",
            alignment="left",
            run_ids=["obs000001", "obs000002"],
        ),
        _classified_candidate(
            "obs000002",
            classified_type="display_block",
            layout_form="set_off_prose",
            alignment="left",
            run_ids=["obs000001", "obs000002"],
        ),
        _classified_candidate(
            "obs000003",
            classified_type="display_block",
            status="uncertain",
            layout_form="set_off_prose",
            alignment="left",
            run_ids=["obs000003"],
        ),
    ]

    records = aggregate_text_candidates(candidates, [{"page": 1, "width": 1000, "height": 1000}])

    assert [record["observation_ids"] for record in records] == [
        ["obs000001", "obs000002"],
        ["obs000003"],
    ]


@pytest.mark.parametrize(
    ("layout_form", "alignment"),
    [("", "left"), ("set_off_prose", "")],
)
def test_display_aggregation_rejects_empty_layout_metadata(
    layout_form: str, alignment: str
) -> None:
    candidates = [
        _classified_candidate(
            "obs000001",
            classified_type="display_block",
            layout_form=layout_form,
            alignment=alignment,
            run_ids=["obs000001", "obs000002"],
        ),
        _classified_candidate(
            "obs000002",
            classified_type="display_block",
            layout_form=layout_form,
            alignment=alignment,
            run_ids=["obs000001", "obs000002"],
        ),
    ]

    records = aggregate_text_candidates(
        candidates, [{"page": 1, "width": 1000, "height": 1000}]
    )

    assert [record["observation_ids"] for record in records] == [
        ["obs000001"],
        ["obs000002"],
    ]


def test_protected_anchor_member_blocks_interleaved_display_aggregation() -> None:
    candidates = [
        _classified_candidate(
            "a",
            classified_type="display_block",
            layout_form="set_off_prose",
            alignment="left",
            run_ids=["a", "x", "b"],
            protected_anchor_group=["a", "b"],
        ),
        _classified_candidate(
            "x",
            classified_type="display_block",
            layout_form="set_off_prose",
            alignment="left",
            run_ids=["a", "x", "b"],
        ),
        _classified_candidate(
            "b",
            classified_type="display_block",
            layout_form="set_off_prose",
            alignment="left",
            run_ids=["a", "x", "b"],
            protected_anchor_group=["a", "b"],
        ),
    ]

    records = aggregate_text_candidates(
        candidates, [{"page": 1, "width": 1000, "height": 1000}]
    )

    assert [record["observation_ids"] for record in records] == [["a"], ["x"], ["b"]]


def test_layout_fragments_preserve_one_exact_decision_per_display_observation() -> None:
    candidates = [
        _classified_candidate(
            "obs000001",
            classified_type="display_block",
            layout_form="set_off_prose",
            alignment="left",
            run_ids=["obs000001", "obs000002"],
        ),
        _classified_candidate(
            "obs000002",
            classified_type="display_block",
            layout_form="set_off_prose",
            alignment="left",
            run_ids=["obs000001", "obs000002"],
        ),
    ]

    record = aggregate_text_candidates(candidates, [{"page": 1, "width": 1000, "height": 1000}])[0]

    assert record["attrs"]["layout_fragments"] == [
        {
            "observation_id": "obs000001",
            "page": 1,
            "classified_type": "display_block",
            "status": "resolved",
            "layout_form": "set_off_prose",
            "signals": ["fixture_signal"],
        },
        {
            "observation_id": "obs000002",
            "page": 1,
            "classified_type": "display_block",
            "status": "resolved",
            "layout_form": "set_off_prose",
            "signals": ["fixture_signal"],
        },
    ]


def test_materialization_deep_copies_nested_logical_record_state() -> None:
    records = [_logical_record("paragraph", ["obs000001"])]

    units = materialize_text_units(records)
    units[0]["attrs"]["changed"] = True

    assert records == [_logical_record("paragraph", ["obs000001"])]
