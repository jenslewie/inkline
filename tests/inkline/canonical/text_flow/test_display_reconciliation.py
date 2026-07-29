from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from inkline.canonical import build_page_layout_analysis
from inkline.canonical.text_flow.aggregation import aggregate_text_candidates
from inkline.canonical.text_flow.candidates import build_text_candidates
from inkline.canonical.text_flow.layout import classify_text_candidates_by_layout
from inkline.canonical.text_flow.reconcile import (
    reconcile_cross_page_displays,
    reconcile_cross_page_footnotes,
    reconcile_text_flow_records,
    reconcile_text_records,
)

ROOT = Path(__file__).resolve().parents[4]
SILK_ROAD_OBSERVED = ROOT / "data/outputs/golden/observed/丝绸之路新史_observed.json"


def _record(
    observation_id: str,
    text: str,
    *,
    page: int,
    bbox: list[float],
    unit_type: str = "display_block",
    layout_form: str | None = "short_line_group",
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "inline_runs": [{"type": "text", "text": text}],
        "source_tags": [observation_id],
    }
    if layout_form is not None:
        attrs["layout_form"] = layout_form
    if unit_type == "display_block":
        attrs["alignment"] = "left"
    return {
        "unit_type": unit_type,
        "text": text,
        "page": page,
        "pages": [page],
        "bbox": deepcopy(bbox),
        "spans": [{"page": page, "bbox": deepcopy(bbox)}],
        "observation_ids": [observation_id],
        "role_hints": [
            "footnote_text" if unit_type == "footnote" else "body_text"
        ],
        "attrs": attrs,
        "parser_payloads": [{"source": observation_id}],
    }


def _pages(*page_numbers: int) -> list[dict[str, Any]]:
    return [
        {"page": page, "width": 1000.0, "height": 1000.0}
        for page in page_numbers
    ]


def _page_layout(*page_numbers: int) -> dict[str, Any]:
    return {
        "pages": [
            {
                "page": page,
                "page_size": {"width": 1000.0, "height": 1000.0},
                "body_lane": {
                    "body_left": 100.0,
                    "body_right": 900.0,
                    "page_height": 1000.0,
                    "line_height": 30.0,
                },
            }
            for page in page_numbers
        ]
    }


def _cross_page_pair(
    left_type: str = "display_block",
    right_type: str = "display_block",
    *,
    layout_form: str = "short_line_group",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return (
        [
            _record(
                "left",
                "left",
                page=1,
                bbox=[200.0, 850.0, 500.0, 920.0],
                unit_type=left_type,
                layout_form=layout_form,
            ),
            _record(
                "right",
                "right",
                page=2,
                bbox=[210.0, 100.0, 420.0, 160.0],
                unit_type=right_type,
                layout_form=layout_form,
            ),
        ],
        _pages(1, 2),
        _page_layout(1, 2),
    )


def _display_pair(
    layout_form: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return _cross_page_pair(layout_form=layout_form)


def _reconciled_text(
    fixture: tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]],
) -> str:
    records, pages, page_layout = fixture
    return reconcile_cross_page_displays(records, pages, page_layout)[0]["text"]


def _record_with_observation_id(
    records: list[dict[str, Any]], observation_id: str
) -> dict[str, Any]:
    return next(
        record for record in records if observation_id in record["observation_ids"]
    )


def _silk_road_page_291_292_records() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    observed = json.loads(SILK_ROAD_OBSERVED.read_text(encoding="utf-8"))
    page_layout = build_page_layout_analysis(observed)
    candidates, _ignored = build_text_candidates(
        observed,
        included_pages={291, 292},
        anchor_groups_by_observation_id={},
    )
    classified = classify_text_candidates_by_layout(
        candidates,
        observed["pages"],
        page_layout=page_layout,
    )
    records = aggregate_text_candidates(classified, observed["pages"])
    return (
        reconcile_cross_page_footnotes(records, page_layout),
        observed["pages"],
        page_layout,
    )


def test_display_continues_across_page_291_292_footnotes() -> None:
    records, pages, page_layout = _silk_road_page_291_292_records()
    original = deepcopy(records)

    reconciled = reconcile_cross_page_displays(records, pages, page_layout)

    display = _record_with_observation_id(reconciled, "obs002497")
    assert records == original
    assert display["observation_ids"] == [
        "obs002497",
        "obs002498",
        "obs002499",
        "obs002503",
    ]
    assert display["pages"] == [291, 292]
    assert display["unit_type"] == "display_block"
    footnote = _record_with_observation_id(reconciled, "obs002500")
    assert footnote["unit_type"] == "footnote"
    assert display["attrs"]["merge_events"][-1]["reason"] == (
        "cross_page_display_block_continuation"
    )
    assert display["attrs"]["merge_events"][-1][
        "interrupting_observation_ids"
    ] == ["obs002500"]


def test_display_joiner_depends_on_layout_form() -> None:
    assert _reconciled_text(_display_pair("short_line_group")) == "left\nright"
    assert _reconciled_text(_display_pair("set_off_text")) == "leftright"


