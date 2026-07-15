from __future__ import annotations

from inkline.canonical.page_review.llm import (
    page_review_groups,
    page_review_llm_prompt,
    page_review_profile_groups,
    page_review_prompt_profile,
)


def test_page_review_groups_selected_pages_in_bounded_batches() -> None:
    assert page_review_groups([1, 2, 3, 4, 6, 7, 11], max_pages=3) == [
        [1, 2, 3],
        [4, 6, 7],
        [11],
    ]


def test_page_review_groups_preserve_contiguous_runs_when_possible() -> None:
    assert page_review_groups([1, 3, 4, 5, 6, 7, 8, 9, 10], max_pages=3) == [
        [1],
        [3, 4, 5],
        [6, 7, 8],
        [9, 10],
    ]


def test_page_review_profile_groups_do_not_mix_review_instructions() -> None:
    records = {
        1: {"skeleton_context": {"matter": "pre_body"}, "signals": []},
        2: {"skeleton_context": {"matter": "pre_body"}, "signals": []},
        3: {"skeleton_context": {"matter": "body"}, "signals": ["visual_sparse_text"]},
        4: {"skeleton_context": {"matter": "body"}, "signals": ["visual_sparse_text"]},
        5: {"skeleton_context": {"matter": "body"}, "signals": ["body_profile"]},
    }

    assert page_review_profile_groups([1, 2, 3, 4, 5], records, max_pages=3) == [
        {"matter": "pre_body", "prompt_profile": "front_special", "pages": [1, 2]},
        {"matter": "body", "prompt_profile": "visual_sparse_text", "pages": [3, 4]},
        {"matter": "body", "prompt_profile": "general", "pages": [5]},
    ]


def test_page_review_profile_groups_batches_noncontiguous_pages_by_profile() -> None:
    records = {
        1: {"skeleton_context": {"matter": "body"}, "signals": []},
        3: {"skeleton_context": {"matter": "body"}, "signals": []},
        5: {"skeleton_context": {"matter": "body"}, "signals": []},
        7: {"skeleton_context": {"matter": "body"}, "signals": []},
        9: {"skeleton_context": {"matter": "body"}, "signals": []},
    }

    assert page_review_profile_groups([1, 3, 5, 7, 9], records, max_pages=3) == [
        {"matter": "body", "prompt_profile": "general", "pages": [1, 3, 5]},
        {"matter": "body", "prompt_profile": "general", "pages": [7, 9]},
    ]


def test_page_review_profile_groups_do_not_mix_book_matter() -> None:
    records = {
        1: {"skeleton_context": {"matter": "pre_body"}, "signals": ["body_profile"]},
        2: {"skeleton_context": {"matter": "body"}, "signals": ["body_profile"]},
        3: {"skeleton_context": {"matter": "back_matter"}, "signals": ["body_profile"]},
    }

    assert page_review_profile_groups([1, 2, 3], records, max_pages=4) == [
        {"matter": "pre_body", "prompt_profile": "front_special", "pages": [1]},
        {"matter": "body", "prompt_profile": "general", "pages": [2]},
        {"matter": "back_matter", "prompt_profile": "general", "pages": [3]},
    ]


def test_page_review_prompt_profile_prioritizes_body_section_and_tables() -> None:
    assert page_review_prompt_profile(
        {"skeleton_context": {"matter": "body", "is_body_section_start": True}, "signals": []}
    ) == "body_section_start"
    assert page_review_prompt_profile(
        {"skeleton_context": {"matter": "body"}, "signals": ["visual_sparse_text"], "visual_kinds": ["table_region"]}
    ) == "textual_table"
    assert page_review_prompt_profile(
        {
            "skeleton_context": {"matter": "body"},
            "signals": ["visual_verifier_candidate"],
            "visual_kinds": ["table_region"],
        }
    ) == "textual_table"
    assert page_review_prompt_profile(
        {
            "skeleton_context": {"matter": "back_matter"},
            "signals": ["visual_dominant"],
            "visual_kinds": ["table_region"],
        }
    ) == "textual_table"
    assert page_review_prompt_profile(
        {
            "skeleton_context": {"matter": "body"},
            "signals": ["body_profile"],
            "visual_kinds": ["image_region"],
        }
    ) == "mixed_visual_body"
    assert page_review_prompt_profile(
        {
            "skeleton_context": {"matter": "body"},
            "signals": ["visual_dominant", "no_body_profile"],
            "visual_kinds": ["image_region"],
        }
    ) == "visual_sparse_text"


def test_page_review_prompt_profiles_define_body_and_table_precedence() -> None:
    mixed_prompt = page_review_llm_prompt({"pages": []}, profile="mixed_visual_body")
    table_prompt = page_review_llm_prompt({"pages": []}, profile="textual_table")

    assert "A continuous body paragraph wins over visual area." in mixed_prompt
    assert "A narrow explanatory block directly attached to an image is a caption" in mixed_prompt
    assert "A table_region is presumed to be a readable cell-based table" in table_prompt


def test_page_review_prompt_defines_the_strict_decision_contract() -> None:
    prompt = page_review_llm_prompt(
        {
            "first_body_page": 15,
            "pages": [
                {"page": 1, "page_role": "visual_page", "signals": ["visual_dominant"]}
            ],
        }
    )

    assert "dedication_page" in prompt
    assert "acknowledgments_page" in prompt
    assert "cover_flap" in prompt
    assert 'literal null without quotes' in prompt

    assert "Do not change the front/body/back boundary" in prompt
    assert "Only classify the supplied candidate pages" in prompt
    assert '"text_flow_action"' in prompt
    assert '"visual_asset_action"' in prompt
    assert '"special_page_kind"' in prompt
    assert "The input is structural evidence, not a prior decision" in prompt
    assert "Review profile: general" in prompt
    assert "Return text_flow_page/include for independent body prose" in prompt


def test_front_special_prompt_distinguishes_pre_body_from_front_matter() -> None:
    prompt = page_review_llm_prompt({"pages": []}, profile="front_special")

    assert "pre-body physical range" in prompt
    assert "external-wrap pages" in prompt
    assert "both panels are cover_flap" in prompt
    assert "half_title_page/title_page/dedication_page/acknowledgments_page/copyright_page/toc_page/blank_page -> front_matter" in prompt
    assert "For copyright_page, use visual_page, front_matter, metadata_only, and retain." in prompt
    assert "not dedication_page" in prompt
    assert "A page headed Acknowledgments, Acknowledgements, 致谢, or 鸣谢" in prompt
