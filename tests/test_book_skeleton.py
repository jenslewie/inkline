from __future__ import annotations

from pathlib import Path

import pytest

from inkline.canonical import (
    BOOK_SKELETON_SCHEMA_NAME,
    BOOK_SKELETON_SCHEMA_VERSION,
    audit_book_skeleton,
    book_skeleton_toc_llm_prompt,
    build_book_skeleton_from_observed,
    make_observation,
    make_observed_document,
    make_observed_page,
    validate_book_skeleton,
)
from inkline.canonical.book_skeleton.toc_llm import normalize_llm_toc_entries
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
    assert "printed_start_page" not in skeleton["toc_entries"][0]
    assert "candidate_pages" not in skeleton["toc_entries"][0]
    assert "selected_page" not in skeleton["toc_entries"][0]
    for removed_field in ("raw_title", "title", "raw_label", "label"):
        assert removed_field not in skeleton["toc_entries"][0]
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}
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
    assert [entry["display_title"] for entry in skeleton["toc_entries"]][-3:] == [
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
    display_titles = [entry["display_title"] for entry in skeleton["toc_entries"]]

    assert "I 日本：从战国时代到世界强权 32 中国：衰落中的明王朝 213 有子名 “舍” 384 朝鲜：通向战利品的大道" not in display_titles
    assert display_titles == [
        "1 日本：从战国时代到世界强权",
        "2 中国：衰落中的明王朝",
        "3 有子名 “舍”",
        "4 朝鲜：通向战利品的大道",
    ]
    for entry in skeleton["toc_entries"]:
        assert "raw_label" not in entry
        assert "label" not in entry
        assert "title" not in entry
        assert "label_correction" not in entry["attrs"]
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}
    assert entries["1 日本：从战国时代到世界强权"]["selected_start_page"] == 32
    assert entries["2 中国：衰落中的明王朝"]["selected_start_page"] is None


def test_build_book_skeleton_from_observed_recovers_glued_multi_digit_numeric_labels() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 220)]
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
                    "8 北上汉城 1019 二十五条觉书 12810 朝鲜水师的反击 "
                    "137II 进军平壤 15612 黄海海权之争 "
                    "17213 “予观倭贼如蚁蚊耳” 18114 伏见城 191"
                ),
                page=26,
                role_hint="toc_text",
            ),
            *[
                make_observation(
                    f"obs{index:06d}",
                    "text_region",
                    text=title,
                    page=page,
                    role_hint="title_text",
                )
                for index, (title, page) in enumerate(
                    [
                        ("北上汉城", 128),
                        ("二十五条觉书", 155),
                        ("朝鲜水师的反击", 172),
                        ("进军平壤", 183),
                        ("黄海海权之争", 199),
                        ("“予观倭贼如蚁蚊耳”", 208),
                        ("伏见城", 218),
                    ],
                    start=2,
                )
            ],
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)

    assert [entry["display_title"] for entry in skeleton["toc_entries"]] == [
        "8 北上汉城",
        "9 二十五条觉书",
        "10 朝鲜水师的反击",
        "11 进军平壤",
        "12 黄海海权之争",
        "13 “予观倭贼如蚁蚊耳”",
        "14 伏见城",
    ]
    assert [entry["level"] for entry in skeleton["toc_entries"]] == [2] * 7


def test_build_book_skeleton_from_observed_preserves_toc_title_ellipsis() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 330)]
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
                    "21 与此同时，在马尼拉…… 300"
                    "22 “咨尔丰臣平秀吉……特封尔为日本国王” 303"
                ),
                page=27,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="与此同时，在马尼拉",
                page=326,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="“咨尔丰臣平秀吉……特封尔为日本国王”",
                page=329,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)

    assert [entry["display_title"] for entry in skeleton["toc_entries"]] == [
        "21 与此同时，在马尼拉……",
        "22 “咨尔丰臣平秀吉……特封尔为日本国王”",
    ]


def test_build_book_skeleton_from_observed_locates_titles_from_title_text_only() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 520)]
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
                text="目录\n第五部分 丁酉再乱 329\n24 水、雷、大灾难 331",
                page=27,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="正文中提到了第五部分丁酉再乱，但这里不是标题。",
                page=17,
                role_hint="body_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="第五部分\n丁酉再乱",
                page=355,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="24 水、雷、大灾难",
                page=357,
                role_hint="title_text",
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="第五部分 丁酉再乱",
                page=508,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)

    assert skeleton["toc_entries"][0]["candidate_start_pages"] == [355]
    assert skeleton["toc_entries"][0]["selected_start_page"] == 355
    assert skeleton["toc_entries"][1]["candidate_start_pages"] == [357]


