from __future__ import annotations

import pytest

from inkline.canonical import make_observation, make_observed_document, make_observed_page
from inkline.canonical.page_review import (
    build_page_review_plan,
    resolve_page_review,
    validate_resolved_page_review,
)
from inkline.canonical.schema import ValidationError


def test_page_review_selects_visual_observations_and_front_section_continuations() -> None:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 7)],
        [
            make_observation("obs000001", "image_region", page=4, bbox=[100, 100, 900, 1200]),
            make_observation("obs000002", "table_region", page=6, bbox=[100, 100, 900, 1200]),
        ],
    )
    skeleton = {
        "boundaries": {"first_body_page": 6},
        "toc_pages": [2],
        "toc_entries": [
            {"role": "front_matter", "selected_start_page": 4},
            {"role": "body", "selected_start_page": 6},
        ],
    }
    page_roles = [
        {"page": 1, "page_role": "blank_page", "signals": ["no_content_observations"]},
        {"page": 2, "page_role": "text_flow_page", "signals": ["body_profile"]},
        {"page": 3, "page_role": "text_flow_page", "signals": ["body_profile"]},
        {"page": 4, "page_role": "text_flow_page", "signals": ["body_profile"]},
        {"page": 5, "page_role": "text_flow_page", "signals": ["body_profile"]},
        {"page": 6, "page_role": "text_flow_page", "signals": ["body_profile"]},
    ]

    plan = build_page_review_plan(document, skeleton, page_roles)
    by_page = {record["page"]: record for record in plan["pages"]}

    assert plan["candidate_pages"] == [4, 5, 6]
    assert by_page[1]["text_flow_action"] == "exclude"
    assert by_page[1]["visual_asset_action"] == "not_needed"
    assert by_page[1]["llm_review_status"] == "deterministic"
    assert by_page[2]["text_flow_action"] == "metadata_only"
    assert by_page[3]["text_flow_action"] == "include"
    assert by_page[3]["llm_review_status"] == "not_selected"
    assert by_page[4]["text_flow_action"] == "needs_review"
    assert by_page[4]["visual_asset_action"] == "needs_review"
    assert by_page[5]["llm_review_status"] == "pending"
    assert "section_visual_continuity" in by_page[5]["signals"]
    assert by_page[6]["llm_review_status"] == "pending"


def test_page_review_resolves_only_selected_candidates() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.1-shadow"},
        "candidate_pages": [4, 6],
        "pages": [
            _record(3, "text_flow_page", "include", "not_needed", "not_selected"),
            _record(4, "title_like_page", "needs_review", "needs_review", "pending"),
            _record(6, "visual_page", "needs_review", "needs_review", "pending"),
        ],
    }

    resolved = resolve_page_review(
        plan,
        [
            _decision(4, "title_page", "metadata_only", "retain", "high"),
            _decision(6, "table_or_chart_page", "include", "retain", "medium"),
        ],
        llm_model="qwen-test",
    )

    by_page = {record["page"]: record for record in resolved["pages"]}
    assert by_page[3]["decision_source"] == "layout_and_skeleton"
    assert by_page[4]["page_role"] == "title_page"
    assert by_page[4]["text_flow_action"] == "metadata_only"
    assert by_page[4]["visual_asset_action"] == "retain"
    assert by_page[4]["llm_review_status"] == "sent_and_resolved"
    assert resolved["llm"]["reviewed_pages"] == [4, 6]


def test_resolved_page_review_rejects_pending_candidates() -> None:
    review = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.1-shadow"},
        "candidate_pages": [4],
        "pages": [_record(4, "title_like_page", "needs_review", "needs_review", "pending")],
    }

    with pytest.raises(ValidationError, match="candidate page 4 has not been resolved"):
        validate_resolved_page_review(review)


def _record(
    page: int,
    page_role: str,
    text_flow_action: str,
    visual_asset_action: str,
    llm_review_status: str,
) -> dict[str, object]:
    return {
        "page": page,
        "page_role": page_role,
        "text_flow_action": text_flow_action,
        "visual_asset_action": visual_asset_action,
        "decision_source": "llm_page_review" if llm_review_status == "pending" else "layout_and_skeleton",
        "llm_review_status": llm_review_status,
        "signals": [],
    }


def _decision(
    page: int,
    page_role: str,
    text_flow_action: str,
    visual_asset_action: str,
    confidence: str,
) -> dict[str, object]:
    return {
        "page": page,
        "page_role": page_role,
        "text_flow_action": text_flow_action,
        "visual_asset_action": visual_asset_action,
        "confidence": confidence,
    }
