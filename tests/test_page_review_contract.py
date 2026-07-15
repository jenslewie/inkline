from __future__ import annotations

import pytest

from inkline.canonical import make_observation, make_observed_document, make_observed_page
from inkline.canonical.page_review import (
    build_page_review_plan,
    resolve_page_review,
    validate_resolved_page_review,
)
from inkline.canonical.schema import ValidationError


def test_page_review_selects_only_front_matter_visual_observations() -> None:
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

    assert plan["candidate_pages"] == [4]
    assert by_page[1]["text_flow_action"] == "exclude"
    assert by_page[1]["visual_asset_action"] == "not_needed"
    assert by_page[1]["page_role"] == "visual_page"
    assert by_page[1]["special_page_kind"] == "blank_page"
    assert by_page[1]["llm_review_status"] == "deterministic"
    assert by_page[2]["text_flow_action"] == "metadata_only"
    assert by_page[3]["text_flow_action"] == "include"
    assert by_page[3]["llm_review_status"] == "not_selected"
    assert by_page[4]["text_flow_action"] == "needs_review"
    assert by_page[4]["visual_asset_action"] == "needs_review"
    assert by_page[5]["llm_review_status"] == "not_selected"
    assert by_page[5]["text_flow_action"] == "include"
    assert by_page[5]["visual_asset_action"] == "not_needed"
    assert by_page[6]["llm_review_status"] == "not_selected"
    assert by_page[6]["text_flow_action"] == "include"
    assert by_page[6]["visual_asset_action"] == "not_needed"


def test_page_review_resolves_non_pre_body_visual_pages_from_layout() -> None:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 4)],
        [make_observation("obs000001", "image_region", page=3, bbox=[100, 100, 900, 1200])],
    )
    skeleton = {
        "boundaries": {"first_body_page": 2},
        "toc_pages": [],
        "toc_entries": [{"role": "body", "selected_start_page": 2}],
    }
    page_roles = [
        {"page": 1, "page_role": "front_matter_page", "signals": ["body_profile"]},
        {"page": 2, "page_role": "text_flow_page", "signals": ["body_profile"]},
        {"page": 3, "page_role": "visual_page", "signals": ["visual_dominant"]},
    ]

    plan = build_page_review_plan(document, skeleton, page_roles)
    page_three = next(record for record in plan["pages"] if record["page"] == 3)

    assert page_three["llm_review_status"] == "not_selected"
    assert page_three["text_flow_action"] == "exclude"
    assert page_three["visual_asset_action"] == "retain"


def test_page_review_does_not_select_unindexed_front_matter_text_for_llm_review() -> None:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 4)],
        [],
    )
    skeleton = {
        "boundaries": {"first_body_page": 3},
        "toc_pages": [],
        "toc_entries": [
            {"role": "front_matter", "selected_start_page": 2},
            {"role": "body", "selected_start_page": 3},
        ],
    }
    page_roles = [
        {"page": 1, "page_role": "front_matter_page", "signals": ["unnumbered_prelude"]},
        {"page": 2, "page_role": "text_flow_page", "signals": ["body_profile"]},
        {"page": 3, "page_role": "text_flow_page", "signals": ["body_profile"]},
    ]

    plan = build_page_review_plan(document, skeleton, page_roles)
    page_one = next(record for record in plan["pages"] if record["page"] == 1)

    assert page_one["llm_review_status"] == "not_selected"
    assert page_one["text_flow_action"] == "include"
    assert page_one["visual_asset_action"] == "not_needed"