def test_build_book_skeleton_from_observed_keeps_split_toc_lines_and_part_hierarchy() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 430)]
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
                text=(
                    "目录\n"
                    "第一部分 通往阿金库尔之路\n"
                    "引言\n"
                    "vii\n"
                    "致谢\n"
                    "xxi\n"
                    "说明\n"
                    "XXV\n"
                    "第一章 “正当继承权” 7\n"
                    "第二部分 阿金库尔远征\n"
                    "第九章 “顺风驶向法兰西” 173\n"
                    "第三部分 战后余波\n"
                    "第十六章 死亡名单 353"
                ),
                page=33,
                role_hint="toc_text",
            ),
            *[
                make_observation(
                    f"obs{index:06d}",
                    "text_region",
                    text=title,
                    page=page,
                    role_hint="title_text",
                )
                for index, (title, page) in enumerate(
                    [
                        ("引言", 13),
                        ("致谢", 27),
                        ("说明", 31),
                        ("第一部分\n通往阿金库尔之路", 35),
                        ("第一章\n“正当继承权”", 41),
                        ("第二部分\n阿金库尔远征", 205),
                        ("第九章\n“顺风驶向法兰西”", 215),
                        ("第三部分\n战后余波", 396),
                        ("第十六章\n死亡名单", 403),
                    ],
                    start=2,
                )
            ],
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}

    assert "致谢" in entries
    assert "说明" in entries
    assert "第一部分 通往阿金库尔之路" in entries
    assert "第二部分 阿金库尔远征" in entries
    assert "第三部分 战后余波" in entries
    assert entries["第一部分 通往阿金库尔之路"]["level"] == 1
    assert entries["第一章 “正当继承权”"]["level"] == 2
    assert entries["第一章 “正当继承权”"]["parent_entry_index"] == entries[
        "第一部分 通往阿金库尔之路"
    ]["entry_index"]
    assert entries["第九章 “顺风驶向法兰西”"]["parent_entry_index"] == entries[
        "第二部分 阿金库尔远征"
    ]["entry_index"]
    assert entries["第十六章 死亡名单"]["parent_entry_index"] == entries[
        "第三部分 战后余波"
    ]["entry_index"]