@pytest.mark.parametrize(
    ("left_type", "right_type"),
    [("paragraph", "display_block"), ("display_block", "paragraph")],
)
def test_display_reconciliation_never_changes_endpoint_types(
    left_type: str,
    right_type: str,
) -> None:
    records, pages, page_layout = _cross_page_pair(left_type, right_type)

    reconciled = reconcile_cross_page_displays(records, pages, page_layout)

    assert reconciled == records
    assert [record["unit_type"] for record in reconciled] == [
        left_type,
        right_type,
    ]


def test_three_page_display_audits_each_transition_and_keeps_footnotes() -> None:
    records = [
        _record("page-1", "A", page=1, bbox=[200.0, 850.0, 500.0, 920.0]),
        _record(
            "note-1",
            "Page one note",
            page=1,
            bbox=[100.0, 940.0, 900.0, 980.0],
            unit_type="footnote",
            layout_form=None,
        ),
        _record("page-2", "B", page=2, bbox=[210.0, 100.0, 510.0, 920.0]),
        _record(
            "note-2",
            "Page two note",
            page=2,
            bbox=[100.0, 940.0, 900.0, 980.0],
            unit_type="footnote",
            layout_form=None,
        ),
        _record("page-3", "C", page=3, bbox=[220.0, 100.0, 430.0, 160.0]),
    ]

    reconciled = reconcile_cross_page_displays(
        records,
        _pages(1, 2, 3),
        _page_layout(1, 2, 3),
    )

    display = reconciled[0]
    assert display["text"] == "A\nB\nC"
    assert display["observation_ids"] == ["page-1", "page-2", "page-3"]
    assert display["pages"] == [1, 2, 3]
    assert [
        event["boundary_evidence"]["physical_page_transition"]
        for event in display["attrs"]["merge_events"]
    ] == [[1, 2], [2, 3]]
    assert [
        event["interrupting_observation_ids"]
        for event in display["attrs"]["merge_events"]
    ] == [["note-1"], ["note-2"]]
    assert [record["observation_ids"] for record in reconciled[1:]] == [
        ["note-1"],
        ["note-2"],
    ]


def test_orchestrator_reconciles_footnotes_before_displays() -> None:
    records = [
        _record("display-left", "A", page=1, bbox=[200.0, 700.0, 500.0, 740.0]),
        _record(
            "note-left",
            "1 Note（接下页）",
            page=1,
            bbox=[100.0, 800.0, 900.0, 980.0],
            unit_type="footnote",
            layout_form=None,
        ),
        _record("display-right", "B", page=2, bbox=[210.0, 100.0, 420.0, 160.0]),
        _record(
            "note-right",
            "（接上页）continued note",
            page=2,
            bbox=[100.0, 850.0, 900.0, 920.0],
            unit_type="footnote",
            layout_form=None,
        ),
    ]

    reconciled = reconcile_text_flow_records(
        records,
        _pages(1, 2),
        _page_layout(1, 2),
    )

    display = _record_with_observation_id(reconciled, "display-left")
    footnote = _record_with_observation_id(reconciled, "note-left")
    assert display["observation_ids"] == ["display-left", "display-right"]
    assert display["attrs"]["merge_events"][0][
        "interrupting_observation_ids"
    ] == ["note-left", "note-right"]
    assert footnote["observation_ids"] == ["note-left", "note-right"]


def test_legacy_orchestrator_does_not_run_display_reconciliation() -> None:
    records, pages, page_layout = _cross_page_pair()

    legacy = reconcile_text_records(records, pages, page_layout)
    text_flow = reconcile_text_flow_records(records, pages, page_layout)

    assert legacy == records
    assert len(legacy) == 2
    assert len(text_flow) == 1
    assert text_flow[0]["observation_ids"] == ["left", "right"]


@pytest.mark.parametrize(
    ("left_form", "right_form"),
    [
        ("short_line_group", "set_off_text"),
        ("", ""),
        (None, None),
        ("attribution", "attribution"),
    ],
)
def test_display_requires_compatible_non_boundary_layout_forms(
    left_form: str | None,
    right_form: str | None,
) -> None:
    records, pages, page_layout = _cross_page_pair()
    for record, layout_form in zip(records, (left_form, right_form), strict=True):
        if layout_form is None:
            record["attrs"].pop("layout_form")
        else:
            record["attrs"]["layout_form"] = layout_form

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_explicit_empty_layout_form_cannot_fall_back_to_fragments() -> None:
    records, pages, page_layout = _cross_page_pair()
    for record in records:
        record["attrs"]["layout_form"] = ""
        record["attrs"]["layout_fragments"] = [
            {
                "classified_type": "display_block",
                "status": "resolved",
                "layout_form": "short_line_group",
                "signals": [],
            }
        ]

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_direct_layout_form_conflict_with_resolved_fragments_rejects_merge() -> None:
    records, pages, page_layout = _cross_page_pair()
    records[0]["attrs"]["layout_form"] = "set_off_text"
    records[0]["attrs"]["layout_fragments"] = [
        {
            "classified_type": "display_block",
            "status": "resolved",
            "layout_form": "short_line_group",
            "signals": [],
        }
    ]

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_explicit_endpoint_alignment_conflict_rejects_display_merge() -> None:
    records, pages, page_layout = _cross_page_pair()
    records[0]["attrs"]["alignment"] = "left"
    records[1]["attrs"]["alignment"] = "right"

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_explicit_alignment_checks_only_its_matching_lane_axis() -> None:
    records, pages, page_layout = _cross_page_pair()
    records[0]["attrs"]["alignment"] = "left"
    records[1]["attrs"]["alignment"] = "left"
    records[1]["bbox"] = [310.0, 100.0, 500.0, 160.0]
    records[1]["spans"][0]["bbox"] = deepcopy(records[1]["bbox"])

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_direct_alignment_conflict_with_resolved_fragment_rejects_merge() -> None:
    records, pages, page_layout = _cross_page_pair()
    records[0]["attrs"]["alignment"] = "left"
    records[0]["attrs"]["layout_fragments"] = [
        {
            "classified_type": "display_block",
            "status": "resolved",
            "layout_form": "short_line_group",
            "alignment": "right",
            "signals": [],
        }
    ]

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


