from __future__ import annotations

import pytest

from inkline.canonical import (
    BOOK_SKELETON_SCHEMA_NAME,
    BOOK_SKELETON_SCHEMA_VERSION,
    audit_book_skeleton,
    build_book_skeleton_from_observed,
    make_observation,
    make_observed_document,
    make_observed_page,
    validate_book_skeleton,
)
from inkline.canonical.schema import ValidationError


def _document() -> dict:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 321)]
    observations = [
        make_observation(
            "obs000001",
            "text_region",
            text="目录\n前言 1\n序章 14\n第一章 米兰达 42\n结论 308\n丝绸之路主要地名中英古今对照表 317\n注释 319",
            page=10,
            role_hint="toc_text",
        ),
        make_observation(
            "obs000002",
            "text_region",
            text="前言",
            page=5,
            role_hint="title_text",
        ),
        make_observation(
            "obs000003",
            "text_region",
            text="序章",
            page=14,
            role_hint="title_text",
        ),
        make_observation(
            "obs000004",
            "text_region",
            text="第一章",
            page=42,
            role_hint="title_text",
        ),
        make_observation(
            "obs000005",
            "text_region",
            text="米兰达",
            page=42,
            role_hint="title_text",
        ),
        make_observation(
            "obs000006",
            "text_region",
            text="结论",
            page=308,
            role_hint="title_text",
        ),
        make_observation(
            "obs000007",
            "text_region",
            text="丝绸之路主要地名",
            page=317,
            role_hint="title_text",
        ),
        make_observation(
            "obs000008",
            "text_region",
            text="中英古今对照表",
            page=317,
            role_hint="title_text",
        ),
        make_observation(
            "obs000009",
            "text_region",
            text="正文中提到了注释这个词，但这不是注释章节标题。",
            page=80,
            role_hint="body_text",
        ),
        make_observation(
            "obs000010",
            "text_region",
            text="① 注释",
            page=319,
            role_hint="title_text",
        ),
    ]
    return make_observed_document(
        {
            "doc_id": "silk",
            "title": "丝绸之路新史",
            "language": "zh-CN",
            "source_file": "silk.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        observations,
    )


def test_build_book_skeleton_from_observed_uses_toc_titles_and_observed_title_pages() -> None:
    skeleton = build_book_skeleton_from_observed(_document())

    validate_book_skeleton(skeleton)
    assert skeleton["metadata"]["schema_name"] == BOOK_SKELETON_SCHEMA_NAME
    assert skeleton["metadata"]["schema_version"] == BOOK_SKELETON_SCHEMA_VERSION
    assert skeleton["toc_pages"] == [10]
    assert "printed_page" not in skeleton["toc_entries"][0]
    assert "candidate_pages" not in skeleton["toc_entries"][0]
    assert "selected_page" not in skeleton["toc_entries"][0]
    entries = {entry["title"]: entry for entry in skeleton["toc_entries"]}
    assert entries["第一章 米兰达"]["selected_start_page"] == 42
    assert entries["丝绸之路主要地名中英古今对照表"]["selected_start_page"] == 317
    assert entries["注释"]["candidate_start_pages"] == [319]
    assert skeleton["boundaries"]["first_body_page"] == 14


def test_build_book_skeleton_from_observed_includes_toc_continuation_pages() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 494)]
    document = make_observed_document(
        {
            "doc_id": "imjin",
            "title": "壬辰战争",
            "language": "zh-CN",
            "source_file": "imjin.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n新版序言 1\n第一部分 东亚三国 1\n第一章 日本 32",
                page=26,
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="第五部分 丁酉再乱 329\n第六部分 余波 421\n参考书目 441\n注释 455\n出版后记 493",
                page=27,
                role_hint="body_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="第一部分\n东亚三国",
                page=28,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="参考书目",
                page=467,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)

    assert skeleton["toc_pages"] == [26, 27]
    assert [entry["title"] for entry in skeleton["toc_entries"]][-3:] == [
        "参考书目",
        "注释",
        "出版后记",
    ]


def test_build_book_skeleton_from_observed_splits_glued_toc_entries() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 50)]
    document = make_observed_document(
        {
            "doc_id": "imjin",
            "title": "壬辰战争",
            "language": "zh-CN",
            "source_file": "imjin.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text=(
                    "目录\n"
                    "I 日本：从战国时代到世界强权 32 中国：衰落中的明王朝 "
                    "213 有子名 “舍” 384 朝鲜：通向战利品的大道 41"
                ),
                page=26,
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="日本：从战国时代到世界强权",
                page=32,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="中国：衰落中的明王朝",
                page=21,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="有子名 “舍”",
                page=38,
                role_hint="title_text",
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="朝鲜：通向战利品的大道",
                page=41,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    titles = [entry["title"] for entry in skeleton["toc_entries"]]

    assert "I 日本：从战国时代到世界强权 32 中国：衰落中的明王朝 213 有子名 “舍” 384 朝鲜：通向战利品的大道" not in titles
    assert titles == [
        "I 日本：从战国时代到世界强权",
        "中国：衰落中的明王朝",
        "有子名 “舍”",
        "朝鲜：通向战利品的大道",
    ]
    entries = {entry["title"]: entry for entry in skeleton["toc_entries"]}
    assert entries["I 日本：从战国时代到世界强权"]["selected_start_page"] == 32
    assert entries["中国：衰落中的明王朝"]["selected_start_page"] == 21


def test_build_book_skeleton_from_observed_ignores_note_headers_when_locating_titles() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 530)]
    document = make_observed_document(
        {
            "doc_id": "agincourt",
            "title": "阿金库尔战役",
            "language": "zh-CN",
            "source_file": "agincourt.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n第七章 金钱与人力 115\n第八章 大行集结 138",
                page=33,
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="第八章",
                page=172,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="大军集结",
                page=172,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "footnote_region",
                text="第八章 大行集结 相关注释很多很多。",
                page=522,
                role_hint="footnote_text",
            ),
            make_observation(
                "obs000005",
                "page_marker",
                text="第八章 大行集结",
                page=522,
                role_hint="header",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entry = next(entry for entry in skeleton["toc_entries"] if entry["title"] == "第八章 大行集结")

    assert entry["selected_start_page"] == 172
    assert 522 not in entry["candidate_start_pages"]


def test_build_book_skeleton_from_observed_accepts_llm_roles_but_not_llm_pages() -> None:
    skeleton = build_book_skeleton_from_observed(
        _document(),
        llm_classification={
            "entry_roles": [
                {"entry_index": 0, "role": "front_matter"},
                {"entry_index": 1, "role": "body"},
                {"entry_index": 2, "role": "body"},
                {"entry_index": 3, "role": "body"},
                {"entry_index": 4, "role": "back_matter"},
                {"entry_index": 5, "role": "back_matter", "page": 999},
            ],
            "first_body_entry_index": 1,
            "last_body_entry_index": 3,
            "first_back_matter_entry_index": 4,
            "uncertain_entries": [{"entry_index": 5, "title": "注释", "reason": "short title"}],
        },
        llm_model="qwen-test",
        llm_source="toc_llm",
    )

    assert skeleton["boundaries"]["first_body_entry_index"] == 1
    assert skeleton["boundaries"]["first_body_page"] == 14
    assert skeleton["boundaries"]["last_body_entry_index"] == 3
    assert skeleton["boundaries"]["last_body_page"] == 308
    assert skeleton["boundaries"]["first_back_matter_entry_index"] == 4
    assert skeleton["boundaries"]["first_back_matter_page"] == 317
    assert skeleton["llm"]["used"] is True
    assert skeleton["llm"]["model"] == "qwen-test"


def test_build_book_skeleton_from_observed_keeps_numbered_chapter_body_after_llm() -> None:
    skeleton = build_book_skeleton_from_observed(
        _document(),
        llm_classification={
            "entry_roles": [
                {"entry_index": 1, "role": "body"},
                {"entry_index": 2, "role": "back_matter"},
                {"entry_index": 3, "role": "body"},
                {"entry_index": 4, "role": "back_matter"},
                {"entry_index": 5, "role": "back_matter"},
            ],
            "first_body_entry_index": 1,
            "last_body_entry_index": 3,
            "first_back_matter_entry_index": 4,
        },
    )

    entries = {entry["title"]: entry for entry in skeleton["toc_entries"]}
    assert entries["第一章 米兰达"]["role"] == "body"
    assert skeleton["boundaries"]["first_back_matter_page"] == 317


def test_build_book_skeleton_from_observed_downranks_footnote_heavy_title_matches() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 570)]
    document = make_observed_document(
        {
            "doc_id": "agincourt",
            "title": "阿金库尔战役",
            "language": "zh-CN",
            "source_file": "agincourt.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n第十八章 胜利的奖赏 403\n附录 1 关于人数的一个问题 433",
                page=33,
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="附录1",
                page=483,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="关于人数的一个问题",
                page=483,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="附录正文。",
                page=483,
                role_hint="body_text",
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="附录1 关于人数的一个问题",
                page=559,
                role_hint="title_text",
            ),
            make_observation(
                "obs000006",
                "footnote_region",
                text="1. 这里是附录注释。",
                page=559,
                role_hint="footnote_text",
            ),
            make_observation(
                "obs000007",
                "footnote_region",
                text="2. 这里还是附录注释。",
                page=559,
                role_hint="footnote_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entry = next(
        entry for entry in skeleton["toc_entries"] if entry["title"] == "附录 1 关于人数的一个问题"
    )

    assert entry["selected_start_page"] == 483


def test_build_book_skeleton_from_observed_selects_monotonic_start_pages() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 540)]
    document = make_observed_document(
        {
            "doc_id": "millennium",
            "title": "追寻千禧年",
            "language": "zh-CN",
            "source_file": "millennium.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text=(
                    "目录\n第一章 启示预言的传统 1\n中世纪欧洲的启示文学传统 17\n"
                    "第二章 宗教异议的传统 28"
                ),
                page=9,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="第一章 启示预言的传统",
                page=25,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="中世纪欧洲的启示文学传统",
                page=41,
                role_hint="body_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="中世纪欧洲的启示文学传统",
                page=493,
                role_hint="title_text",
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="第二章 宗教异议的传统",
                page=52,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entries = {entry["title"]: entry for entry in skeleton["toc_entries"]}

    assert entries["中世纪欧洲的启示文学传统"]["candidate_start_pages"] == [493, 41]
    assert entries["中世纪欧洲的启示文学传统"]["selected_start_page"] == 41


def test_build_book_skeleton_from_observed_preserves_local_best_when_order_allows() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 60)]
    document = make_observed_document(
        {
            "doc_id": "agincourt",
            "title": "阿金库尔战役",
            "language": "zh-CN",
            "source_file": "agincourt.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        pages,
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n2015年版序言 1\n序言 13\n第一章 正当继承权 31",
                page=33,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="2015年版序言",
                page=9,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="序言",
                page=21,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="2015年版序言",
                page=9,
                role_hint="body_text",
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="第一章 正当继承权",
                page=41,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entries = {entry["title"]: entry for entry in skeleton["toc_entries"]}

    assert entries["序言"]["candidate_start_pages"] == [21, 9]
    assert entries["序言"]["selected_start_page"] == 21


def test_validate_book_skeleton_rejects_invalid_entry_role() -> None:
    skeleton = build_book_skeleton_from_observed(_document())
    skeleton["toc_entries"][0]["role"] = "cover"

    with pytest.raises(ValidationError, match="role"):
        validate_book_skeleton(skeleton)


def test_validate_book_skeleton_rejects_ambiguous_legacy_page_fields() -> None:
    skeleton = build_book_skeleton_from_observed(_document())
    skeleton["toc_entries"][0]["candidate_pages"] = [1]

    with pytest.raises(ValidationError, match="candidate_pages"):
        validate_book_skeleton(skeleton)


def test_validate_book_skeleton_rejects_unlocated_glued_toc_title() -> None:
    skeleton = build_book_skeleton_from_observed(_document())
    skeleton["toc_entries"][0]["title"] = (
        "I 日本：从战国时代到世界强权 32 中国：衰落中的明王朝 "
        "213 有子名 “舍” 384 朝鲜：通向战利品的大道"
    )
    skeleton["toc_entries"][0]["candidate_start_pages"] = []
    skeleton["toc_entries"][0]["selected_start_page"] = None

    with pytest.raises(ValidationError, match="glued TOC"):
        validate_book_skeleton(skeleton)


def test_validate_book_skeleton_rejects_selected_start_page_outside_candidates() -> None:
    skeleton = build_book_skeleton_from_observed(_document())
    skeleton["toc_entries"][0]["candidate_start_pages"] = [5]
    skeleton["toc_entries"][0]["selected_start_page"] = 99

    with pytest.raises(ValidationError, match="selected_start_page"):
        validate_book_skeleton(skeleton)


def test_validate_book_skeleton_rejects_non_contiguous_entry_roles() -> None:
    skeleton = build_book_skeleton_from_observed(_document())
    skeleton["toc_entries"][0]["role"] = "front_matter"
    skeleton["toc_entries"][1]["role"] = "body"
    skeleton["toc_entries"][2]["role"] = "back_matter"
    skeleton["toc_entries"][3]["role"] = "body"

    with pytest.raises(ValidationError, match="contiguous"):
        validate_book_skeleton(skeleton)


def test_audit_book_skeleton_reports_entry_level_quality_issues() -> None:
    skeleton = build_book_skeleton_from_observed(_document())
    skeleton["toc_entries"][0]["candidate_start_pages"] = []
    skeleton["toc_entries"][0]["selected_start_page"] = None
    skeleton["toc_entries"][1]["selected_start_page"] = 999
    skeleton["toc_entries"][2]["role"] = "back_matter"
    skeleton["toc_entries"][3]["role"] = "body"

    audit = audit_book_skeleton(skeleton)

    assert audit["summary"]["toc_entry_count"] == len(skeleton["toc_entries"])
    assert audit["summary"]["issue_count"] == 4
    assert {
        issue["issue_type"]
        for issue in audit["issues"]
    } == {
        "unlocated_entry",
        "selected_start_page_not_in_candidates",
        "non_monotonic_selected_start_page",
        "roles_not_contiguous",
    }


def test_audit_book_skeleton_reports_clean_summary_for_valid_skeleton() -> None:
    audit = audit_book_skeleton(build_book_skeleton_from_observed(_document()))

    assert audit["summary"]["issue_count"] == 0
    assert audit["summary"]["unlocated_entry_count"] == 0
    assert audit["issues"] == []
