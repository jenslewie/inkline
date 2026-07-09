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
