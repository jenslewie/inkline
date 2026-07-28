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
