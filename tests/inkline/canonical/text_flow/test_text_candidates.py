from __future__ import annotations

import json
from pathlib import Path

from inkline.canonical import make_observation, make_observed_document, make_observed_page
from inkline.canonical.text_flow.candidates import build_text_candidates

ROOT = Path(__file__).resolve().parents[4]
SILK_ROAD_OBSERVED = ROOT / "data/outputs/golden/observed/丝绸之路新史_observed.json"
MIDDLE_KINGDOM_OBSERVED = ROOT / "data/outputs/golden/observed/中日交流两千年_observed.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _middle_kingdom_chapter_fixture() -> tuple[dict, dict[str, tuple[str, ...]]]:
    anchor_group = ("obs000103", "obs000104")
    return _load(MIDDLE_KINGDOM_OBSERVED), dict.fromkeys(anchor_group, anchor_group)


def test_candidates_are_atomic_and_have_no_text_unit_identity() -> None:
    observed = _load(SILK_ROAD_OBSERVED)
    candidates, _ignored = build_text_candidates(
        observed,
        included_pages={292},
        anchor_groups_by_observation_id={},
    )
    selected = [
        candidate
        for candidate in candidates
        if candidate["observation_id"] in {"obs002504", "obs002505", "obs002506"}
    ]
    assert [candidate["observation_id"] for candidate in selected] == [
        "obs002504",
        "obs002505",
        "obs002506",
    ]
    assert [candidate["text"] for candidate in selected] == [
        "有些甚至提到了性：",
        "他爱许多女人。",
        "他做爱。",
    ]
    assert all("unit_id" not in candidate for candidate in candidates)
    assert all("observation_ids" not in candidate for candidate in candidates)


def test_direct_anchor_membership_is_protected_without_aggregation() -> None:
    observed, anchor_map = _middle_kingdom_chapter_fixture()
    candidates, _ignored = build_text_candidates(
        observed,
        included_pages={11},
        anchor_groups_by_observation_id=anchor_map,
    )
    protected = [candidate for candidate in candidates if candidate["protected_anchor_group"]]
    assert [candidate["observation_id"] for candidate in protected] == [
        "obs000103",
        "obs000104",
    ]
    assert all(candidate["candidate_type"] == "heading" for candidate in protected)


def test_direct_anchor_precedes_competing_title_in_same_reading_order_slot() -> None:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "fixture",
            "parser_mode": "fixture",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "anchor-a",
                "text_region",
                text="Chapter",
                page=1,
                bbox=[400, 200, 600, 240],
                role_hint="title_text",
                attrs={"reading_order": 0},
            ),
            make_observation(
                "competing-title",
                "text_region",
                text="Competing title evidence",
                page=1,
                bbox=[100, 150, 300, 180],
                role_hint="title_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "anchor-b",
                "text_region",
                text="Accepted title",
                page=1,
                bbox=[300, 250, 700, 290],
                role_hint="title_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "body",
                "text_region",
                text="Body remains retained.",
                page=1,
                bbox=[100, 350, 900, 420],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ],
    )
    group = ("anchor-a", "anchor-b")

    candidates, ignored = build_text_candidates(
        document,
        included_pages={1},
        anchor_groups_by_observation_id=dict.fromkeys(group, group),
    )

    assert [candidate["observation_id"] for candidate in candidates] == [
        "anchor-a",
        "anchor-b",
        "competing-title",
        "body",
    ]
    assert ignored == {}