def test_build_book_skeleton_from_observed_assigns_chapter_subheading_hierarchy() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 500)]
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
                    "目录\n"
                    "第一章 启示预言的传统 001\n"
                    "犹太教和早期基督教的启示文学 001\n"
                    "中世纪欧洲的启示文学传统 017\n"
                    "002\n"
                    "/ 追寻千禧年\n"
                    "第五章 十字军运动的后果 …… 102\n"
                    "结论 373\n"
                    "附录 克伦威尔时期英格兰的自由灵：浮嚣派\n"
                    "与他们的文献 …… 381\n"
                    "注释 460"
                ),
                page=9,
                role_hint="toc_text",
            ),
            *[
                make_observation(
                    f"obs{index:06d}",
                    "text_region",
                    text=title,
                    page=page,
                    role_hint="title_text",
                )
                for index, (title, page) in enumerate(
                    [
                        ("第一章\n启示预言的传统", 25),
                        ("犹太教和早期基督教的启示文学", 25),
                        ("中世纪欧洲的启示文学传统", 41),
                        ("第五章\n十字军运动的后果", 126),
                        ("结论", 405),
                        ("附录\n克伦威尔时期英格兰的自由灵：浮嚣派\n与他们的文献", 413),
                        ("注释和参考书目", 491),
                        ("注释", 492),
                        ("第一章 启示预言的传统", 492),
                        ("犹太教和早期基督教的启示文学", 492),
                    ],
                    start=2,
                )
            ],
            make_observation(
                "obs000020",
                "footnote_region",
                text="12 Matthew xvi, 27 - 28 (= Luke ix, 27).",
                page=492,
                role_hint="reference_text",
            ),
            make_observation(
                "obs000021",
                "footnote_region",
                text="13 关于两个时期：Vulliaud, pp. 45 sq.。",
                page=492,
                role_hint="reference_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}

    assert entries["第一章 启示预言的传统"]["level"] == 1
    assert entries["犹太教和早期基督教的启示文学"]["level"] == 2
    assert entries["犹太教和早期基督教的启示文学"]["parent_entry_index"] == entries[
        "第一章 启示预言的传统"
    ]["entry_index"]
    assert entries["中世纪欧洲的启示文学传统"]["parent_entry_index"] == entries[
        "第一章 启示预言的传统"
    ]["entry_index"]
    assert "第五章 十字军运动的后果" in entries
    assert "/ 追寻千禧年 第五章 十字军运动的后果" not in entries
    assert entries["结论"]["level"] == 1
    assert "附录 克伦威尔时期英格兰的自由灵：浮嚣派与他们的文献" in entries
    assert entries["注释"]["selected_start_page"] == 492


def test_build_book_skeleton_from_observed_supports_topic_and_appendix_labels() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 950)]
    document = make_observed_document(
        {
            "doc_id": "egypt",
            "title": "埃及、希腊与罗马",
            "language": "zh-CN",
            "source_file": "egypt.pdf",
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
                    "专题 1 阿玛尔那信札 101\n"
                    "专题2 萨福与抒情诗 209\n"
                    "附录 1 关于人数的一个问题 433\n"
                    "viii 埃及、希腊与罗马\n"
                    "第13章 希波战争 262\n"
                    "第31章 早期基督教社群 753\n"
                    "第32章 君士坦丁及其后继者 780\n"
                    "古代地中海各文明年代图表 894\n"
                    "大事年表 895"
                ),
                page=12,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="专题1\n阿玛尔那信札",
                page=115,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="专题2\n萨福与抒情诗",
                page=222,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="附录1\n关于人数的一个问题",
                page=483,
                role_hint="title_text",
            ),
            make_observation(
                "obs000008",
                "text_region",
                text="第13章\n希波战争",
                page=274,
                role_hint="title_text",
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="第31章\n早期基督教社群",
                page=798,
                role_hint="title_text",
            ),
            make_observation(
                "obs000006",
                "text_region",
                text="早期基督教社群",
                page=809,
                role_hint="title_text",
            ),
            make_observation(
                "obs000007",
                "text_region",
                text="第32章\n君士坦丁及其后继者",
                page=825,
                role_hint="title_text",
            ),
            make_observation(
                "obs000009",
                "image_region",
                text="古代地中海各文明年代图表",
                page=939,
            ),
            make_observation(
                "obs000010",
                "text_region",
                text="大事年表①",
                page=940,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}

    assert "raw_label" not in entries["专题1 阿玛尔那信札"]
    assert "label" not in entries["专题1 阿玛尔那信札"]
    assert "title" not in entries["专题1 阿玛尔那信札"]
    assert "专题2 萨福与抒情诗" in entries
    assert "附录1 关于人数的一个问题" in entries
    assert "第13章 希波战争" in entries
    assert "viii 埃及、希腊与罗马 第13章 希波战争" not in entries
    assert entries["第31章 早期基督教社群"]["candidate_start_pages"][0] == 798
    assert entries["第31章 早期基督教社群"]["selected_start_page"] == 798
    assert entries["古代地中海各文明年代图表"]["candidate_start_pages"] == [939]
    assert entries["古代地中海各文明年代图表"]["selected_start_page"] == 939


def test_book_skeleton_rules_do_not_hardcode_sample_specific_titles() -> None:
    canonical_dir = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "inkline-canonical"
        / "src"
        / "inkline"
        / "canonical"
    )
    production_source = "\n".join(
        (canonical_dir / filename).read_text()
        for filename in ("book_skeleton/toc.py", "book_skeleton/pages.py")
    )

    assert "古代地中海各文明年代图表" not in production_source