def test_page_review_selects_sparse_front_visual_but_not_front_prose() -> None:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 4)],
        [],
    )
    skeleton = {
        "boundaries": {"first_body_page": 3},
        "toc_pages": [],
        "toc_entries": [
            {"role": "front_matter", "selected_start_page": 1},
            {"role": "body", "selected_start_page": 3},
        ],
    }
    page_roles = [
        {"page": 1, "page_role": "front_matter_page", "signals": ["body_profile"]},
        {
            "page": 2,
            "page_role": "front_visual_page",
            "signals": ["sparse_centered_text", "body_profile"],
        },
        {"page": 3, "page_role": "text_flow_page", "signals": ["body_profile"]},
    ]

    plan = build_page_review_plan(document, skeleton, page_roles)
    by_page = {record["page"]: record for record in plan["pages"]}

    assert plan["candidate_pages"] == [2]
    assert by_page[1]["llm_review_status"] == "not_selected"
    assert by_page[1]["text_flow_action"] == "include"
    assert by_page[1]["visual_asset_action"] == "not_needed"
    assert by_page[2]["llm_review_status"] == "pending"


def test_page_review_selects_dark_pre_body_text_page_for_visual_review() -> None:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 3)],
        [],
    )
    plan = build_page_review_plan(
        document,
        {"boundaries": {"first_body_page": 2}},
        [
            {
                "page": 1,
                "page_role": "front_matter_page",
                "signals": ["text_content", "body_profile", "raster_dark_visual_layout"],
            },
            {"page": 2, "page_role": "text_flow_page", "signals": ["body_profile"]},
        ],
    )

    assert plan["candidate_pages"] == [1]


def test_page_review_accepts_dedication_page() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.4-shadow"},
        "candidate_pages": [3],
        "pages": [_record(3, "visual_page", "needs_review", "needs_review", "pending")],
    }

    resolved = resolve_page_review(
        plan,
        [_decision(3, "visual_page", "dedication_page", "exclude", "retain", "high")],
        llm_model="qwen-test",
        llm_prompt_version="test-prompt-v1",
    )

    assert resolved["pages"][0]["special_page_kind"] == "dedication_page"


def test_page_review_normalizes_acknowledgments_page_to_front_text_flow() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.6-shadow"},
        "candidate_pages": [3],
        "pages": [_record(3, "visual_page", "needs_review", "needs_review", "pending")],
    }

    resolved = resolve_page_review(
        plan,
        [
            _decision(
                3,
                "visual_page",
                "acknowledgments_page",
                "exclude",
                "retain",
                "high",
            )
        ],
        llm_model="qwen-test",
        llm_prompt_version="test-prompt-v1",
    )

    record = resolved["pages"][0]
    assert record["special_page_kind"] == "acknowledgments_page"
    assert record["page_role"] == "text_flow_page"
    assert record["book_block_position"] == "front_matter"
    assert record["text_flow_action"] == "include"
    assert record["visual_asset_action"] == "not_needed"


def test_page_review_accepts_cover_flap() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.4-shadow"},
        "candidate_pages": [2],
        "pages": [_record(2, "visual_page", "needs_review", "needs_review", "pending")],
    }

    resolved = resolve_page_review(
        plan,
        [
            _decision(
                2,
                "visual_page",
                "cover_flap",
                "exclude",
                "retain",
                "high",
                book_block_position="external_wrap",
            )
        ],
        llm_model="qwen-test",
        llm_prompt_version="test-prompt-v1",
    )

    assert resolved["pages"][0]["special_page_kind"] == "cover_flap"
    assert resolved["pages"][0]["book_block_position"] == "external_wrap"


def test_page_review_normalizes_hardcover_wrap_special_pages() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.7-shadow"},
        "candidate_pages": [2, 3],
        "pages": [
            _record(2, "text_flow_page", "needs_review", "needs_review", "pending"),
            _record(3, "text_flow_page", "needs_review", "needs_review", "pending"),
        ],
    }

    resolved = resolve_page_review(
        plan,
        [
            _decision(
                2,
                "text_flow_page",
                "dust_jacket_spread",
                "include",
                "not_needed",
                "high",
                book_block_position="external_wrap",
            ),
            _decision(
                3,
                "text_flow_page",
                "front_board",
                "include",
                "not_needed",
                "high",
                book_block_position="external_wrap",
            ),
        ],
        llm_model="qwen-test",
        llm_prompt_version="test-prompt-v1",
    )

    for record, special_page_kind in zip(
        resolved["pages"], ["dust_jacket_spread", "front_board"], strict=True
    ):
        assert record["special_page_kind"] == special_page_kind
        assert record["page_role"] == "visual_page"
        assert record["book_block_position"] == "external_wrap"
        assert record["text_flow_action"] == "exclude"
        assert record["visual_asset_action"] == "retain"


