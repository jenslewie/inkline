from __future__ import annotations

from inkline.canonical import (
    book_skeleton_toc_llm_prompt,
    build_book_skeleton_from_observed,
    make_observation,
    make_observed_document,
    make_observed_page,
)


def test_locates_split_short_title_blocks_before_notes() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 290)]
    document = make_observed_document(
        {
            "doc_id": "attila",
            "title": "匈人王阿提拉",
            "language": "zh-CN",
            "source_file": "attila.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n第一章 阿提拉在当下 1\n第二章 扫荡欧洲 13\n注释 281",
                page=4,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="第一章",
                page=6,
                role_hint="body_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="阿提拉在当下",
                page=6,
                role_hint="body_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="第二章",
                page=18,
                role_hint="title_text",
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="扫荡欧洲",
                page=18,
                role_hint="title_text",
            ),
            make_observation(
                "obs000006",
                "text_region",
                text="注释",
                page=286,
                role_hint="title_text",
            ),
            make_observation(
                "obs000007",
                "text_region",
                text="第一章 阿提拉在当下",
                page=286,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}

    assert entries["第一章 阿提拉在当下"]["candidate_start_pages"][0] == 6
    assert entries["第一章 阿提拉在当下"]["selected_start_page"] == 6


def test_toc_llm_prompt_discourages_spaces_inside_compact_chinese_words() -> None:
    prompt = book_skeleton_toc_llm_prompt(
        {
            "mode": "toc_image_extraction",
            "toc_pages": [4],
            "expected_output": {"toc_entries": []},
        }
    )

    assert "Use '缩写', '年表', and '致谢'" in prompt


def test_toc_llm_prompt_preserves_decimal_chapter_numbers() -> None:
    prompt = book_skeleton_toc_llm_prompt(
        {
            "mode": "toc_image_extraction",
            "toc_pages": [39],
            "expected_output": {"toc_entries": []},
        }
    )

    assert "Use '第1章', not '第Ⅰ章'" in prompt


def test_toc_llm_prompt_keeps_aligned_back_matter_top_level() -> None:
    prompt = book_skeleton_toc_llm_prompt(
        {
            "mode": "toc_image_extraction",
            "toc_pages": [13],
            "expected_output": {"toc_entries": []},
        }
    )

    assert "If a back_matter entry is visually aligned with top-level chapters" in prompt
    assert "Do not make it a child of the final body entry" in prompt
    assert "Entries with the same left alignment must have the same level" in prompt


def test_toc_llm_prompt_makes_visual_indent_decisive() -> None:
    prompt = book_skeleton_toc_llm_prompt(
        {
            "mode": "toc_image_extraction",
            "toc_pages": [13],
            "expected_output": {"toc_entries": []},
        }
    )

    assert "Treat visual indentation as decisive" in prompt
    assert "semantic relationship is unclear" in prompt


def test_toc_llm_prompt_requires_attachment_order_and_role_sequence() -> None:
    prompt = book_skeleton_toc_llm_prompt(
        {
            "mode": "toc_image_extraction",
            "toc_pages": [4, 5],
            "expected_output": {"toc_entries": []},
        }
    )

    assert "TOC images, supplied in preceding messages, are in ascending physical PDF" in prompt
    assert "Do not reorder or group TOC entries by role" in prompt
    assert "must not be classified as front_matter" in prompt


def test_toc_llm_prompt_excludes_the_toc_page_heading() -> None:
    prompt = book_skeleton_toc_llm_prompt(
        {
            "mode": "toc_image_extraction",
            "toc_pages": [4],
            "expected_output": {"toc_entries": []},
        }
    )

    assert "Do not emit a TOC page heading as a toc_entry" in prompt


def test_toc_llm_prompt_splits_packed_parenthesized_toc_entries() -> None:
    prompt = book_skeleton_toc_llm_prompt(
        {
            "mode": "toc_image_extraction",
            "toc_pages": [8],
            "expected_output": {"toc_entries": []},
        }
    )

    assert "A(191)/B(193) represents two TOC entries" in prompt


def test_locates_toc_entry_from_table_region_caption_text() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 350)]
    document = make_observed_document(
        {
            "doc_id": "attila",
            "title": "匈人王阿提拉",
            "language": "zh-CN",
            "source_file": "attila.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n资料来源 329\n参考文献 333\n帝王姓名表 346",
                page=5,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "table_region",
                text="资料来源",
                page=329,
                role_hint="unknown",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="参考文献",
                page=338,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "table_region",
                text="帝王姓名表",
                page=346,
                role_hint="unknown",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}

    assert entries["资料来源"]["selected_start_page"] == 329
    assert entries["帝王姓名表"]["selected_start_page"] == 346
