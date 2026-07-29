from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from inkline.canonical.text_flow.reconcile import reconcile_cross_page_footnotes
from inkline.canonical.text_flow.reconcile.common import merge_records


def _record(
    observation_id: str,
    text: str,
    *,
    page: int,
    bbox: list[float],
    unit_type: str = "list_item",
    role_hint: str = "reference_text",
) -> dict[str, Any]:
    return {
        "unit_type": unit_type,
        "text": text,
        "page": page,
        "pages": [page],
        "bbox": bbox,
        "spans": [{"page": page, "bbox": deepcopy(bbox)}],
        "observation_ids": [observation_id],
        "role_hints": [role_hint],
        "attrs": {
            "inline_runs": [{"type": "text", "text": text}],
            "note_refs": [{"observation_id": observation_id}],
            "source_tags": [observation_id],
        },
        "parser_payloads": [{"source": observation_id}],
    }


def _page_layout(*pages: int) -> dict[str, Any]:
    return {
        "pages": [
            {
                "page": page,
                "page_size": {"width": 1000.0, "height": 1000.0},
                "body_lane": {
                    "body_left": 100.0,
                    "body_right": 900.0,
                    "page_height": 1000.0,
                },
            }
            for page in pages
        ]
    }


def _silk_road_footnote_records() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = [
        _record(
            "obs001399",
            "4 引文中的接下页说明必须保留，原注在此（接下页）",
            page=162,
            bbox=[89.563, 887.667, 860.367, 922.562],
        ),
        _record(
            "obs001402",
            "下一页正文不属于脚注。",
            page=163,
            bbox=[120.0, 120.0, 891.0, 169.0],
            unit_type="paragraph",
            role_hint="body_text",
        ),
        _record(
            "obs001405",
            "（接上页）方便起见引用英文版；引文中的接上页说明也必须保留。",
            page=163,
            bbox=[138.928, 500.953, 888.575, 568.637],
        ),
        _record(
            "obs001406",
            "Nicholas Sims-Williams 把译文发布到了网上。",
            page=163,
            bbox=[138.928, 572.927, 887.870, 605.815],
        ),
        _record(
            "obs001407",
            "每封信札的最新翻译如下：",
            page=163,
            bbox=[174.894, 607.722, 385.755, 623.928],
        ),
        _record(
            "obs001408",
            "信札 1 号的书目信息。",
            page=163,
            bbox=[138.928, 626.787, 875.882, 659.676],
        ),
        _record(
            "obs001409",
            "信札 2 号的书目信息。",
            page=163,
            bbox=[136.812, 662.536, 887.870, 767.874],
        ),
        _record(
            "obs001410",
            "信札 3 号的书目信息。",
            page=163,
            bbox=[136.812, 769.781, 886.460, 802.669],
        ),
        _record(
            "obs001411",
            "信札 5 号的书目信息。",
            page=163,
            bbox=[136.812, 805.529, 886.460, 839.847],
        ),
        _record(
            "obs001412",
            '1 Nicholas Sims-Williams, "Sogdian Ancient Letter II", 261.',
            page=163,
            bbox=[116.361, 841.754, 602.962, 857.960],
        ),
    ]
    return records, _page_layout(162, 163)


def _next_independent_marker_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    return next(record for record in records if "obs001412" in record["observation_ids"])


def _unmarked_cross_page_reference_fixture() -> tuple[
    list[dict[str, Any]], dict[str, Any]
]:
    return (
        [
            _record(
                "left",
                "4 这条引用在页末没有结构续页标记。",
                page=10,
                bbox=[100.0, 880.0, 900.0, 920.0],
            ),
            _record(
                "right",
                "下一页顶部看起来像引用，但不能据此猜测。",
                page=11,
                bbox=[100.0, 100.0, 900.0, 140.0],
            ),
        ],
        _page_layout(10, 11),
    )


def test_explicit_cross_page_footnote_absorbs_only_same_lane_tail() -> None:
    records, page_layout = _silk_road_footnote_records()
    original = deepcopy(records)

    reconciled = reconcile_cross_page_footnotes(records, page_layout)

    footnote = next(
        record for record in reconciled if "obs001399" in record["observation_ids"]
    )
    assert records == original
    assert "obs001405" in footnote["observation_ids"]
    assert "（接下页）" not in footnote["text"]
    assert "（接上页）" not in footnote["text"]
    assert "引文中的接下页说明必须保留" in footnote["text"]
    assert "引文中的接上页说明也必须保留" in footnote["text"]
    assert footnote["pages"] == [162, 163]
    assert footnote["unit_type"] == "footnote"
    assert footnote["attrs"]["merge_events"][0]["reason"] == (
        "explicit_cross_page_footnote_continuation"
    )
    assert footnote["attrs"]["merge_events"][0][
        "interrupting_observation_ids"
    ] == ["obs001402"]
    assert all(
        observation_id in footnote["observation_ids"]
        for observation_id in [
            "obs001406",
            "obs001407",
            "obs001408",
            "obs001409",
            "obs001410",
            "obs001411",
        ]
    )
    assert len(footnote["attrs"]["merge_events"]) == 7
    assert _next_independent_marker_record(reconciled)["observation_ids"] == [
        "obs001412"
    ]
    inline_text = "".join(
        str(run.get("text") or "") for run in footnote["attrs"]["inline_runs"]
    )
    assert "（接下页）" not in inline_text
    assert "（接上页）" not in inline_text