@pytest.mark.parametrize("source", ["direct", "fragment"])
def test_malformed_alignment_metadata_rejects_display_merge(source: str) -> None:
    records, pages, page_layout = _cross_page_pair()
    if source == "direct":
        records[0]["attrs"]["alignment"] = {}
    else:
        records[0]["attrs"].pop("alignment")
        records[0]["attrs"]["layout_fragments"] = [
            {
                "classified_type": "display_block",
                "status": "resolved",
                "layout_form": "short_line_group",
                "alignment": {},
                "signals": [],
            }
        ]

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_attribution_completion_flag_rejects_display_merge() -> None:
    records, pages, page_layout = _cross_page_pair()
    records[0]["attrs"]["has_attribution_line"] = True

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_malformed_layout_fragment_signals_reject_display_merge() -> None:
    records, pages, page_layout = _cross_page_pair()
    records[0]["attrs"].pop("layout_form")
    records[0]["attrs"]["layout_fragments"] = [
        {
            "classified_type": "display_block",
            "status": "resolved",
            "layout_form": "short_line_group",
            "signals": [{}],
        }
    ]

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_incompatible_display_lanes_reject_merge() -> None:
    records, pages, page_layout = _cross_page_pair()
    records[1]["bbox"] = [600.0, 100.0, 850.0, 160.0]
    records[1]["spans"][0]["bbox"] = deepcopy(records[1]["bbox"])

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


@pytest.mark.parametrize(
    "broken_evidence",
    ["left_page_bottom", "right_page_top", "page_layout", "source_pages"],
)
def test_display_requires_complete_physical_boundary_evidence(
    broken_evidence: str,
) -> None:
    records, pages, page_layout = _cross_page_pair()
    if broken_evidence == "left_page_bottom":
        records[0]["bbox"] = [200.0, 500.0, 500.0, 600.0]
        records[0]["spans"][0]["bbox"] = deepcopy(records[0]["bbox"])
    elif broken_evidence == "right_page_top":
        records[1]["bbox"] = [210.0, 300.0, 420.0, 360.0]
        records[1]["spans"][0]["bbox"] = deepcopy(records[1]["bbox"])
    elif broken_evidence == "page_layout":
        page_layout["pages"][1].pop("body_lane")
    else:
        pages = _pages(1, 3)

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_non_finite_page_height_rejects_display_merge() -> None:
    records, pages, page_layout = _cross_page_pair()
    page_layout["pages"][0]["page_size"]["height"] = math.nan

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_display_does_not_jump_over_nonfootnote_body_resumption() -> None:
    records, pages, page_layout = _cross_page_pair()
    records.insert(
        1,
        _record(
            "body",
            "Body resumes here",
            page=1,
            bbox=[100.0, 930.0, 900.0, 970.0],
            unit_type="paragraph",
            layout_form=None,
        ),
    )

    assert reconcile_cross_page_displays(records, pages, page_layout) == records


def test_unproven_multi_page_right_display_is_not_absorbed() -> None:
    records, _, _ = _cross_page_pair()
    records[1]["pages"] = [2, 3]
    records[1]["spans"].append(
        {"page": 3, "bbox": [210.0, 100.0, 420.0, 160.0]}
    )

    reconciled = reconcile_cross_page_displays(
        records,
        _pages(1, 2, 3),
        _page_layout(1, 2, 3),
    )

    assert reconciled == records


@pytest.mark.parametrize(
    "value",
    [math.nan, math.inf, -math.inf, True, False, "100"],
    ids=["nan", "inf", "negative-inf", "true", "false", "string"],
)
def test_malformed_display_geometry_rejects_merge(value: Any) -> None:
    records, pages, page_layout = _cross_page_pair()
    records[1]["bbox"][0] = value
    records[1]["spans"][0]["bbox"][0] = value

    assert reconcile_cross_page_displays(records, pages, page_layout) == records