def test_build_book_skeleton_from_observed_requires_title_evidence_for_short_titles() -> None:
    document = make_observed_document(
        {
            "doc_id": "short-title",
            "title": "Short Title",
            "language": "zh-CN",
            "source_file": "short.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 4)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\n致谢 1\n第一章 正文 3",
                page=1,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="作者在正文中表达了致谢，但这里不是章节标题。",
                page=2,
                role_hint="body_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="致谢",
                page=3,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}

    assert entries["致谢"]["candidate_start_pages"] == [3]
    assert entries["致谢"]["selected_start_page"] == 3


def test_build_book_skeleton_from_observed_regresses_silk_split_title_pages() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 325)]
    document = make_observed_document(
        {
            "doc_id": "silk",
            "title": "丝绸之路新史",
            "language": "zh-CN",
            "source_file": "silk.pdf",
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
                    "第一章 楼 兰：中亚的十字路口 29\n"
                    "第三章 高昌：胡汉交融之所 105\n"
                    "第五章 长安：丝路终点的国际都会 179\n"
                    "第七章 于阗：佛教、伊斯兰教的入疆通道 251\n"
                    "结论 中亚陆路的历史 295\n"
                    "丝绸之路主要地名中英古今对照表 / 304\n"
                    "译后记 / 308\n"
                    "出版后记 / 310"
                ),
                page=13,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="第一章",
                page=42,
                role_hint="body_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="楼兰",
                page=42,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="中亚的十字路口",
                page=42,
                role_hint="body_text",
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="第三章",
                page=118,
                role_hint="body_text",
            ),
            make_observation(
                "obs000006",
                "text_region",
                text="高昌",
                page=118,
                role_hint="title_text",
            ),
            make_observation(
                "obs000007",
                "text_region",
                text="胡汉交融之所",
                page=118,
                role_hint="body_text",
            ),
            make_observation(
                "obs000008",
                "text_region",
                text="第五章",
                page=192,
                role_hint="body_text",
            ),
            make_observation(
                "obs000009",
                "text_region",
                text="长安",
                page=192,
                role_hint="title_text",
            ),
            make_observation(
                "obs000010",
                "text_region",
                text="丝路终点的国际都会",
                page=192,
                role_hint="body_text",
            ),
            make_observation(
                "obs000011",
                "text_region",
                text="第七章",
                page=264,
                role_hint="body_text",
            ),
            make_observation(
                "obs000012",
                "text_region",
                text="于 真",
                page=264,
                role_hint="title_text",
            ),
            make_observation(
                "obs000013",
                "text_region",
                text="佛教、伊斯兰教的入疆通道",
                page=264,
                role_hint="body_text",
            ),
            make_observation(
                "obs000014",
                "text_region",
                text="结论",
                page=308,
                role_hint="title_text",
            ),
            make_observation(
                "obs000015",
                "text_region",
                text="中亚陆路的历史",
                page=308,
                role_hint="title_text",
            ),
            make_observation(
                "obs000016",
                "text_region",
                text="丝绸之路主要地名中英古今对照表",
                page=317,
                role_hint="title_text",
            ),
            make_observation(
                "obs000017",
                "text_region",
                text="译后记",
                page=321,
                role_hint="title_text",
            ),
            make_observation(
                "obs000018",
                "text_region",
                text="出版后记",
                page=323,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(
        document,
        llm_classification={
            "entry_roles": [
                {"entry_index": index, "role": "body"}
                for index in range(5)
            ]
            + [
                {"entry_index": 5, "role": "back_matter"},
                {"entry_index": 6, "role": "back_matter"},
                {"entry_index": 7, "role": "back_matter"},
            ]
        },
    )
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}

    assert entries["第一章 楼 兰：中亚的十字路口"]["selected_start_page"] == 42
    assert entries["第三章 高昌：胡汉交融之所"]["selected_start_page"] == 118
    assert entries["第五章 长安：丝路终点的国际都会"]["selected_start_page"] == 192
    assert entries["第七章 于阗：佛教、伊斯兰教的入疆通道"]["selected_start_page"] == 264
    assert entries["结论 中亚陆路的历史"]["level"] == 1
    assert entries["结论 中亚陆路的历史"]["parent_entry_index"] is None
    assert entries["丝绸之路主要地名中英古今对照表"]["level"] == 1
    assert entries["丝绸之路主要地名中英古今对照表"]["parent_entry_index"] is None
    assert entries["译后记"]["level"] == 1
    assert entries["译后记"]["parent_entry_index"] is None