def test_page_review_rejects_external_wrap_kind_with_book_position() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.4-shadow"},
        "candidate_pages": [2],
        "pages": [_record(2, "visual_page", "needs_review", "needs_review", "pending")],
    }

    with pytest.raises(ValidationError, match="requires external_wrap"):
        resolve_page_review(
            plan,
            [_decision(2, "visual_page", "cover_flap", "exclude", "retain", "high")],
            llm_model="qwen-test",
            llm_prompt_version="test-prompt-v1",
        )


def test_page_review_derives_copyright_page_consumption_policy() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.4-shadow"},
        "candidate_pages": [4],
        "pages": [_record(4, "text_flow_page", "needs_review", "needs_review", "pending")],
    }

    resolved = resolve_page_review(
        plan,
        [
            _decision(
                4,
                "text_flow_page",
                "copyright_page",
                "include",
                "not_needed",
                "high",
                book_block_position="external_wrap",
            )
        ],
        llm_model="qwen-test",
        llm_prompt_version="test-prompt-v1",
    )

    page = resolved["pages"][0]
    assert page["page_role"] == "visual_page"
    assert page["book_block_position"] == "front_matter"
    assert page["text_flow_action"] == "metadata_only"
    assert page["visual_asset_action"] == "retain"


def test_page_review_normalizes_string_null_special_page_kind() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.4-shadow"},
        "candidate_pages": [4],
        "pages": [_record(4, "visual_page", "needs_review", "needs_review", "pending")],
    }

    resolved = resolve_page_review(
        plan,
        [_decision(4, "visual_page", "null", "exclude", "retain", "high")],
        llm_model="qwen-test",
        llm_prompt_version="test-prompt-v1",
    )

    assert resolved["pages"][0]["special_page_kind"] is None


def test_page_review_marks_toc_body_starts_as_structural_context() -> None:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 5)],
        [],
    )
    skeleton = {
        "boundaries": {"first_body_page": 2},
        "toc_pages": [],
        "toc_entries": [
            {"role": "front_matter", "selected_start_page": 1},
            {"role": "body", "selected_start_page": 2},
            {"role": "body", "selected_start_page": 4},
        ],
    }
    page_roles = [
        {"page": page, "page_role": "text_flow_page", "signals": ["body_profile"]}
        for page in range(1, 5)
    ]

    plan = build_page_review_plan(document, skeleton, page_roles)
    by_page = {record["page"]: record for record in plan["pages"]}

    assert by_page[1]["skeleton_context"] == {"matter": "pre_body", "is_body_section_start": False}
    assert "is_pre_body_candidate" not in by_page[1]
    assert "is_front_matter_candidate" not in by_page[1]
    assert by_page[2]["skeleton_context"] == {"matter": "body", "is_body_section_start": True}
    assert by_page[3]["skeleton_context"] == {"matter": "body", "is_body_section_start": False}
    assert by_page[4]["skeleton_context"] == {"matter": "body", "is_body_section_start": True}


def test_page_review_materializes_skeleton_front_matter_position() -> None:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 11)],
        [],
    )
    skeleton = {
        "boundaries": {"first_body_page": 8},
        "toc_pages": [7],
        "toc_entries": [
            {"role": "front_matter", "selected_start_page": 4},
            {"role": "body", "selected_start_page": 8},
        ],
    }
    page_roles = [
        {"page": page, "page_role": "text_flow_page", "signals": ["body_profile"]}
        for page in range(1, 11)
    ]

    plan = build_page_review_plan(document, skeleton, page_roles)
    by_page = {record["page"]: record for record in plan["pages"]}

    assert by_page[1]["book_block_position"] == "unknown"
    assert by_page[4]["book_block_position"] == "front_matter"
    assert by_page[6]["book_block_position"] == "front_matter"
    assert by_page[7]["book_block_position"] == "front_matter"
    assert by_page[8]["book_block_position"] == "body"