def test_tail_absorption_stops_at_an_independent_reference_marker() -> None:
    records, page_layout = _silk_road_footnote_records()
    after_marker = _record(
        "after-marker",
        "The record after an independent note must also stay separate.",
        page=163,
        bbox=[138.0, 860.0, 888.0, 890.0],
    )
    records.append(after_marker)

    reconciled = reconcile_cross_page_footnotes(records, page_layout)

    footnote = next(
        record for record in reconciled if "obs001399" in record["observation_ids"]
    )
    assert "obs001412" not in footnote["observation_ids"]
    assert "after-marker" not in footnote["observation_ids"]
    assert any(
        record["observation_ids"] == ["after-marker"] for record in reconciled
    )


@pytest.mark.parametrize(
    ("stop_type", "stop_role", "stop_page", "stop_bbox"),
    [
        ("paragraph", "body_text", 2, [100.0, 300.0, 900.0, 340.0]),
        ("list_item", "reference_text", 2, [650.0, 300.0, 850.0, 340.0]),
        ("list_item", "reference_text", 3, [100.0, 100.0, 900.0, 140.0]),
        ("heading", "title_text", 2, [100.0, 300.0, 900.0, 340.0]),
        ("table", "table", 2, [100.0, 300.0, 900.0, 500.0]),
        ("visual", "figure", 2, [100.0, 300.0, 900.0, 500.0]),
    ],
    ids=["non-reference", "lane-break", "page-change", "heading", "table", "visual"],
)
def test_tail_absorption_stops_at_structural_or_layout_boundary(
    stop_type: str,
    stop_role: str,
    stop_page: int,
    stop_bbox: list[float],
) -> None:
    records = [
        _record(
            "left",
            "4 Left（接下页）",
            page=1,
            bbox=[100.0, 880.0, 900.0, 920.0],
        ),
        _record(
            "right",
            "（接上页）Right",
            page=2,
            bbox=[100.0, 100.0, 900.0, 140.0],
        ),
        _record(
            "tail",
            "Continuation tail.",
            page=2,
            bbox=[100.0, 150.0, 900.0, 190.0],
        ),
        _record(
            "stop",
            "Boundary.",
            page=stop_page,
            bbox=stop_bbox,
            unit_type=stop_type,
            role_hint=stop_role,
        ),
        _record(
            "after-stop",
            "Must remain separate.",
            page=stop_page,
            bbox=[100.0, 510.0, 900.0, 550.0],
        ),
    ]

    reconciled = reconcile_cross_page_footnotes(records, _page_layout(1, 2, 3))

    footnote = next(record for record in reconciled if "left" in record["observation_ids"])
    assert "tail" in footnote["observation_ids"]
    assert "stop" not in footnote["observation_ids"]
    assert "after-stop" not in footnote["observation_ids"]


@pytest.mark.parametrize("broken_evidence", ["page", "role", "lane"])
def test_explicit_pair_requires_adjacent_pages_reference_role_and_lane(
    broken_evidence: str,
) -> None:
    records = [
        _record(
            "left",
            "4 Left（接下页）",
            page=10,
            bbox=[100.0, 880.0, 900.0, 920.0],
        ),
        _record(
            "right",
            "（接上页）Right",
            page=11,
            bbox=[100.0, 100.0, 900.0, 140.0],
        ),
    ]
    if broken_evidence == "page":
        records[1]["page"] = 12
        records[1]["pages"] = [12]
        records[1]["spans"][0]["page"] = 12
    elif broken_evidence == "role":
        records[1]["unit_type"] = "paragraph"
        records[1]["role_hints"] = ["body_text"]
    else:
        records[1]["bbox"] = [5.0, 100.0, 70.0, 140.0]

    reconciled = reconcile_cross_page_footnotes(records, _page_layout(10, 11, 12))

    assert [record["observation_ids"] for record in reconciled] == [
        ["left"],
        ["right"],
    ]
    assert [record["unit_type"] for record in reconciled] == [
        "list_item",
        "list_item" if broken_evidence != "role" else "paragraph",
    ]