def test_build_book_skeleton_from_observed_preserves_toc_labels_pages_and_hierarchy() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 90)]
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
                    "第一部分 东亚三国 1\n"
                    "I 日本：从战国时代到世界强权 3\n"
                    "2 中国：衰落中的明王朝 21\n"
                    "3 有子名 “舍” 38\n"
                    "4 朝鲜：通向战利品的大道 41\n"
                    "第二部分 战争前夜 57"
                ),
                page=26,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="第一部分\n东亚三国",
                page=28,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="日本：从战国时代到世界强权",
                page=30,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="中国：衰落中的明王朝",
                page=48,
                role_hint="title_text",
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="有子名 “舍”",
                page=65,
                role_hint="title_text",
            ),
            make_observation(
                "obs000006",
                "text_region",
                text="朝鲜：通向战利品的大道",
                page=68,
                role_hint="title_text",
            ),
            make_observation(
                "obs000007",
                "text_region",
                text="第二部分\n战争前夜",
                page=84,
                role_hint="title_text",
            ),
        ],
    )

    skeleton = build_book_skeleton_from_observed(document)
    entries = skeleton["toc_entries"]

    assert entries[0]["display_title"] == "第一部分 东亚三国"
    assert "printed_start_page" not in entries[0]
    assert entries[0]["level"] == 1
    assert entries[0]["parent_entry_index"] is None
    assert entries[1]["display_title"] == "1 日本：从战国时代到世界强权"
    assert "printed_start_page" not in entries[1]
    assert entries[1]["level"] == 2
    assert entries[1]["parent_entry_index"] == 0
    assert entries[2]["display_title"] == "2 中国：衰落中的明王朝"
    assert entries[2]["level"] == 2
    assert entries[2]["parent_entry_index"] == 0
    assert entries[5]["display_title"] == "第二部分 战争前夜"
    assert entries[5]["level"] == 1
    assert entries[5]["parent_entry_index"] is None


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
    entry = next(
        entry for entry in skeleton["toc_entries"] if entry["display_title"] == "第八章 大行集结"
    )

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


def test_book_skeleton_toc_llm_prompt_defines_output_field_contract() -> None:
    prompt = book_skeleton_toc_llm_prompt(
        {
            "mode": "toc_image_extraction",
            "toc_pages": [9],
            "expected_output": {"toc_entries": []},
        }
    )

    assert '"entry_index"' in prompt
    assert '"display_title"' in prompt
    assert '"parent_entry_index"' in prompt
    assert '"raw_title"' not in prompt
    assert '"title"' not in prompt
    assert '"raw_label"' not in prompt
    assert '"label"' not in prompt
    assert "level starts at 1" in prompt
    assert "front_matter" in prompt
    assert "body" in prompt
    assert "back_matter" in prompt
    assert "unknown" in prompt
    assert "Do not output physical PDF page numbers" in prompt
    assert "Do not insert spaces between Chinese characters inside names or words" in prompt
    assert "第一章 楼兰：中亚的十字路口" in prompt


