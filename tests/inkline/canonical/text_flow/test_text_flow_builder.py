from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from inkline.canonical import build_page_layout_analysis, build_text_flow

ROOT = Path(__file__).resolve().parents[4]
AGINCOURT = "阿金库尔战役"
MIN_KINGDOM = "闽国"


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


def _agincourt_sources() -> tuple[dict, dict, dict, dict]:
    observed = _load(ROOT / f"data/outputs/golden/observed/{AGINCOURT}_observed.json")
    skeleton = _load(ROOT / f"data/outputs/golden/skeleton/{AGINCOURT}_skeleton.json")
    page_review = _load(
        ROOT / f"data/outputs/golden/page-review/{AGINCOURT}/{AGINCOURT}_page_review.json"
    )
    return observed, skeleton, page_review, build_page_layout_analysis(observed)


def _golden_sources(book: str) -> tuple[dict, dict, dict, dict]:
    observed = _load(ROOT / f"data/outputs/golden/observed/{book}_observed.json")
    skeleton = _load(ROOT / f"data/outputs/golden/skeleton/{book}_skeleton.json")
    page_review = _load(ROOT / f"data/outputs/golden/page-review/{book}/{book}_page_review.json")
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


def test_direct_anchor_precedes_same_slot_shadow_without_dropping_it() -> None:
    flow = build_text_flow(*_agincourt_sources())
    anchor = _unit_for_observations(flow, ["obs000974", "obs000975"])
    shadow_units = [unit for unit in flow["text_units"] if "obs003606" in unit["observation_ids"]]

    assert anchor["unit_type"] == "heading"
    assert len(shadow_units) == 1
    assert shadow_units[0]["observation_ids"] == ["obs003606"]


def test_source_validation_uses_direct_anchor_priority_within_title_slot() -> None:
    observed, skeleton, page_review, page_layout = _golden_sources(MIN_KINGDOM)
    page_review = deepcopy(page_review)
    page_record = next(record for record in page_review["pages"] if record["page"] == 211)
    page_record["page_role"] = "text_flow_page"
    page_record["text_flow_action"] = "include"
    page_record["visual_asset_action"] = "not_needed"

    flow = build_text_flow(observed, skeleton, page_review, page_layout)
    anchor = _unit_for_observations(flow, ["obs001732"])
    shadow_units = [unit for unit in flow["text_units"] if "obs001778" in unit["observation_ids"]]

    assert anchor["unit_type"] == "heading"
    assert len(shadow_units) == 1
    assert shadow_units[0]["observation_ids"] == ["obs001778"]
