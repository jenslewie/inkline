from __future__ import annotations

from inkline.canonical.page_review.llm import page_review_groups, page_review_llm_prompt


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


def test_page_review_prompt_defines_the_strict_decision_contract() -> None:
    prompt = page_review_llm_prompt(
        {
            "first_body_page": 15,
            "pages": [
                {"page": 1, "page_role": "front_visual_page", "signals": ["visual_dominant"]}
            ],
        }
    )

    assert "Do not change the front/body/back boundary" in prompt
    assert "Only classify the supplied candidate pages" in prompt
    assert '"text_flow_action"' in prompt
    assert '"visual_asset_action"' in prompt
