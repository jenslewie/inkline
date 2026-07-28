from __future__ import annotations

import inspect
import json
from copy import deepcopy
from pathlib import Path

import pytest

from inkline.canonical import (
    ValidationError,
    build_observed_index,
    build_page_layout_analysis,
    build_section_map_evidence,
    build_text_flow,
    validate_section_map_sources,
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def sources() -> tuple[dict, dict, dict, dict]:
    observed = _load(ROOT / "data/outputs/golden/observed/中日交流两千年_observed.json")
    skeleton = _load(ROOT / "data/outputs/golden/skeleton/中日交流两千年_skeleton.json")
    page_review = _load(
        ROOT / "data/outputs/golden/page-review/中日交流两千年/中日交流两千年_page_review.json"
    )
    page_layout = build_page_layout_analysis(observed)
    text_flow = build_text_flow(observed, skeleton, page_review, page_layout)
    return skeleton, page_review, text_flow, observed


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _section(evidence: dict, entry_index: int) -> dict:
    return next(
        section
        for section in evidence["sections"]
        if section["skeleton_entry_index"] == entry_index
    )


def test_evidence_maps_split_titles_to_distinct_exact_text_flow_units(sources) -> None:
    skeleton, page_review, text_flow, _observed = sources

    evidence = build_section_map_evidence(skeleton, page_review, text_flow)

    chapter = _section(evidence, 2)["start_evidence"]
    subsection = _section(evidence, 3)["start_evidence"]
    assert chapter["title_observation_ids"] == ["obs000103", "obs000104"]
    assert subsection["title_observation_ids"] == ["obs000105"]
    assert chapter["text_flow_status"] == "mapped"
    assert chapter["title_text_unit_id"] != subsection["title_text_unit_id"]
    assert evidence["text_flow_order"].index(chapter["title_text_unit_id"]) < evidence[
        "text_flow_order"
    ].index(subsection["title_text_unit_id"])
    serialized = json.dumps(evidence, ensure_ascii=False)
    assert "parser_payload" not in serialized
    assert "text_unit_ids" not in serialized
    assert "physical_ranges" not in serialized


def test_evidence_preserves_offset_anchor_without_fabricated_title_unit(sources) -> None:
    skeleton, page_review, text_flow, _observed = sources

    start = _section(build_section_map_evidence(skeleton, page_review, text_flow), 40)[
        "start_evidence"
    ]

    assert start["method"] == "printed_page_offset"
    assert start["page"] == 135
    assert start["title_text_unit_id"] is None
    assert start["text_flow_status"] == "not_applicable"
    assert start["title_observation_ids"] == []
    assert len(start["supporting_anchor_ids"]) == 2


def test_evidence_preserves_unlocated_section_seed(sources) -> None:
    skeleton, page_review, text_flow, _observed = sources
    unlocated = deepcopy(skeleton)
    entry = unlocated["toc_entries"][3]
    entry["candidate_start_pages"] = []
    entry["selected_start_page"] = None
    entry["selected_start_anchor"] = None

    start = _section(build_section_map_evidence(unlocated, page_review, text_flow), 3)[
        "start_evidence"
    ]

    assert start == {
        "method": "unlocated",
        "anchor_id": None,
        "page": None,
        "title_text_unit_id": None,
        "text_flow_status": "unlocated",
        "title_observation_ids": [],
        "toc_observation_ids": [],
        "supporting_anchor_ids": [],
        "printed_page_offset": None,
    }


@pytest.mark.parametrize("mutation", ["incomplete", "duplicate", "off_page"])
def test_evidence_rejects_invalid_direct_title_coverage(sources, mutation: str) -> None:
    skeleton, page_review, text_flow, _observed = sources
    invalid = deepcopy(text_flow)
    unit = next(
        value
        for value in invalid["text_units"]
        if value["observation_ids"] == ["obs000103", "obs000104"]
    )
    if mutation == "incomplete":
        unit["observation_ids"] = ["obs000103"]
    elif mutation == "duplicate":
        duplicate = deepcopy(unit)
        duplicate["unit_id"] = "tu999999"
        invalid["text_units"].append(duplicate)
    else:
        unit["page"] = 12
        unit["pages"] = [12]

    with pytest.raises(ValidationError):
        build_section_map_evidence(skeleton, page_review, invalid)


def test_source_audit_resolves_observation_and_page_provenance(sources) -> None:
    skeleton, page_review, text_flow, observed = sources

    audited = validate_section_map_sources(
        skeleton,
        page_review,
        text_flow,
        build_observed_index(observed),
    )

    assert audited.doc_id == "中日交流两千年"
    assert audited.units_by_id[
        _section(build_section_map_evidence(skeleton, page_review, text_flow), 2)["start_evidence"][
            "title_text_unit_id"
        ]
    ]["observation_ids"] == ["obs000103", "obs000104"]


def test_source_audit_rejects_incomplete_direct_anchor_mapping(sources) -> None:
    skeleton, page_review, text_flow, observed = sources
    invalid = deepcopy(text_flow)
    unit = next(
        value
        for value in invalid["text_units"]
        if value["observation_ids"] == ["obs000103", "obs000104"]
    )
    unit["observation_ids"] = ["obs000103"]

    with pytest.raises(ValidationError, match="exact TextFlow mapping"):
        validate_section_map_sources(
            skeleton,
            page_review,
            invalid,
            build_observed_index(observed),
        )


def test_business_builder_does_not_accept_observed_document_or_raw_text_units() -> None:
    assert tuple(inspect.signature(build_section_map_evidence).parameters) == (
        "skeleton",
        "page_review",
        "text_flow",
    )
