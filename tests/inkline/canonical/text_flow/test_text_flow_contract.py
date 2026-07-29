from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from inkline.canonical import (
    ValidationError,
    build_page_layout_analysis,
    build_text_flow,
    validate_text_flow,
    validate_text_flow_against_sources,
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def sources() -> tuple[dict, dict, dict, dict, dict]:
    observed = _load(ROOT / "data/outputs/golden/observed/中日交流两千年_observed.json")
    skeleton = _load(ROOT / "data/outputs/golden/skeleton/中日交流两千年_skeleton.json")
    page_review = _load(
        ROOT / "data/outputs/golden/page-review/中日交流两千年/中日交流两千年_page_review.json"
    )
    page_layout = build_page_layout_analysis(observed)
    flow = build_text_flow(observed, skeleton, page_review, page_layout)
    return flow, observed, skeleton, page_review, page_layout


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _valid_text_flow_fixture(sources) -> tuple[dict, tuple[dict, dict, dict, dict]]:
    flow, observed, skeleton, page_review, page_layout = deepcopy(sources)
    for unit in flow["text_units"]:
        if unit["unit_type"] not in {"paragraph", "display_block"}:
            continue
        unit["attrs"].setdefault(
            "layout_fragments",
            [
                {
                    "observation_id": observation_id,
                    "page": unit["page"],
                    "classified_type": unit["unit_type"],
                    "status": "resolved",
                    "layout_form": None,
                    "signals": [],
                }
                for observation_id in unit["observation_ids"]
            ],
        )
    return flow, (observed, skeleton, page_review, page_layout)


def _three_page_text_flow_fixture(
    sources,
) -> tuple[dict, tuple[dict, dict, dict, dict]]:
    flow, source_artifacts = _valid_text_flow_fixture(sources)
    target_ids = {"obs000051", "obs000053", "obs000063"}
    target = next(
        unit for unit in flow["text_units"] if "obs000051" in unit["observation_ids"]
    )
    target["unit_type"] = "paragraph"
    target["pages"] = [4, 5, 6]
    target["observation_ids"] = ["obs000051", "obs000053", "obs000063"]
    target["attrs"]["layout_fragments"] = [
        {
            "observation_id": observation_id,
            "page": page,
            "classified_type": "paragraph",
            "status": "resolved",
            "layout_form": None,
            "signals": [],
        }
        for observation_id, page in zip(target["observation_ids"], target["pages"], strict=True)
    ]
    target["attrs"]["merge_events"] = [
        {"left_page": 4, "right_page": 5},
        {"left_page": 5, "right_page": 6},
    ]
    flow["text_units"] = [
        unit
        for unit in flow["text_units"]
        if unit is target or target_ids.isdisjoint(unit["observation_ids"])
    ]
    for index, unit in enumerate(flow["text_units"], start=1):
        unit["unit_id"] = f"tu{index:06d}"
    return flow, source_artifacts


def _three_page_unit(flow: dict) -> dict:
    return next(unit for unit in flow["text_units"] if unit["pages"] == [4, 5, 6])


def test_text_flow_contract_accepts_built_artifact(sources) -> None:
    flow, observed, skeleton, page_review, page_layout = sources

    validate_text_flow(flow)
    validate_text_flow_against_sources(flow, observed, skeleton, page_review, page_layout)


def test_text_flow_contract_rejects_non_contiguous_unit_identity(sources) -> None:
    flow = deepcopy(sources[0])
    flow["text_units"][0]["unit_id"] = "lu000001"

    with pytest.raises(ValidationError, match="contiguous tu ids"):
        validate_text_flow(flow)


def test_text_flow_contract_rejects_crossed_direct_anchor_boundary(sources) -> None:
    flow, observed, skeleton, page_review, page_layout = sources
    crossed = deepcopy(flow)
    chapter = next(
        unit
        for unit in crossed["text_units"]
        if unit["observation_ids"] == ["obs000103", "obs000104"]
    )
    subsection = next(
        unit for unit in crossed["text_units"] if unit["observation_ids"] == ["obs000105"]
    )
    chapter["observation_ids"].extend(subsection["observation_ids"])
    crossed["text_units"].remove(subsection)
    for index, unit in enumerate(crossed["text_units"], start=1):
        unit["unit_id"] = f"tu{index:06d}"

    with pytest.raises(ValidationError, match=r"exact TextUnit|crosses distinct"):
        validate_text_flow_against_sources(crossed, observed, skeleton, page_review, page_layout)


def test_validation_rejects_mixed_layout_fragments(sources) -> None:
    flow, source_artifacts = _valid_text_flow_fixture(sources)
    paragraph = next(
        unit for unit in flow["text_units"] if unit["unit_type"] == "paragraph"
    )
    paragraph["attrs"]["layout_fragments"][0]["classified_type"] = "display_block"

    with pytest.raises(ValidationError, match="layout fragment type"):
        validate_text_flow_against_sources(flow, *source_artifacts)


def test_validation_requires_one_event_per_cross_page_transition(sources) -> None:
    flow, source_artifacts = _three_page_text_flow_fixture(sources)
    _three_page_unit(flow)["attrs"]["merge_events"].pop()

    with pytest.raises(ValidationError, match="adjacent-page transition"):
        validate_text_flow_against_sources(flow, *source_artifacts)


def test_validation_requires_cross_page_footnote_merge_events(sources) -> None:
    flow, _source_artifacts = _three_page_text_flow_fixture(sources)
    footnote = _three_page_unit(flow)
    footnote["unit_type"] = "footnote"
    footnote["attrs"].pop("layout_fragments")
    footnote["attrs"]["merge_events"].pop()

    with pytest.raises(ValidationError, match="adjacent-page transition"):
        validate_text_flow(flow)


@pytest.mark.parametrize(
    "extra_event",
    [
        {"left_page": 6, "right_page": 7},
        {"left_page": 4, "right_page": 5},
        "not-an-event",
        {"reason": "missing pages"},
        {"left_page": "4", "right_page": 5},
    ],
    ids=["unmatched", "duplicate", "non-mapping", "missing-pages", "invalid-pages"],
)
def test_validation_requires_exact_transition_event_collection(
    sources, extra_event
) -> None:
    flow, _source_artifacts = _three_page_text_flow_fixture(sources)
    _three_page_unit(flow)["attrs"]["merge_events"].append(extra_event)

    with pytest.raises(ValidationError, match="adjacent-page transition"):
        validate_text_flow(flow)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("observation_id", ""),
        ("page", True),
        ("classified_type", []),
        ("status", "pending"),
        ("status", []),
        ("layout_form", []),
        ("signals", "display_gap_before"),
    ],
)
def test_validation_rejects_invalid_layout_fragment_fields(
    sources, field, invalid_value
) -> None:
    flow, _source_artifacts = _valid_text_flow_fixture(sources)
    paragraph = next(
        unit for unit in flow["text_units"] if unit["unit_type"] == "paragraph"
    )
    paragraph["attrs"]["layout_fragments"][0][field] = invalid_value

    with pytest.raises(ValidationError, match="layout fragment"):
        validate_text_flow(flow)


@pytest.mark.parametrize(
    "field",
    [
        "observation_id",
        "page",
        "classified_type",
        "status",
        "layout_form",
        "signals",
    ],
)
def test_validation_rejects_missing_layout_fragment_fields(sources, field) -> None:
    flow, _source_artifacts = _valid_text_flow_fixture(sources)
    paragraph = next(
        unit for unit in flow["text_units"] if unit["unit_type"] == "paragraph"
    )
    paragraph["attrs"]["layout_fragments"][0].pop(field)

    with pytest.raises(ValidationError, match="layout fragment"):
        validate_text_flow(flow)


def test_validation_rejects_non_mapping_layout_fragment(sources) -> None:
    flow, _source_artifacts = _valid_text_flow_fixture(sources)
    paragraph = next(
        unit for unit in flow["text_units"] if unit["unit_type"] == "paragraph"
    )
    paragraph["attrs"]["layout_fragments"][0] = []

    with pytest.raises(ValidationError, match="layout fragment"):
        validate_text_flow(flow)
