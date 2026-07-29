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
    reconcile_cross_page_footnotes,
    reconcile_cross_page_paragraphs,
    reconcile_text_records,
)

ROOT = Path(__file__).resolve().parents[4]
SILK_ROAD_OBSERVED = ROOT / "data/outputs/golden/observed/丝绸之路新史_observed.json"


def _record_with_observation_id(
    records: list[dict[str, Any]], observation_id: str
) -> dict[str, Any]:
    return next(
        record for record in records if observation_id in record["observation_ids"]
    )


def _record(
    observation_id: str,
    text: str,
    *,
    page: int,
    bbox: list[float],
    unit_type: str = "paragraph",
    line_count: int = 2,
    first_line_indent: float = 0.0,
) -> dict[str, Any]:
    return {
        "unit_type": unit_type,
        "text": text,
        "page": page,
        "pages": [page],
        "bbox": deepcopy(bbox),
        "spans": [{"page": page, "bbox": deepcopy(bbox)}],
        "observation_ids": [observation_id],
        "role_hints": ["footnote_text" if unit_type == "footnote" else "body_text"],
        "attrs": {
            "inline_runs": [{"type": "text", "text": text}],
            "note_refs": [{"marker": observation_id}],
            "source_tags": [observation_id],
            "text_line_metrics_by_observation": {
                observation_id: {
                    "line_count": line_count,
                    "first_line_indent": first_line_indent,
                    "char_width": 20.0,
                }
            },
        },
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
    left_type: str = "paragraph", right_type: str = "paragraph"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return (
        [
            _record(
                "left",
                "Left fragment",
                page=1,
                bbox=[100.0, 850.0, 900.0, 920.0],
                unit_type=left_type,
            ),
            _record(
                "right",
                "right fragment",
                page=2,
                bbox=[100.0, 100.0, 900.0, 160.0],
                unit_type=right_type,
            ),
        ],
        _pages(1, 2),
        _page_layout(1, 2),
    )


def _silk_road_page_81_82_records() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    observed = json.loads(SILK_ROAD_OBSERVED.read_text(encoding="utf-8"))
    page_layout = build_page_layout_analysis(observed)
    candidates, _ignored = build_text_candidates(
        observed,
        included_pages={81, 82},
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


def test_paragraph_continues_across_two_page_footnotes() -> None:
    records, pages, page_layout = _silk_road_page_81_82_records()
    original = deepcopy(records)

    reconciled = reconcile_cross_page_paragraphs(records, pages, page_layout)

    paragraph = _record_with_observation_id(reconciled, "obs000747")
    assert records == original
    assert paragraph["observation_ids"] == ["obs000747", "obs000752"]
    assert paragraph["text"].endswith(
        "大多数人改走塔克拉玛干北道，而这正是我们下一章的主题。"
    )
    assert paragraph["pages"] == [81, 82]
    assert _record_with_observation_id(reconciled, "obs000748")["unit_type"] == (
        "footnote"
    )
    assert _record_with_observation_id(reconciled, "obs000749")["unit_type"] == (
        "footnote"
    )
    assert paragraph["attrs"]["note_refs"][-1]["marker"] == "1"
    event = paragraph["attrs"]["merge_events"][0]
    assert event["reason"] == "cross_page_paragraph_continuation"
    assert event["interrupting_observation_ids"] == ["obs000748", "obs000749"]


def test_reconciliation_pipeline_runs_footnotes_before_paragraphs() -> None:
    records = [
        _record("paragraph-left", "A", page=1, bbox=[100.0, 700.0, 900.0, 740.0]),
        _record(
            "note-left",
            "1 Note（接下页）",
            page=1,
            bbox=[100.0, 800.0, 900.0, 980.0],
            unit_type="footnote",
        ),
        _record(
            "paragraph-right",
            "B",
            page=2,
            bbox=[100.0, 100.0, 900.0, 160.0],
        ),
        _record(
            "note-right",
            "（接上页）continued note",
            page=2,
            bbox=[100.0, 850.0, 900.0, 920.0],
            unit_type="footnote",
        ),
    ]

    reconciled = reconcile_text_records(
        records,
        _pages(1, 2),
        _page_layout(1, 2),
    )

    paragraph = _record_with_observation_id(reconciled, "paragraph-left")
    footnote = _record_with_observation_id(reconciled, "note-left")
    assert paragraph["observation_ids"] == ["paragraph-left", "paragraph-right"]
    assert paragraph["attrs"]["merge_events"][0][
        "interrupting_observation_ids"
    ] == ["note-left", "note-right"]
    assert footnote["observation_ids"] == ["note-left", "note-right"]


def test_three_page_paragraph_requires_two_proven_transitions() -> None:
    records = [
        _record("page-1", "A", page=1, bbox=[100.0, 850.0, 900.0, 920.0]),
        _record(
            "note-1",
            "Page one note",
            page=1,
            bbox=[100.0, 940.0, 900.0, 980.0],
            unit_type="footnote",
        ),
        _record("page-2", "B", page=2, bbox=[100.0, 100.0, 900.0, 920.0]),
        _record(
            "note-2",
            "Page two note",
            page=2,
            bbox=[100.0, 940.0, 900.0, 980.0],
            unit_type="footnote",
        ),
        _record("page-3", "C", page=3, bbox=[100.0, 100.0, 900.0, 160.0]),
    ]

    reconciled = reconcile_cross_page_paragraphs(
        records,
        _pages(1, 2, 3),
        _page_layout(1, 2, 3),
    )

    paragraph = reconciled[0]
    assert paragraph["observation_ids"] == ["page-1", "page-2", "page-3"]
    assert paragraph["pages"] == [1, 2, 3]
    assert [
        (event["left_page"], event["right_page"])
        for event in paragraph["attrs"]["merge_events"]
    ] == [(1, 2), (2, 3)]
    assert [
        event["interrupting_observation_ids"]
        for event in paragraph["attrs"]["merge_events"]
    ] == [["note-1"], ["note-2"]]


def test_unproven_multi_page_right_paragraph_is_not_absorbed() -> None:
    records, _, _ = _cross_page_pair()
    records[1]["pages"] = [2, 3]
    records[1]["spans"].append(
        {"page": 3, "bbox": [100.0, 100.0, 900.0, 160.0]}
    )

    reconciled = reconcile_cross_page_paragraphs(
        records,
        _pages(1, 2, 3),
        _page_layout(1, 2, 3),
    )

    assert reconciled == records
    assert "merge_events" not in reconciled[1]["attrs"]


@pytest.mark.parametrize(
    "right_pages",
    [
        [2, 3, 2],
        [],
        None,
        "2",
        [2, True, 2],
        [2, False, 2],
        [2, "2", 2],
        [2, 2.0, 2],
    ],
    ids=[
        "hidden-extra-page",
        "empty",
        "none",
        "not-a-list",
        "true-page",
        "false-page",
        "string-page",
        "float-page",
    ],
)
def test_noncanonical_right_pages_reject_paragraph_merge(right_pages: Any) -> None:
    records, pages, page_layout = _cross_page_pair()
    records[1]["pages"] = right_pages

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


@pytest.mark.parametrize("right_type", ["display_block", "heading", "list_item"])
def test_paragraph_does_not_cross_different_type(right_type: str) -> None:
    records, pages, page_layout = _cross_page_pair("paragraph", right_type)

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


def test_nonparagraph_left_endpoint_is_not_promoted_or_merged() -> None:
    records, pages, page_layout = _cross_page_pair("display_block", "paragraph")

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


def test_paragraph_does_not_jump_over_excluded_visual_page() -> None:
    records = [
        _record("page-1", "A", page=1, bbox=[100.0, 850.0, 900.0, 920.0]),
        _record("page-3", "B", page=3, bbox=[100.0, 100.0, 900.0, 160.0]),
    ]

    assert (
        reconcile_cross_page_paragraphs(
            records,
            _pages(1, 2, 3),
            _page_layout(1, 2, 3),
        )
        == records
    )


@pytest.mark.parametrize(
    "broken_evidence",
    ["left_page_bottom", "right_page_top", "body_lane", "right_first_line_indent"],
)
def test_paragraph_requires_complete_boundary_geometry(
    broken_evidence: str,
) -> None:
    records, pages, page_layout = _cross_page_pair()
    if broken_evidence == "left_page_bottom":
        records[0]["bbox"] = [100.0, 500.0, 900.0, 600.0]
        records[0]["spans"][0]["bbox"] = deepcopy(records[0]["bbox"])
    elif broken_evidence == "right_page_top":
        records[1]["bbox"] = [100.0, 300.0, 900.0, 360.0]
        records[1]["spans"][0]["bbox"] = deepcopy(records[1]["bbox"])
    elif broken_evidence == "body_lane":
        records[1]["bbox"] = [500.0, 100.0, 900.0, 160.0]
        records[1]["spans"][0]["bbox"] = deepcopy(records[1]["bbox"])
    else:
        metrics = records[1]["attrs"]["text_line_metrics_by_observation"]["right"]
        metrics["first_line_indent"] = 60.0

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("first_line_indent", math.nan),
        ("first_line_indent", math.inf),
        ("first_line_indent", -math.inf),
        ("char_width", math.nan),
        ("char_width", math.inf),
        ("char_width", -math.inf),
    ],
)
def test_non_finite_first_line_metrics_reject_paragraph_merge(
    field: str,
    value: float,
) -> None:
    records, pages, page_layout = _cross_page_pair()
    metrics = records[1]["attrs"]["text_line_metrics_by_observation"]["right"]
    metrics[field] = value

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("first_line_indent", True),
        ("first_line_indent", False),
        ("first_line_indent", "20"),
        ("char_width", True),
        ("char_width", False),
        ("char_width", "20"),
    ],
)
def test_coerced_first_line_metrics_reject_paragraph_merge(
    field: str,
    value: bool | str,
) -> None:
    records, pages, page_layout = _cross_page_pair()
    metrics = records[1]["attrs"]["text_line_metrics_by_observation"]["right"]
    metrics[field] = value

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


