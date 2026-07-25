from __future__ import annotations

import pytest

import inkline.canonical as canonical_api
from inkline.canonical import (
    build_book_skeleton_from_observed,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.book_skeleton.pages import (
    add_printed_page_offset_candidates,
    select_monotonic_start_pages,
)
from inkline.canonical.book_skeleton.toc import (
    assign_toc_hierarchy,
    infer_toc_levels,
    parse_toc_entries,
)
from inkline.canonical.schema import ValidationError


def test_build_book_skeleton_prefers_exact_title_over_same_page_fuzzy_candidate() -> None:
    document = make_observed_document(
        {
            "doc_id": "fuzzy-title",
            "title": "Fuzzy Title",
            "language": "zh-CN",
            "source_file": "fuzzy-title.pdf",
            "parser_name": "test-parser",
            "parser_mode": "structured",
        },
        [
            make_observed_page(1, width=1000, height=1400),
            make_observed_page(2, width=1000, height=1400),
        ],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n第1章 资料来源 2",
                page=1,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="第1章 资料来源\n本页正文说明",
                page=2,
                role_hint="title_text",
            ),
            make_observation(
                "obs000010",
                "text_region",
                text="资料",
                page=2,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="来源",
                page=2,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entry = skeleton["toc_entries"][0]

    assert entry["selected_start_page"] == 2
    assert entry["selected_start_anchor"]["title_observation_ids"] == ["obs000010", "obs000003"]


def test_build_book_skeleton_preserves_exact_split_anchor_evidence_order() -> None:
    document = make_observed_document(
        {
            "doc_id": "split-title",
            "title": "Split Title",
            "language": "zh-CN",
            "source_file": "split-title.pdf",
            "parser_name": "test-parser",
            "parser_mode": "structured",
        },
        [
            make_observed_page(1, width=1000, height=1400),
            make_observed_page(2, width=1000, height=1400),
        ],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n资料来源 2",
                page=1,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000010",
                "text_region",
                text="资料",
                page=2,
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="来源",
                page=2,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    anchor = skeleton["toc_entries"][0]["selected_start_anchor"]

    assert anchor is not None
    assert anchor["title_observation_ids"] == ["obs000010", "obs000002"]


def test_parse_toc_entries_keeps_printed_page_as_internal_evidence() -> None:
    entries = parse_toc_entries("亚瑟／3\n主教座堂／15")

    assert [entry["printed_start_page"] for entry in entries] == [3, 15]


def test_parse_toc_entries_splits_packed_parenthesized_children() -> None:
    entries = parse_toc_entries(
        "第九章 郑成功父子——唇齿之谊 191\n"
        "从明到清（191）/郑成功父子（193）/郑氏家族向日本乞师（195）/其他乞师（199）"
    )
    infer_toc_levels(entries)
    assign_toc_hierarchy(entries)

    assert [entry["display_title"] for entry in entries] == [
        "第九章 郑成功父子--唇齿之谊",
        "从明到清",
        "郑成功父子",
        "郑氏家族向日本乞师",
        "其他乞师",
    ]
    assert [entry["printed_start_page"] for entry in entries] == [191, 191, 193, 195, 199]
    assert [entry["level"] for entry in entries] == [1, 2, 2, 2, 2]
    assert [entry["parent_entry_index"] for entry in entries] == [None, 0, 0, 0, 0]


def test_select_monotonic_start_pages_prefers_shared_printed_page_offset() -> None:
    entries = [
        {"candidate_start_pages": [233, 15], "printed_start_page": 3},
        {"candidate_start_pages": [238, 27], "printed_start_page": 15},
        {"candidate_start_pages": [239, 43], "printed_start_page": 31},
    ]

    select_monotonic_start_pages(entries)

    assert [entry["selected_start_page"] for entry in entries] == [15, 27, 43]


def test_select_monotonic_start_pages_resets_printed_offset_at_role_boundary() -> None:
    entries = [
        {"candidate_start_pages": [24], "printed_start_page": 23, "role": "front_matter"},
        {"candidate_start_pages": [35], "printed_start_page": 1, "role": "body"},
    ]

    select_monotonic_start_pages(entries)

    assert [entry["selected_start_page"] for entry in entries] == [24, 35]


def test_select_monotonic_start_pages_prefers_exact_body_printed_offset() -> None:
    entries = [
        {"candidate_start_pages": [35], "printed_start_page": 1, "role": "body"},
        {"candidate_start_pages": [153, 152], "printed_start_page": 118, "role": "body"},
        {"candidate_start_pages": [173], "printed_start_page": 139, "role": "body"},
    ]

    select_monotonic_start_pages(entries)

    assert [entry["selected_start_page"] for entry in entries] == [35, 152, 173]


def test_select_monotonic_start_pages_keeps_unlocatable_entry_null() -> None:
    entries = [
        {"candidate_start_pages": [20]},
        {"candidate_start_pages": [10]},
    ]

    select_monotonic_start_pages(entries)

    assert [entry["selected_start_page"] for entry in entries] == [20, None]


def test_select_monotonic_start_pages_rejects_hundreds_page_printed_offset() -> None:
    entries = [{"candidate_start_pages": [233], "printed_start_page": 3}]

    select_monotonic_start_pages(entries)

    assert entries[0]["selected_start_page"] is None


def test_add_printed_page_offset_candidates_fills_ocr_missed_title_page() -> None:
    entries = [
        {
            "candidate_start_pages": [15],
            "printed_start_page": 3,
            "selected_start_page": 15,
            "role": "body",
        },
        {
            "candidate_start_pages": [],
            "printed_start_page": 15,
            "selected_start_page": None,
            "role": "body",
        },
        {
            "candidate_start_pages": [43],
            "printed_start_page": 31,
            "selected_start_page": 43,
            "role": "body",
        },
    ]

    add_printed_page_offset_candidates(entries, page_count=100)
    select_monotonic_start_pages(entries)

    assert entries[1]["candidate_start_pages"] == [27]
    assert [entry["selected_start_page"] for entry in entries] == [15, 27, 43]

    document = _printed_offset_document()
    skeleton = build_book_skeleton_from_observed(document)

    anchor = skeleton["toc_entries"][1]["selected_start_anchor"]
    assert anchor["resolution_method"] == "printed_page_offset"
    assert anchor["page"] == 27
    assert anchor["printed_page_offset"] == 12
    assert anchor["title_observation_ids"] == []
    assert anchor["supporting_anchor_ids"] == ["sa000000", "sa000002"]
    assert anchor["confidence"] == "medium"


def test_validate_book_skeleton_against_observed_rejects_unknown_offset_support() -> None:
    document = _printed_offset_document()
    skeleton = build_book_skeleton_from_observed(document)
    skeleton["toc_entries"][1]["selected_start_anchor"]["supporting_anchor_ids"] = [
        "sa000000",
        "sa999999",
    ]

    with pytest.raises(ValidationError, match="unknown supporting anchor"):
        canonical_api.validate_book_skeleton_against_observed(skeleton, document)


def test_validate_book_skeleton_against_observed_requires_straddling_offset_supports() -> None:
    document = _printed_offset_document()
    skeleton = build_book_skeleton_from_observed(document)
    skeleton["toc_entries"][1]["selected_start_anchor"]["supporting_anchor_ids"] = [
        "sa000000",
        "sa000001",
    ]

    with pytest.raises(ValidationError, match="offset supports must straddle"):
        canonical_api.validate_book_skeleton_against_observed(skeleton, document)


def test_validate_book_skeleton_against_observed_requires_agreed_offset_supports() -> None:
    document = _printed_offset_document()
    skeleton = build_book_skeleton_from_observed(document)
    skeleton["toc_entries"][2]["selected_start_anchor"]["printed_page_offset"] = 13

    with pytest.raises(ValidationError, match="offset supports do not agree"):
        canonical_api.validate_book_skeleton_against_observed(skeleton, document)


def _printed_offset_document() -> dict:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 50)]
    return make_observed_document(
        {
            "doc_id": "offset-sample",
            "title": "Offset Sample",
            "language": "zh-CN",
            "source_file": "offset-sample.pdf",
            "parser_name": "test-parser",
            "parser_mode": "structured",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n亚瑟 3\n主教座堂 15\n查理曼 31",
                page=1,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002", "text_region", text="亚瑟", page=15, role_hint="title_text"
            ),
            make_observation(
                "obs000003", "text_region", text="查理曼", page=43, role_hint="title_text"
            ),
        ],
    )


