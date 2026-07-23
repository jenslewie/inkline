from __future__ import annotations

from inkline.canonical.page_review.llm import (
    page_review_llm_prompt,
    page_review_prompt_profile,
)


def test_page_review_prompt_profile_prioritizes_body_section_and_tables() -> None:
    assert page_review_prompt_profile(
        {
            "skeleton_context": {"matter": "pre_body"},
            "signals": ["visual_content"],
            "visual_kinds": ["image_region"],
        }
    ) == "front_visual_identity"
    assert page_review_prompt_profile(
        {
            "skeleton_context": {"matter": "pre_body"},
            "signals": ["raster_dark_visual_layout"],
            "visual_kinds": [],
        }
    ) == "front_visual_identity"
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
    assert "dust_jacket_spread" in prompt
    assert "front_exterior_page" in prompt
    assert "back_exterior_page" in prompt
    assert "cover_flap" in prompt
    assert "decorative_preliminary_page" in prompt
    assert "decorative_title_page" in prompt
    assert "epigraph_page" in prompt
    assert "plate_page" in prompt
    assert "chronology_chart_page" in prompt
    assert "genealogy_chart_page" in prompt
    assert 'literal null without quotes' in prompt

    assert "Do not change the front/body/back boundary" in prompt
    assert "Only classify the supplied candidate pages" in prompt
    assert '"text_flow_action"' in prompt
    assert '"visual_asset_action"' in prompt
    assert '"special_page_kind"' in prompt
    assert "The input is structural evidence, not a prior decision" in prompt
    assert "Review profile: general" in prompt
    assert "Return text_flow_page/include for independent body prose" in prompt
    assert (
        '"book_block_position": "unknown",\n'
        '      "special_page_kind": null,'
    ) in prompt


def test_front_special_prompt_distinguishes_pre_body_from_front_matter() -> None:
    prompt = page_review_llm_prompt({"pages": []}, profile="front_special")

    assert "pre-body physical range" in prompt
    assert "external-wrap pages" in prompt
    assert "both panels are cover_flap" in prompt
    assert "half_title_page/title_page/decorative_preliminary_page/decorative_title_page/epigraph_page" in prompt
    assert "For copyright_page, use visual_page, front_matter, metadata_only, and retain." in prompt
    assert "not dedication_page" in prompt
    assert "A page headed Acknowledgments, Acknowledgements, 致谢, or 鸣谢" in prompt
    assert "bibliographic title page" in prompt
    assert "is dust_jacket_spread, not cover_flap" in prompt
    assert "Classify every supplied physical page independently; do not infer a jacket spread from neighboring pages" in prompt
    assert "verify all four required elements are visibly present in the same image" in prompt
    assert "front-cover design, back-cover design, book spine, and one or more jacket flaps" in prompt
    assert "If any required element is absent or uncertain, dust_jacket_spread is invalid" in prompt
    assert "A standalone front exterior design is front_exterior_page" in prompt
    assert "back_exterior_page" in prompt
    assert "Do not guess whether either surface is a paperback cover or a hardcover board" in prompt


def test_front_residual_prompt_distinguishes_dedication_from_front_prose() -> None:
    prompt = page_review_llm_prompt({"pages": []}, profile="front_residual_unknown")

    assert "dedicates or memorializes the book to a person or memory" in prompt
    assert "dedication_page and uses visual_page/exclude/retain" in prompt
    assert "CIP, ISBN, copyright notice, edition, printing, publisher, or imprint" in prompt
    assert "copyright_page with visual_page/front_matter/metadata_only/retain" in prompt


def test_front_visual_prompt_distinguishes_exteriors_from_plates() -> None:
    prompt = page_review_llm_prompt({"pages": []}, profile="front_visual_identity")

    assert "front_exterior_page" in prompt
    assert "back_exterior_page" in prompt
    assert "Do not call an exterior surface a plate_page" in prompt
    assert "plate_page with visual_page/exclude/retain" in prompt
    assert "Do not require MinerU to have linked a caption to its image" in prompt
    assert "decorative_preliminary_page" in prompt
    assert "decorative_title_page" in prompt
    assert "is half_title_page, not decorative_preliminary_page" in prompt
    assert "chronology_chart_page, not plate_page" in prompt
    assert "genealogy_chart_page, not chronology_chart_page" in prompt


def test_sequence_profiles_distinguish_exterior_and_title_followups() -> None:
    exterior_prompt = page_review_llm_prompt({"pages": []}, profile="after_front_exterior")
    back_exterior_prompt = page_review_llm_prompt({"pages": []}, profile="after_back_exterior")
    dust_jacket_prompt = page_review_llm_prompt({"pages": []}, profile="after_dust_jacket_spread")
    preliminary_prompt = page_review_llm_prompt({"pages": []}, profile="after_decorative_preliminary")
    title_prompt = page_review_llm_prompt({"pages": []}, profile="after_title_page")

    assert "another front-facing exterior surface" in exterior_prompt
    assert "book-internal decorative leaf" in exterior_prompt
    assert "decorative_title_page" in exterior_prompt
    assert "Do not call that composition decorative_title_page" in exterior_prompt
    assert "author biography, publisher details, contact information, or a QR code" in exterior_prompt
    assert "Do not infer a dust jacket, hardcover board, or paperback material" in exterior_prompt
    assert "rear cover flap rather than a second back exterior" in back_exterior_prompt
    assert "not merely because it has a QR code or publisher mark" in back_exterior_prompt
    assert '"special_page_kind": "front_exterior_page"' in dust_jacket_prompt
    assert "MUST use half_title_page" in preliminary_prompt
    assert "further patterned, textured, or intentionally blank leaf" in preliminary_prompt
    assert "decorative_title_page, not another title_page" in title_prompt


def test_dust_jacket_followup_keeps_exposed_exterior_out_of_title_page() -> None:
    prompt = page_review_llm_prompt({"pages": []}, profile="after_dust_jacket_spread")

    assert "immediately preceding physical page was resolved as dust_jacket_spread" in prompt
    assert "front_exterior_page" in prompt
    assert "not title_page merely because it displays the book title" in prompt


def test_front_visual_prompt_keeps_ambiguous_surface_untyped() -> None:
    prompt = page_review_llm_prompt({"pages": []}, profile="front_visual_identity")

    assert "current-page evidence that it is internal" in prompt
    assert "Image dominance alone is insufficient" in prompt
    assert "MUST use special_page_kind=null and book_block_position=unknown, never front_matter" in prompt