def test_build_book_skeleton_from_observed_accepts_llm_toc_entries_as_structure_source() -> None:
    skeleton = build_book_skeleton_from_observed(
        _document(),
        llm_toc_entries=[
            {
                "entry_index": 0,
                "raw_title": "中文版序言",
                "title": "中文版序言",
                "display_title": "中文版序言",
                "raw_label": None,
                "label": None,
                "level": 1,
                "parent_entry_index": None,
                "role": "front_matter",
            },
            {
                "entry_index": 1,
                "raw_title": "序章",
                "title": "序章",
                "display_title": "序章",
                "raw_label": None,
                "label": None,
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
            {
                "entry_index": 2,
                "raw_title": "第一章 米兰达",
                "title": "米兰达",
                "display_title": "第一章 米兰达",
                "raw_label": "第一章",
                "label": "第一章",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
            {
                "entry_index": 3,
                "raw_title": "陌生后置材料",
                "title": "陌生后置材料",
                "display_title": "陌生后置材料",
                "raw_label": None,
                "label": None,
                "level": 1,
                "parent_entry_index": None,
                "role": "back_matter",
            },
        ],
        llm_model="qwen-test",
        llm_source="toc_image_llm",
    )

    assert [entry["display_title"] for entry in skeleton["toc_entries"]] == [
        "中文版序言",
        "序章",
        "第一章 米兰达",
        "陌生后置材料",
    ]
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}
    assert entries["第一章 米兰达"]["selected_start_page"] == 42
    assert entries["陌生后置材料"]["role"] == "back_matter"
    assert entries["陌生后置材料"]["level"] == 1
    assert entries["陌生后置材料"]["candidate_start_pages"] == []
    assert skeleton["boundaries"]["first_body_entry_index"] == 1
    assert skeleton["boundaries"]["first_body_page"] == 14
    assert skeleton["boundaries"]["first_back_matter_entry_index"] == 3
    assert skeleton["llm"]["used"] is True
    assert skeleton["llm"]["source"] == "toc_image_llm"


def test_normalize_llm_toc_entries_does_not_rewrite_display_title_content() -> None:
    entries = normalize_llm_toc_entries(
        [
            {
                "entry_index": 0,
                "display_title": "第一章 楼 兰：中亚的十字路口",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
            {
                "entry_index": 1,
                "display_title": "第二章 The Silk Road",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
        ]
    )

    assert entries[0]["display_title"] == "第一章 楼 兰：中亚的十字路口"
    assert entries[1]["display_title"] == "第二章 The Silk Road"


def test_build_book_skeleton_from_observed_preserves_llm_level_and_parent_for_unknown_matter_titles() -> None:
    skeleton = build_book_skeleton_from_observed(
        _document(),
        llm_toc_entries=[
            {
                "entry_index": 0,
                "raw_title": "第一章 米兰达",
                "title": "米兰达",
                "display_title": "第一章 米兰达",
                "raw_label": "第一章",
                "label": "第一章",
                "level": 1,
                "parent_entry_index": None,
                "role": "body",
            },
            {
                "entry_index": 1,
                "raw_title": "材料来源说明",
                "title": "材料来源说明",
                "display_title": "材料来源说明",
                "raw_label": None,
                "label": None,
                "level": 1,
                "parent_entry_index": None,
                "role": "back_matter",
            },
            {
                "entry_index": 2,
                "raw_title": "档案馆藏目录",
                "title": "档案馆藏目录",
                "display_title": "档案馆藏目录",
                "raw_label": None,
                "label": None,
                "level": 2,
                "parent_entry_index": 1,
                "role": "back_matter",
            },
        ],
        llm_source="toc_image_llm",
    )

    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}
    assert entries["材料来源说明"]["level"] == 1
    assert entries["材料来源说明"]["parent_entry_index"] is None
    assert entries["档案馆藏目录"]["level"] == 2
    assert entries["档案馆藏目录"]["parent_entry_index"] == 1


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

    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}
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
        entry
        for entry in skeleton["toc_entries"]
        if entry["display_title"] == "附录1 关于人数的一个问题"
    )

    assert entry["selected_start_page"] == 483


def test_build_book_skeleton_from_observed_recovers_ocr_missed_page_from_toc_offset() -> None:
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
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}

    assert entries["中世纪欧洲的启示文学传统"]["candidate_start_pages"] == [41]
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
    entries = {entry["display_title"]: entry for entry in skeleton["toc_entries"]}

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


def test_validate_book_skeleton_rejects_printed_start_page() -> None:
    skeleton = build_book_skeleton_from_observed(_document())
    skeleton["toc_entries"][0]["printed_start_page"] = "1"

    with pytest.raises(ValidationError, match="printed_start_page"):
        validate_book_skeleton(skeleton)


def test_validate_book_skeleton_rejects_unlocated_glued_toc_title() -> None:
    skeleton = build_book_skeleton_from_observed(_document())
    skeleton["toc_entries"][0]["display_title"] = (
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


def test_validate_book_skeleton_rejects_nonmonotonic_selected_start_pages() -> None:
    skeleton = build_book_skeleton_from_observed(_document())
    skeleton["toc_entries"][1]["candidate_start_pages"] = [42, 300]
    skeleton["toc_entries"][1]["selected_start_page"] = 300
    skeleton["toc_entries"][2]["candidate_start_pages"] = [42]
    skeleton["toc_entries"][2]["selected_start_page"] = 42

    with pytest.raises(ValidationError, match="monotonic"):
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


def test_audit_book_skeleton_does_not_report_internal_label_corrections() -> None:
    pages = [make_observed_page(page, width=1000, height=1400) for page in range(1, 40)]
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
                text="目录\n第一部分 东亚三国 1\nI 日本：从战国时代到世界强权 3",
                page=26,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="第一部分\n东亚三国",
                page=28,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="日本：从战国时代到世界强权",
                page=30,
                role_hint="title_text",
            ),
        ],
    )

    audit = audit_book_skeleton(build_book_skeleton_from_observed(document))

    assert "label_ocr_correction_count" not in audit["summary"]
    assert audit["issues"] == []