def test_llm_corrected_toc_title_retains_positional_printed_page_evidence() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 50)]
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n大行集结 5\n冲峰 15\n终章 25",
                page=1,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002", "text_region", text="大军集结", page=17, role_hint="title_text"
            ),
            make_observation(
                "obs000003", "text_region", text="冲锋", page=27, role_hint="body_text"
            ),
            make_observation(
                "obs000004", "text_region", text="终章", page=37, role_hint="title_text"
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(
        document,
        llm_toc_entries=[
            {
                "entry_index": 0,
                "display_title": "大军集结",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
            {
                "entry_index": 1,
                "display_title": "冲锋",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
            {
                "entry_index": 2,
                "display_title": "终章",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
        ],
        llm_model="qwen-test",
        llm_source="toc_image_llm",
    )

    assert [entry["selected_start_page"] for entry in skeleton["toc_entries"]] == [17, 27, 37]


def test_llm_toc_entries_retain_internal_printed_page_constraints() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 240)]
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n亚瑟／3\n主教座堂／15\n查理曼／31",
                page=1,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002", "text_region", text="亚瑟", page=15, role_hint="title_text"
            ),
            make_observation(
                "obs000003", "text_region", text="主教座堂", page=27, role_hint="title_text"
            ),
            make_observation(
                "obs000004", "text_region", text="查理曼", page=43, role_hint="title_text"
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="亚瑟\n主教座堂\n查理曼",
                page=233,
                role_hint="title_text",
            ),
            make_observation(
                "obs000006", "text_region", text="主教座堂", page=238, role_hint="title_text"
            ),
            make_observation(
                "obs000007", "text_region", text="查理曼", page=239, role_hint="title_text"
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(
        document,
        llm_toc_entries=[
            {
                "entry_index": 0,
                "display_title": "亚瑟",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
            {
                "entry_index": 1,
                "display_title": "主教座堂",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
            {
                "entry_index": 2,
                "display_title": "查理曼",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
        ],
        llm_model="qwen-test",
        llm_source="toc_image_llm",
    )

    assert [entry["selected_start_page"] for entry in skeleton["toc_entries"]] == [15, 27, 43]
