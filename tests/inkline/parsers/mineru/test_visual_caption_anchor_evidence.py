from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from inkline.canonical import (
    build_book_skeleton_from_observed,
    validate_observed_document,
)
from inkline.parsers.mineru.extraction.io import flatten_content_list_v2
from inkline.parsers.mineru.normalize.observed_shadow import build_observed_document_shadow

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "visual_caption_anchor_evidence"
TARGET_FIXTURES = [
    "table_caption_horizontal.json",
    "table_caption_rotated.json",
    "chart_caption.json",
    "appendix_table_caption.json",
]


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _build_pair(fixture: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    observed = build_observed_document_shadow(
        pages=flatten_content_list_v2(fixture["content_list_v2"]),
        page_sizes={
            int(page): (float(size[0]), float(size[1]))
            for page, size in fixture["content_page_sizes"].items()
        },
        metadata={
            "doc_id": fixture["case_id"],
            "title": fixture["case_id"],
            "language": "zh-CN",
            "source_file": f"{fixture['case_id']}.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        middle=fixture["middle"],
    )
    validate_observed_document(observed)
    return observed, build_book_skeleton_from_observed(observed)


def _caption_and_parent(
    observed: dict[str, Any], fixture: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    caption = next(
        observation
        for observation in observed["observations"]
        if observation["role_hint"] == "caption_text"
        and observation["text"] == fixture["caption_text"]
    )
    parent_id = caption["attrs"]["visual_parent_observation_id"]
    parent = next(
        observation
        for observation in observed["observations"]
        if observation["observation_id"] == parent_id
    )
    return caption, parent


@pytest.mark.parametrize("fixture_name", TARGET_FIXTURES)
def test_exact_visual_caption_anchor_owns_its_evidence(fixture_name: str) -> None:
    fixture = _load_fixture(fixture_name)
    observed, skeleton = _build_pair(fixture)
    caption, parent = _caption_and_parent(observed, fixture)
    entry = skeleton["toc_entries"][0]
    anchor = entry["selected_start_anchor"]

    assert parent["kind"] == fixture["resource_kind"]
    assert parent["text"] == fixture["retained_resource_text"]
    assert caption["bbox"] == fixture["caption_bbox"]
    assert caption["attrs"]["bbox_provenance"] == "mineru_middle"
    assert caption["attrs"]["direct_anchor_eligible"] is True
    assert anchor is not None
    assert anchor["resolution_method"] == "observed_title_match"
    assert anchor["page"] == 2
    assert anchor["title_observation_ids"] == [caption["observation_id"]]
    assert parent["observation_id"] not in anchor["title_observation_ids"]


def test_ordinary_precise_caption_and_parent_are_not_promoted() -> None:
    fixture = _load_fixture("ordinary_equation_caption.json")
    observed, skeleton = _build_pair(fixture)
    caption, parent = _caption_and_parent(observed, fixture)
    anchor = skeleton["toc_entries"][0]["selected_start_anchor"]

    assert parent["text"] == fixture["retained_resource_text"]
    assert caption["text"] == fixture["caption_text"]
    assert caption["bbox"] == fixture["caption_bbox"]
    assert caption["attrs"]["bbox_provenance"] == "mineru_middle"
    assert caption["attrs"]["direct_anchor_eligible"] is True
    assert skeleton["toc_entries"][0]["candidate_start_pages"] == [3]
    assert anchor is not None
    assert anchor["page"] == 3
    assert anchor["title_observation_ids"] == ["obs000003"]
    assert caption["observation_id"] not in anchor["title_observation_ids"]
    assert parent["observation_id"] not in anchor["title_observation_ids"]