@pytest.mark.parametrize(
    "marker",
    ["¹ Source", "[21] Source", "［2］ Source", "㉑ Source", "❶ Source"],
)
def test_tail_absorption_stops_at_conservative_independent_marker_vocabulary(
    marker: str,
) -> None:
    records = [
        _record(
            "left",
            "4 Left（接下页）",
            page=1,
            bbox=[100.0, 880.0, 900.0, 920.0],
        ),
        _record(
            "right",
            "（接上页）Right",
            page=2,
            bbox=[100.0, 100.0, 900.0, 140.0],
        ),
        _record(
            "marker",
            marker,
            page=2,
            bbox=[100.0, 150.0, 900.0, 190.0],
        ),
        _record(
            "after-marker",
            "Must remain separate.",
            page=2,
            bbox=[100.0, 200.0, 900.0, 240.0],
        ),
    ]

    reconciled = reconcile_cross_page_footnotes(records, _page_layout(1, 2))

    footnote = next(record for record in reconciled if "left" in record["observation_ids"])
    assert "marker" not in footnote["observation_ids"]
    assert "after-marker" not in footnote["observation_ids"]


@pytest.mark.parametrize(
    ("left_text", "right_text"),
    [
        ("4 Left（接下页）", "(接上页]Right"),
        ("4 Left（接下页）", "接上页码不是结构标记"),
        ("4 Left(接下页]", "（接上页）Right"),
    ],
)
def test_continuation_pair_rejects_unbalanced_or_non_token_markers(
    left_text: str,
    right_text: str,
) -> None:
    records = [
        _record(
            "left",
            left_text,
            page=1,
            bbox=[100.0, 880.0, 900.0, 920.0],
        ),
        _record(
            "right",
            right_text,
            page=2,
            bbox=[100.0, 100.0, 900.0, 140.0],
        ),
    ]

    reconciled = reconcile_cross_page_footnotes(records, _page_layout(1, 2))

    assert [record["observation_ids"] for record in reconciled] == [
        ["left"],
        ["right"],
    ]
    assert [record["text"] for record in reconciled] == [left_text, right_text]


def test_unmarked_cross_page_reference_is_not_guessed() -> None:
    records, page_layout = _unmarked_cross_page_reference_fixture()

    reconciled = reconcile_cross_page_footnotes(records, page_layout)

    assert len(reconciled) == len(records)
    assert [record["unit_type"] for record in reconciled] == [
        "list_item",
        "list_item",
    ]
    assert [record["observation_ids"] for record in reconciled] == [
        ["left"],
        ["right"],
    ]


def test_merge_records_preserves_source_collections_and_boundary_audit() -> None:
    left = _record(
        "left",
        "Left",
        page=1,
        bbox=[100.0, 880.0, 900.0, 920.0],
    )
    right = _record(
        "right",
        "Right",
        page=2,
        bbox=[100.0, 100.0, 900.0, 140.0],
    )
    left["attrs"]["left_only"] = {"left": True}
    right["attrs"]["right_only"] = {"right": True}
    left["attrs"]["merge_events"] = [{"reason": "preexisting"}]
    interruption = _record(
        "interrupting",
        "Body",
        page=2,
        bbox=[100.0, 200.0, 900.0, 240.0],
        unit_type="paragraph",
        role_hint="body_text",
    )
    original_right = deepcopy(right)

    merge_records(
        left,
        right,
        reason="explicit_cross_page_footnote_continuation",
        joiner="\n",
        interruptions=[interruption],
        boundary_evidence={"left_marker": "接下页", "right_marker": "接上页"},
    )

    assert right == original_right
    assert left["text"] == "Left\nRight"
    assert left["pages"] == [1, 2]
    assert left["spans"] == [
        {"page": 1, "bbox": [100.0, 880.0, 900.0, 920.0]},
        {"page": 2, "bbox": [100.0, 100.0, 900.0, 140.0]},
    ]
    assert left["observation_ids"] == ["left", "right"]
    assert left["parser_payloads"] == [{"source": "left"}, {"source": "right"}]
    assert left["role_hints"] == ["reference_text"]
    assert left["attrs"]["source_tags"] == ["left", "right"]
    assert left["attrs"]["inline_runs"] == [
        {"type": "text", "text": "Left"},
        {"type": "text", "text": "Right"},
    ]
    assert left["attrs"]["note_refs"] == [
        {"observation_id": "left"},
        {"observation_id": "right"},
    ]
    assert left["attrs"]["left_only"] == {"left": True}
    assert left["attrs"]["right_only"] == {"right": True}
    assert left["attrs"]["merge_events"] == [
        {"reason": "preexisting"},
        {
            "reason": "explicit_cross_page_footnote_continuation",
            "left_page": 1,
            "right_page": 2,
            "left_observation_ids": ["left"],
            "right_observation_ids": ["right"],
            "interrupting_observation_ids": ["interrupting"],
            "boundary_evidence": {
                "left_marker": "接下页",
                "right_marker": "接上页",
            },
        },
    ]


def test_merge_records_does_not_add_missing_attrs_to_right_source() -> None:
    left = _record(
        "left",
        "Left",
        page=1,
        bbox=[100.0, 880.0, 900.0, 920.0],
    )
    right = _record(
        "right",
        "Right",
        page=2,
        bbox=[100.0, 100.0, 900.0, 140.0],
    )
    del right["attrs"]
    original_right = deepcopy(right)

    merge_records(
        left,
        right,
        reason="test_boundary",
        joiner="\n",
        interruptions=[],
    )

    assert right == original_right
