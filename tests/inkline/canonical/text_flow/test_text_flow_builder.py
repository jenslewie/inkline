from __future__ import annotations

import json
from pathlib import Path

from inkline.canonical import build_page_layout_analysis, build_text_flow

ROOT = Path(__file__).resolve().parents[4]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _unit_for_observations(flow: dict, observation_ids: list[str]) -> dict:
    return next(unit for unit in flow["text_units"] if unit["observation_ids"] == observation_ids)


def _middle_kingdom_sources() -> tuple[dict, dict, dict, dict]:
    observed = _load(ROOT / "data/outputs/golden/observed/中日交流两千年_observed.json")
    skeleton = _load(ROOT / "data/outputs/golden/skeleton/中日交流两千年_skeleton.json")
    page_review = _load(
        ROOT / "data/outputs/golden/page-review/中日交流两千年/中日交流两千年_page_review.json"
    )
    return observed, skeleton, page_review, build_page_layout_analysis(observed)


def test_build_text_flow_never_calls_legacy_text_unit_pipeline(monkeypatch) -> None:
    sources = _middle_kingdom_sources()

    def fail_legacy_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("legacy TextUnit pipeline called")

    for target in (
        "inkline.canonical.observed.text_units.build_text_units",
        "inkline.canonical.observed.text_unit_layout.classify_text_units_by_layout",
        "inkline.canonical.text_flow.builder.build_text_units",
        "inkline.canonical.text_flow.builder.classify_text_units_by_layout",
        "inkline.canonical.text_flow.builder.finalize_text_units",
    ):
        monkeypatch.setattr(target, fail_legacy_call, raising=False)

    flow = build_text_flow(*sources)

    assert flow["text_units"][0]["unit_id"] == "tu000001"


def test_text_flow_preserves_distinct_direct_skeleton_anchor_groups() -> None:
    observed = _load(ROOT / "data/outputs/golden/observed/中日交流两千年_observed.json")
    skeleton = _load(ROOT / "data/outputs/golden/skeleton/中日交流两千年_skeleton.json")
    page_review = _load(
        ROOT / "data/outputs/golden/page-review/中日交流两千年/中日交流两千年_page_review.json"
    )
    page_layout = build_page_layout_analysis(observed)

    flow = build_text_flow(observed, skeleton, page_review, page_layout)

    assert _unit_for_observations(flow, ["obs000103", "obs000104"])["text"] == (
        "第一章 邦交的开始\n——倭王与金印"
    )
    assert _unit_for_observations(flow, ["obs000105"])["text"] == "派往乐浪郡的使者"
    assert not any(
        {"obs000103", "obs000104", "obs000105"} <= set(unit["observation_ids"])
        for unit in flow["text_units"]
    )
    excluded_pages = {
        record["page"] for record in page_review["pages"] if record["text_flow_action"] != "include"
    }
    assert not any(excluded_pages.intersection(unit["pages"]) for unit in flow["text_units"])
    assert [unit["unit_id"] for unit in flow["text_units"]] == [
        f"tu{index:06d}" for index in range(1, len(flow["text_units"]) + 1)
    ]
    assert not any(
        "source_text_unit_id" in unit["attrs"] or "source_text_unit_ids" in unit["attrs"]
        for unit in flow["text_units"]
    )


def test_text_flow_uses_supplied_page_layout_without_recomputing_profiles(
    monkeypatch,
) -> None:
    observed = _load(ROOT / "data/outputs/golden/observed/中日交流两千年_observed.json")
    skeleton = _load(ROOT / "data/outputs/golden/skeleton/中日交流两千年_skeleton.json")
    page_review = _load(
        ROOT / "data/outputs/golden/page-review/中日交流两千年/中日交流两千年_page_review.json"
    )
    page_layout = build_page_layout_analysis(observed)

    def fail_if_recomputed(*_args, **_kwargs):
        raise AssertionError("TextFlow recomputed PageLayoutAnalysis")

    monkeypatch.setattr(
        "inkline.canonical.observed.text_unit_layout._page_layout_profile_map",
        fail_if_recomputed,
    )

    flow = build_text_flow(observed, skeleton, page_review, page_layout)

    assert flow["metadata"]["doc_id"] == "中日交流两千年"