def test_page_review_resolves_only_selected_candidates() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.1-shadow"},
        "candidate_pages": [4, 6],
        "pages": [
            _record(3, "text_flow_page", "include", "not_needed", "not_selected"),
            _record(4, "visual_page", "needs_review", "needs_review", "pending"),
            _record(6, "visual_page", "needs_review", "needs_review", "pending"),
        ],
    }

    resolved = resolve_page_review(
        plan,
        [
            _decision(4, "visual_page", "title_page", "metadata_only", "retain", "high"),
            _decision(6, "text_flow_page", None, "include", "retain", "medium"),
        ],
        llm_model="qwen-test",
        llm_prompt_version="test-prompt-v1",
    )

    by_page = {record["page"]: record for record in resolved["pages"]}
    assert by_page[3]["decision_source"] == "layout_and_skeleton"
    assert by_page[4]["page_role"] == "visual_page"
    assert by_page[4]["special_page_kind"] == "title_page"
    assert by_page[4]["text_flow_action"] == "metadata_only"
    assert by_page[4]["visual_asset_action"] == "retain"
    assert by_page[4]["llm_review_status"] == "sent_and_resolved"
    assert resolved["llm"] == {"model": "qwen-test", "prompt_version": "test-prompt-v1"}


def test_page_review_accepts_text_flow_page_for_a_visual_candidate_with_body_text() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.1-shadow"},
        "candidate_pages": [267],
        "pages": [_record(267, "text_flow_page", "needs_review", "needs_review", "pending")],
    }

    resolved = resolve_page_review(
        plan,
        [_decision(267, "text_flow_page", None, "include", "retain", "high")],
        llm_model="qwen-test",
        llm_prompt_version="test-prompt-v1",
    )

    assert resolved["pages"][0]["page_role"] == "text_flow_page"
    assert resolved["pages"][0]["text_flow_action"] == "include"


def test_resolved_page_review_rejects_pending_candidates() -> None:
    review = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.1-shadow"},
        "candidate_pages": [4],
        "pages": [_record(4, "visual_page", "needs_review", "needs_review", "pending")],
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
        "book_block_position": "unknown",
        "special_page_kind": None,
        "text_flow_action": text_flow_action,
        "visual_asset_action": visual_asset_action,
        "decision_source": "llm_page_review" if llm_review_status == "pending" else "layout_and_skeleton",
        "llm_review_status": llm_review_status,
        "signals": [],
    }


def _decision(
    page: int,
    page_role: str,
    special_page_kind: str | None,
    text_flow_action: str,
    visual_asset_action: str,
    confidence: str,
    book_block_position: str = "front_matter",
) -> dict[str, object]:
    return {
        "page": page,
        "page_role": page_role,
        "book_block_position": book_block_position,
        "special_page_kind": special_page_kind,
        "text_flow_action": text_flow_action,
        "visual_asset_action": visual_asset_action,
        "confidence": confidence,
    }


def test_page_review_rejects_visual_page_that_includes_ocr_text() -> None:
    plan = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.1-shadow"},
        "candidate_pages": [15],
        "pages": [_record(15, "visual_page", "needs_review", "needs_review", "pending")],
    }

    with pytest.raises(ValidationError, match="visual_page cannot include text flow"):
        resolve_page_review(
            plan,
            [_decision(15, "visual_page", None, "include", "retain", "high")],
            llm_model="qwen-test",
            llm_prompt_version="test-prompt-v1",
        )


def test_resolved_page_review_rejects_legacy_role_on_any_page_record() -> None:
    review = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.4-shadow"},
        "candidate_pages": [],
        "pages": [
            {
                **_record(18, "table_or_chart_page", "include", "retain", "not_selected"),
                "special_page_kind": None,
            }
        ],
    }

    with pytest.raises(ValidationError, match=r"pages\[0\].page_role is invalid"):
        validate_resolved_page_review(review)