@pytest.mark.parametrize("coordinate", range(4), ids=["x1", "y1", "x2", "y2"])
@pytest.mark.parametrize("value", [math.nan, math.inf], ids=["nan", "inf"])
def test_non_finite_bbox_coordinate_rejects_paragraph_merge(
    coordinate: int,
    value: float,
) -> None:
    records, pages, page_layout = _cross_page_pair()
    records[1]["bbox"][coordinate] = value
    records[1]["spans"][0]["bbox"][coordinate] = value

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


@pytest.mark.parametrize("value", [True, False, "20"], ids=["true", "false", "string"])
def test_coerced_bbox_coordinate_rejects_paragraph_merge(value: bool | str) -> None:
    records, pages, page_layout = _cross_page_pair()
    records[1]["bbox"][1] = value
    records[1]["spans"][0]["bbox"][1] = value

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


@pytest.mark.parametrize(
    "spans",
    [
        [{"page": 2, "bbox": [100.0, 160.0, 900.0, 160.0]}],
        [
            {"page": 2, "bbox": [100.0, 100.0, 900.0, 160.0]},
            {"page": 2, "bbox": [100.0, 160.0, 900.0, 160.0]},
        ],
    ],
    ids=["only-invalid-target-span", "mixed-valid-and-invalid-target-spans"],
)
def test_invalid_target_page_span_cannot_fall_back_to_record_bbox(
    spans: list[dict[str, Any]],
) -> None:
    records, pages, page_layout = _cross_page_pair()
    records[1]["spans"] = deepcopy(spans)

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


@pytest.mark.parametrize(
    "bbox",
    [
        [900.0, 100.0, 900.0, 160.0],
        [901.0, 100.0, 900.0, 160.0],
        [100.0, 160.0, 900.0, 160.0],
        [100.0, 161.0, 900.0, 160.0],
    ],
    ids=["zero-width", "negative-width", "zero-height", "negative-height"],
)
def test_unordered_bbox_extents_reject_paragraph_merge(bbox: list[float]) -> None:
    records, pages, page_layout = _cross_page_pair()
    records[1]["bbox"] = deepcopy(bbox)
    records[1]["spans"][0]["bbox"] = deepcopy(bbox)

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records


def test_nonfootnote_interruption_is_a_hard_boundary() -> None:
    records, pages, page_layout = _cross_page_pair()
    records.insert(
        1,
        _record(
            "heading",
            "A boundary",
            page=1,
            bbox=[100.0, 940.0, 900.0, 970.0],
            unit_type="heading",
        ),
    )

    assert reconcile_cross_page_paragraphs(records, pages, page_layout) == records
