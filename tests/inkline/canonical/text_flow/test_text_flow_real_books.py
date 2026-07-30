from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from inkline.canonical import build_page_layout_analysis, build_text_flow

ROOT = Path(__file__).resolve().parents[4]
BOOK = "丝绸之路新史"


def test_silk_road_text_flow_reconciles_accepted_layout_and_cross_page_cases() -> None:
    flow = _build_silk_road_text_flow()
    observation_ids = [
        observation_id for unit in flow["text_units"] for observation_id in unit["observation_ids"]
    ]
    by_observation = {
        observation_id: unit
        for unit in flow["text_units"]
        for observation_id in unit["observation_ids"]
    }

    assert by_observation["obs001363"]["unit_type"] == "display_block"
    assert by_observation["obs001364"]["unit_type"] == "paragraph"
    assert by_observation["obs002159"] is by_observation["obs002163"]
    assert by_observation["obs002159"]["unit_type"] == "display_block"
    assert by_observation["obs002497"] is by_observation["obs002503"]
    assert by_observation["obs002504"]["unit_type"] == "paragraph"
    assert by_observation["obs002505"]["unit_type"] == "display_block"
    assert by_observation["obs000111"]["unit_type"] == "display_block"
    assert by_observation["obs000747"] is by_observation["obs000752"]
    assert by_observation["obs000748"] is not by_observation["obs000747"]
    assert by_observation["obs000749"] is not by_observation["obs000747"]
    assert by_observation["obs001399"] is by_observation["obs001405"]
    assert by_observation["obs000419"] is by_observation["obs000420"]
    assert by_observation["obs000419"]["unit_type"] == "footnote"
    assert by_observation["obs000258"] is not by_observation["obs000259"]
    assert by_observation["obs000511"] is not by_observation["obs000512"]
    display = by_observation["obs000480"]
    assert by_observation["obs000485"] is display
    assert by_observation["obs000486"] is display
    assert by_observation["obs000487"] is display
    assert display["unit_type"] == "display_block"
    assert by_observation["obs000249"] is by_observation["obs000256"]
    assert by_observation["obs000254"] is not by_observation["obs000249"]
    assert by_observation["obs000255"] is not by_observation["obs000249"]
    assert by_observation["obs000378"] is by_observation["obs000383"]
    assert by_observation["obs000384"] is by_observation["obs000388"]
    assert by_observation["obs000416"] is by_observation["obs000428"]
    assert by_observation["obs000509"] is by_observation["obs000517"]
    title_cluster = by_observation["obs002251"]
    assert by_observation["obs002252"] is title_cluster
    assert by_observation["obs002253"] is title_cluster
    assert title_cluster["unit_type"] == "heading"

    assert set(Counter(observation_ids).values()) == {1}
    assert len(by_observation) == len(observation_ids)
    assert [unit["unit_id"] for unit in flow["text_units"]] == [
        f"tu{index:06d}" for index in range(1, len(flow["text_units"]) + 1)
    ]

    title = by_observation["obs000395"]
    assert by_observation["obs000396"] is title
    assert by_observation["obs000397"] is title
    assert title["unit_type"] == "heading"
    assert title["observation_ids"] == ["obs000395", "obs000396", "obs000397"]
    assert title["text"] == "第一章\n楼兰\n中亚的十字路口"


def test_silk_road_text_flow_reconciles_task4_manual_feedback() -> None:
    flow = _build_silk_road_text_flow()
    observed = _load(ROOT / f"data/outputs/golden/observed/{BOOK}_observed.json")
    source_by_id = {
        observation["observation_id"]: observation for observation in observed["observations"]
    }
    by_observation = {
        observation_id: unit
        for unit in flow["text_units"]
        for observation_id in unit["observation_ids"]
    }

    assert by_observation["obs000257"] is by_observation["obs000262"]
    assert by_observation["obs000280"] is by_observation["obs000289"]
    assert by_observation["obs000469"] is by_observation["obs000476"]
    continued_note = by_observation["obs000472"]
    assert by_observation["obs000473"] is continued_note
    assert by_observation["obs000481"] is continued_note
    assert by_observation["obs000482"] is continued_note
    assert by_observation["obs000511"] is not by_observation["obs000512"]
    assert all(
        by_observation[observation_id]["unit_type"] == "footnote"
        for observation_id in (
            "obs000281",
            "obs000282",
            "obs000283",
            "obs000284",
            "obs000285",
            "obs000286",
        )
    )

    first_paged_paragraph = by_observation["obs000249"]["attrs"]["inline_runs"]
    assert first_paged_paragraph[0]["text"] == (
        source_by_id["obs000249"]["attrs"]["inline_runs"][0]["text"]
        + source_by_id["obs000256"]["attrs"]["inline_runs"][0]["text"]
    )
    second_paged_paragraph = by_observation["obs000257"]["attrs"]["inline_runs"]
    assert second_paged_paragraph[0]["text"] == (
        source_by_id["obs000257"]["attrs"]["inline_runs"][0]["text"]
        + source_by_id["obs000262"]["attrs"]["inline_runs"][0]["text"]
    )
    display_runs = by_observation["obs000480"]["attrs"]["inline_runs"]
    assert display_runs[0]["text"] == (
        source_by_id["obs000480"]["attrs"]["inline_runs"][0]["text"]
        + source_by_id["obs000485"]["attrs"]["inline_runs"][0]["text"]
    )
    assert display_runs[1]["text"] == source_by_id["obs000486"]["attrs"]["inline_runs"][0][
        "text"
    ]


def _build_silk_road_text_flow() -> dict:
    observed = _load(ROOT / f"data/outputs/golden/observed/{BOOK}_observed.json")
    skeleton = _load(ROOT / f"data/outputs/golden/skeleton/{BOOK}_skeleton.json")
    page_review = _load(ROOT / f"data/outputs/golden/page-review/{BOOK}/{BOOK}_page_review.json")
    page_layout = build_page_layout_analysis(observed)
    return build_text_flow(observed, skeleton, page_review, page_layout)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
