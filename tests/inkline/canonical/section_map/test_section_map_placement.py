from __future__ import annotations

import json
from pathlib import Path

import pytest

from inkline.canonical import (
    ValidationError,
    build_page_layout_analysis,
    build_section_map_evidence,
    build_section_map_placements,
    build_text_flow,
    validate_section_map_placements,
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def evidence() -> dict:
    observed = _load(ROOT / "data/outputs/golden/observed/中日交流两千年_observed.json")
    skeleton = _load(ROOT / "data/outputs/golden/skeleton/中日交流两千年_skeleton.json")
    page_review = _load(
        ROOT / "data/outputs/golden/page-review/中日交流两千年/中日交流两千年_page_review.json"
    )
    text_flow = build_text_flow(
        observed,
        skeleton,
        page_review,
        build_page_layout_analysis(observed),
    )
    return build_section_map_evidence(skeleton, page_review, text_flow)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _by_page(placements: list[dict]) -> dict[int, dict]:
    return {record["page"]: record for record in placements}


def test_standalone_identity_precedes_section_start_consideration(evidence) -> None:
    page = evidence["page_review_pages"][0]
    assert page["book_block_position"] == "external_wrap"

    placement = _by_page(build_section_map_placements(evidence))[page["page"]]

    assert placement["placement"] == "standalone"
    assert placement["section_id"] is None


@pytest.mark.parametrize("page", [2, 3, 8, 83])
def test_confirmed_title_copyright_toc_and_blank_pages_are_standalone(evidence, page: int) -> None:
    placement = _by_page(build_section_map_placements(evidence))[page]

    assert placement["placement"] == "standalone"
    assert placement["section_id"] is None


def test_unidentified_body_visual_page_is_unresolved(evidence) -> None:
    placement = _by_page(build_section_map_placements(evidence))[108]

    assert placement["placement"] == "unresolved"
    assert placement["section_id"] is None


def test_same_page_parent_and_child_starts_remain_unresolved(evidence) -> None:
    placement = _by_page(build_section_map_placements(evidence))[11]

    assert placement["placement"] == "unresolved"
    assert placement["reason"] == "conflicting_local_section_starts"


def test_single_local_direct_start_is_section_member(evidence) -> None:
    starts_by_page = {}
    for section in evidence["sections"]:
        start = section["start_evidence"]
        if start["text_flow_status"] == "mapped":
            starts_by_page.setdefault(start["page"], []).append(section)
    page, starts = next(
        (page, starts) for page, starts in starts_by_page.items() if len(starts) == 1
    )

    placement = _by_page(build_section_map_placements(evidence))[page]

    assert placement["placement"] == "section_member"
    assert placement["section_id"] == starts[0]["section_id"]


def test_ordinary_text_flow_page_without_local_start_is_unresolved(evidence) -> None:
    start_pages = {
        section["start_evidence"]["page"]
        for section in evidence["sections"]
        if section["start_evidence"]["text_flow_status"] == "mapped"
    }
    record = next(
        page
        for page in evidence["page_review_pages"]
        if page["text_flow_action"] == "include"
        and page["special_page_kind"] is None
        and page["page"] not in start_pages
    )

    placement = _by_page(build_section_map_placements(evidence))[record["page"]]

    assert placement["placement"] == "unresolved"
    assert placement["section_id"] is None


def test_placement_validator_requires_complete_exclusive_page_list(evidence) -> None:
    placements = build_section_map_placements(evidence)

    with pytest.raises(ValidationError, match="every reviewed page"):
        validate_section_map_placements(placements[1:], evidence)
