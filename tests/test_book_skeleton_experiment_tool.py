from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from PIL import Image

from inkline.canonical.observed import make_observation, make_observed_document, make_observed_page


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "experiment_book_skeleton_inputs.py"
    spec = importlib.util.spec_from_file_location("experiment_book_skeleton_inputs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document() -> dict[str, Any]:
    return make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample Book",
            "language": "zh",
            "source_file": "sample.pdf",
            "parser_name": "test",
            "parser_mode": "shadow",
        },
        [
            make_observed_page(1, width=400, height=600),
            make_observed_page(2, width=400, height=600),
            make_observed_page(3, width=400, height=600),
            make_observed_page(4, width=400, height=600),
            make_observed_page(5, width=400, height=600),
        ],
        [
            make_observation(
                "obs1",
                "text_region",
                text="封面标题",
                page=1,
                bbox=[120, 100, 280, 180],
                role_hint="title_text",
            ),
            make_observation(
                "obs2",
                "text_region",
                text="目录 第一章 1 第二章 20",
                page=2,
                bbox=[60, 80, 340, 500],
                role_hint="toc_text",
            ),
            make_observation(
                "obs3",
                "text_region",
                text="第一章 正文开始。这是一段较长的正文内容。",
                page=3,
                bbox=[40, 80, 360, 520],
                role_hint="body_text",
            ),
            make_observation(
                "obs4",
                "image_region",
                page=4,
                bbox=[20, 20, 380, 560],
                role_hint="unknown",
            ),
            make_observation(
                "obs5",
                "text_region",
                text="ISBN 978-0-0000-0000-0",
                page=5,
                bbox=[60, 80, 340, 400],
                role_hint="reference_text",
            ),
        ],
    )


def _toc_document() -> dict[str, Any]:
    pages = [make_observed_page(page, width=400, height=600) for page in range(1, 13)]
    observations = [
        make_observation(
            "obs1",
            "text_region",
            text="封面",
            page=1,
            bbox=[80, 80, 320, 520],
            role_hint="title_text",
        ),
        make_observation(
            "obs2",
            "text_region",
            text="目录\n前言 1\n第一章 千年王国的期待 25\n附录 413\n注释和参考书目 491\n索引 568",
            page=2,
            bbox=[40, 80, 360, 500],
            role_hint="toc_text",
        ),
        make_observation(
            "obs3",
            "text_region",
            text="前言\n这是一段前言。",
            page=3,
            bbox=[60, 100, 340, 500],
            role_hint="title_text",
        ),
        make_observation(
            "obs4",
            "text_region",
            text="第一章 千年王国的期待\n正文开始。",
            page=5,
            bbox=[60, 100, 340, 500],
            role_hint="title_text",
        ),
        make_observation(
            "obs5",
            "text_region",
            text="附录\n补充材料。",
            page=8,
            bbox=[60, 100, 340, 500],
            role_hint="title_text",
        ),
        make_observation(
            "obs6",
            "text_region",
            text="注释和参考书目\n1 参考资料。",
            page=9,
            bbox=[60, 100, 340, 500],
            role_hint="title_text",
        ),
        make_observation(
            "obs7",
            "text_region",
            text="索引\n阿尔比派 32, 40",
            page=10,
            bbox=[60, 100, 340, 500],
            role_hint="title_text",
        ),
        make_observation(
            "obs8",
            "text_region",
            text="版权信息 ISBN 978-0-0000-0000-0",
            page=12,
            bbox=[60, 100, 340, 500],
            role_hint="reference_text",
        ),
    ]
    return make_observed_document(
        {
            "doc_id": "toc-sample",
            "title": "TOC Sample",
            "language": "zh",
            "source_file": "toc-sample.pdf",
            "parser_name": "test",
            "parser_mode": "shadow",
        },
        pages,
        observations,
    )


def _document_with_pages(
    *,
    doc_id: str,
    page_count: int,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    return make_observed_document(
        {
            "doc_id": doc_id,
            "title": doc_id,
            "language": "zh",
            "source_file": f"{doc_id}.pdf",
            "parser_name": "test",
            "parser_mode": "shadow",
        },
        [make_observed_page(page, width=400, height=600) for page in range(1, page_count + 1)],
        observations,
    )


def test_build_skeleton_evidence_uses_observed_document_not_nodes() -> None:
    tool = _load_tool()

    package = tool.build_skeleton_evidence_package(_document())

    assert package["metadata"]["doc_id"] == "sample"
    assert package["page_count"] == 5
    assert "nodes" not in json.dumps(package, ensure_ascii=False)
    assert package["pages"][1]["role_hint_counts"]["toc_text"] == 1


def test_candidate_pages_include_structural_and_visual_signals() -> None:
    tool = _load_tool()

    package = tool.build_skeleton_evidence_package(_document())
    candidates = {item["page"]: item["signals"] for item in package["candidate_pages"]}

    assert "toc_hint" in candidates[2]
    assert "visual_content" in candidates[4]
    assert "late_page" in candidates[5]


def test_cli_writes_three_input_modes(tmp_path) -> None:
    tool = _load_tool()
    observed_path = tmp_path / "observed.json"
    output_dir = tmp_path / "out"
    observed_path.write_text(json.dumps(_document(), ensure_ascii=False), encoding="utf-8")

    exit_code = tool.main(
        [
            "--book",
            "sample",
            "--observed",
            str(observed_path),
            "--output-dir",
            str(output_dir),
            "--no-render-images",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "sample" / "observed_only" / "input.json").exists()
    assert (output_dir / "sample" / "hybrid" / "input.json").exists()
    assert (output_dir / "sample" / "pdf_image_only" / "input.json").exists()
    assert (output_dir / "sample" / "toc_driven" / "input.json").exists()
    assert (output_dir / "sample" / "toc_llm" / "input.json").exists()


def test_observed_only_input_is_compressed_for_llm() -> None:
    tool = _load_tool()

    package = tool.build_skeleton_evidence_package(_document())
    observed_input = tool.build_observed_only_input(package)

    assert "pages" not in observed_input
    assert observed_input["page_signal_index"][0] == {"page": 1, "signals": ["early_page", "first_page", "title_hint"]}
    assert {item["page"] for item in observed_input["evidence_pages"]} >= {1, 2, 4, 5}


def test_contact_sheets_group_rendered_page_images(tmp_path) -> None:
    tool = _load_tool()
    image_paths = []
    for page in range(1, 4):
        path = tmp_path / f"page_{page:04d}.png"
        Image.new("RGB", (40, 60), color=(255, 255, 255)).save(path)
        image_paths.append({"page": page, "image_path": str(path)})

    sheets = tool.make_contact_sheets(image_paths, tmp_path / "sheets", pages_per_sheet=2)

    assert [sheet["pages"] for sheet in sheets] == [[1, 2], [3]]
    assert all(Path(sheet["image_path"]).exists() for sheet in sheets)


def test_parse_llm_json_content_extracts_wrapped_json() -> None:
    tool = _load_tool()

    parsed = tool.parse_llm_json_content('Here is the result: {"body_ranges": []}')

    assert parsed == {"body_ranges": []}


def test_parse_llm_json_content_preserves_parse_failures_for_audit() -> None:
    tool = _load_tool()

    parsed = tool.parse_llm_json_content("")

    assert parsed["_parse_error"] == "llm_response_not_json"
    assert parsed["_raw_content"] == ""


def test_run_llm_modes_records_mode_errors_and_continues(tmp_path, monkeypatch) -> None:
    tool = _load_tool()
    book_dir = tmp_path / "book"
    for mode in ("observed_only", "hybrid"):
        mode_dir = book_dir / mode
        mode_dir.mkdir(parents=True)
        (mode_dir / "prompt.md").write_text("prompt", encoding="utf-8")
        (mode_dir / "input.json").write_text("{}", encoding="utf-8")

    calls = []

    def fake_chat_json_raw(config, *, prompt, image_paths):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return {"ok": True}, '{"ok": true}'

    monkeypatch.setattr(tool, "_chat_json_raw", fake_chat_json_raw)

    results = tool.run_llm_modes(
        book_dir,
        modes=["observed_only", "hybrid"],
        model="test",
        api_url="http://example.invalid",
        timeout_seconds=1,
    )

    first = json.loads((book_dir / "observed_only" / "skeleton_proposal.json").read_text())
    second = json.loads((book_dir / "hybrid" / "skeleton_proposal.json").read_text())
    assert first["_llm_error"] == "boom"
    assert (book_dir / "observed_only" / "llm_raw_response.txt").read_text() == ""
    assert second == {"ok": True}
    assert results["observed_only"]["status"] == "error"
    assert results["hybrid"]["status"] == "written"


def test_detect_toc_pages_uses_toc_text_and_table_of_contents_shape() -> None:
    tool = _load_tool()
    package = tool.build_skeleton_evidence_package(_toc_document())

    assert tool.detect_toc_pages(package) == [2]


def test_detect_toc_pages_ignores_copyright_and_late_index_like_pages() -> None:
    tool = _load_tool()
    document = make_observed_document(
        {
            "doc_id": "toc-negative",
            "title": "TOC Negative",
            "language": "zh",
            "source_file": "toc-negative.pdf",
            "parser_name": "test",
            "parser_mode": "shadow",
        },
        [make_observed_page(page, width=400, height=600) for page in range(1, 101)],
        [
            make_observation(
                "copyright",
                "text_region",
                text="Copyright 2020\nISBN 978-7-0000-0000-0\n装帧制造 1266\n投稿服务 2326",
                page=4,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation(
                "toc",
                "text_region",
                text="目录\n前言 1\n第一章 正文 9\n附录 80",
                page=8,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation(
                "index",
                "text_region",
                text="阿尔比派 32, 40\n鲍德温 68, 70\n采邑 100, 101\n大公会议 120",
                page=98,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
        ],
    )

    package = tool.build_skeleton_evidence_package(document)

    assert tool.detect_toc_pages(package) == [8]


def test_detect_toc_pages_includes_front_toc_continuation_pages() -> None:
    tool = _load_tool()
    document = make_observed_document(
        {
            "doc_id": "toc-continuation",
            "title": "TOC Continuation",
            "language": "zh",
            "source_file": "toc-continuation.pdf",
            "parser_name": "test",
            "parser_mode": "shadow",
        },
        [make_observed_page(page, width=400, height=600) for page in range(1, 8)],
        [
            make_observation(
                "toc-1",
                "text_region",
                text="目录\n前言 1\n第一章 正文 9\n第二章 继续 20",
                page=2,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation(
                "toc-2",
                "text_region",
                text="第三章 后续 30\n附录 80\n索引 90",
                page=3,
                bbox=[40, 80, 360, 500],
                role_hint="body_text",
            ),
            make_observation(
                "body-list",
                "text_region",
                text="第一节 1\n第二节 2\n第三节 3",
                page=6,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
        ],
    )

    package = tool.build_skeleton_evidence_package(document)

    assert tool.detect_toc_pages(package) == [2, 3]


def test_parse_toc_entries_extracts_titles_and_roles() -> None:
    tool = _load_tool()
    toc_text = "目录\n前言 1\n第一章 千年王国的期待 25\n附录 413\n注释和参考书目 491\n索引 568"

    entries = tool.parse_toc_entries(toc_text)

    assert entries == [
        {"title": "前言", "printed_page": "1", "role": "front_matter"},
        {"title": "第一章 千年王国的期待", "printed_page": "25", "role": "body"},
        {"title": "附录", "printed_page": "413", "role": "back_matter"},
        {"title": "注释和参考书目", "printed_page": "491", "role": "back_matter"},
        {"title": "索引", "printed_page": "568", "role": "back_matter"},
    ]


def test_parse_toc_entries_ignores_standalone_page_labels_and_publication_noise() -> None:
    tool = _load_tool()
    toc_text = "目录\n目录 / 003\n引言\nvii\nPOST WAVE PUBLISHING CONSULTING 2022\n第一章 正文 7"

    entries = tool.parse_toc_entries(toc_text)

    assert entries == [
        {"title": "第一章 正文", "printed_page": "7", "role": "body"},
    ]


def test_parse_toc_entries_joins_wrapped_title_lines() -> None:
    tool = _load_tool()
    toc_text = "结论 373\n附录 克伦威尔时期英格兰的自由灵：浮嚣派\n与他们的文献 …… 381\n注释 460"

    entries = tool.parse_toc_entries(toc_text)

    assert entries == [
        {"title": "结论", "printed_page": "373", "role": "body"},
        {
            "title": "附录 克伦威尔时期英格兰的自由灵：浮嚣派 与他们的文献",
            "printed_page": "381",
            "role": "back_matter",
        },
        {"title": "注释", "printed_page": "460", "role": "back_matter"},
    ]


def test_toc_llm_input_uses_full_toc_page_text() -> None:
    tool = _load_tool()
    long_tail = "第二章 " + "很长的标题" * 80 + " 20"
    document = _document_with_pages(
        doc_id="full-toc-text",
        page_count=3,
        observations=[
            make_observation(
                "toc",
                "text_region",
                text=f"目录\n第一章 开始 1\n{long_tail}",
                page=1,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation("body", "text_region", text="第一章 开始", page=2, bbox=[40, 80, 360, 500]),
        ],
    )

    input_data = tool.build_toc_llm_input(document)

    assert long_tail in input_data["toc_text_pages"][0]["text"]


def test_build_toc_driven_skeleton_plan_locates_entry_pages_and_residuals() -> None:
    tool = _load_tool()

    plan = tool.build_toc_driven_skeleton_plan(_toc_document())

    assert plan["toc_pages"] == [2]
    located = {entry["title"]: entry["candidate_pages"] for entry in plan["toc_entries"]}
    assert located["前言"] == [3]
    assert located["第一章 千年王国的期待"] == [5]
    assert located["附录"] == [8]
    assert located["注释和参考书目"] == [9]
    assert located["索引"] == [10]
    assert plan["body_start_candidates"] == [5]
    assert plan["back_matter_start_candidates"] == [8]
    assert plan["llm_page_tasks"] == [
        {"page": 1, "task": "classify_residual_front_page"},
        {"page": 3, "task": "verify_toc_entry_page", "title": "前言", "role": "front_matter"},
        {
            "page": 5,
            "task": "verify_toc_entry_page",
            "title": "第一章 千年王国的期待",
            "role": "body",
        },
        {"page": 8, "task": "verify_toc_entry_page", "title": "附录", "role": "back_matter"},
        {
            "page": 9,
            "task": "verify_toc_entry_page",
            "title": "注释和参考书目",
            "role": "back_matter",
        },
        {"page": 10, "task": "verify_toc_entry_page", "title": "索引", "role": "back_matter"},
        {"page": 11, "task": "classify_residual_back_page"},
        {"page": 12, "task": "classify_residual_back_page"},
    ]


def test_toc_llm_input_uses_toc_text_without_rule_roles() -> None:
    tool = _load_tool()

    input_data = tool.build_toc_llm_input(_toc_document())

    assert input_data["mode"] == "toc_llm"
    assert input_data["toc_pages"] == [2]
    assert input_data["toc_text_pages"] == [
        {
            "page": 2,
            "text": "目录\n前言 1\n第一章 千年王国的期待 25\n附录 413\n注释和参考书目 491\n索引 568",
        }
    ]
    assert input_data["toc_entries"] == [
        {"entry_index": 0, "title": "前言", "printed_page": "1", "candidate_pages": [3]},
        {
            "entry_index": 1,
            "title": "第一章 千年王国的期待",
            "printed_page": "25",
            "candidate_pages": [5],
        },
        {"entry_index": 2, "title": "附录", "printed_page": "413", "candidate_pages": [8]},
        {
            "entry_index": 3,
            "title": "注释和参考书目",
            "printed_page": "491",
            "candidate_pages": [9],
        },
        {"entry_index": 4, "title": "索引", "printed_page": "568", "candidate_pages": [10]},
    ]
    assert "role" not in input_data["toc_entries"][0]
    assert input_data["expected_output"] == {
        "entry_roles": [
            {
                "entry_index": 0,
                "role": "front_matter|body|back_matter",
            }
        ],
        "first_body_entry_index": 0,
        "first_body_entry_title": "",
        "last_body_entry_index": 0,
        "last_body_entry_title": "",
        "first_back_matter_entry_index": None,
        "first_back_matter_entry_title": None,
        "uncertain_entries": [{"entry_index": 0, "title": "", "reason": ""}],
    }


def test_toc_llm_prompt_requests_toc_only_classification() -> None:
    tool = _load_tool()
    input_data = tool.build_toc_llm_input(_toc_document())

    prompt = tool._toc_llm_prompt(input_data)

    assert "Use only the table of contents" in prompt
    assert "Do not classify TOC entries with hard-coded title word lists" in prompt
    assert "first_body_entry_index" in prompt
    assert "INPUT_JSON:" in prompt


def test_toc_driven_skeleton_plan_does_not_verify_every_body_chapter() -> None:
    tool = _load_tool()
    document = make_observed_document(
        {
            "doc_id": "body-chapters",
            "title": "Body Chapters",
            "language": "zh",
            "source_file": "body-chapters.pdf",
            "parser_name": "test",
            "parser_mode": "shadow",
        },
        [make_observed_page(page, width=400, height=600) for page in range(1, 8)],
        [
            make_observation(
                "toc",
                "text_region",
                text="目录\n前言 1\n第一章 开始 9\n第二章 后续 20\n附录 30",
                page=1,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation("front", "text_region", text="前言", page=2, bbox=[40, 80, 360, 500]),
            make_observation("ch1", "text_region", text="第一章 开始", page=3, bbox=[40, 80, 360, 500]),
            make_observation("ch2", "text_region", text="第二章 后续", page=5, bbox=[40, 80, 360, 500]),
            make_observation("app", "text_region", text="附录", page=7, bbox=[40, 80, 360, 500]),
        ],
    )

    plan = tool.build_toc_driven_skeleton_plan(document)

    assert plan["body_start_candidates"] == [3]
    assert plan["llm_page_tasks"] == [
        {"page": 2, "task": "verify_toc_entry_page", "title": "前言", "role": "front_matter"},
        {"page": 3, "task": "verify_toc_entry_page", "title": "第一章 开始", "role": "body"},
        {"page": 7, "task": "verify_toc_entry_page", "title": "附录", "role": "back_matter"},
    ]


def test_toc_driven_skeleton_plan_skips_index_continuation_pages_before_residual_back() -> None:
    tool = _load_tool()
    document = make_observed_document(
        {
            "doc_id": "index-continuation",
            "title": "Index Continuation",
            "language": "zh",
            "source_file": "index-continuation.pdf",
            "parser_name": "test",
            "parser_mode": "shadow",
        },
        [make_observed_page(page, width=400, height=600) for page in range(1, 10)],
        [
            make_observation(
                "toc",
                "text_region",
                text="目录\n第一章 正文 1\n索引 100",
                page=1,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation("body", "text_region", text="第一章 正文", page=2, bbox=[40, 80, 360, 500]),
            make_observation("index-title", "text_region", text="索引", page=5, bbox=[40, 80, 360, 500]),
            make_observation(
                "index-1",
                "text_region",
                text="阿尔比派 32, 40\n鲍德温 68, 70\n采邑 100, 101",
                page=6,
                bbox=[40, 80, 360, 500],
            ),
            make_observation("index-header", "text_region", text="索引/101", page=7, bbox=[40, 80, 360, 500]),
            make_observation(
                "index-2",
                "text_region",
                text="大公会议 120, 122\n额我略 188, 190\n方济各会 201, 203",
                page=8,
                bbox=[40, 80, 360, 500],
            ),
            make_observation("cover-back", "text_region", text="ISBN 978 条形码 定价", page=9, bbox=[40, 80, 360, 500]),
        ],
    )

    plan = tool.build_toc_driven_skeleton_plan(document)

    assert plan["llm_page_tasks"] == [
        {"page": 2, "task": "verify_toc_entry_page", "title": "第一章 正文", "role": "body"},
        {"page": 5, "task": "verify_toc_entry_page", "title": "索引", "role": "back_matter"},
        {"page": 9, "task": "classify_residual_back_page"},
    ]


def test_toc_driven_skeleton_plan_treats_named_gazetteer_as_back_matter_start() -> None:
    tool = _load_tool()
    assert "对照表" not in tool.BACK_MATTER_TITLE_KEYWORDS
    document = _document_with_pages(
        doc_id="silk-like",
        page_count=324,
        observations=[
            make_observation(
                "toc",
                "text_region",
                text="目录\n第一章 正文 1\n丝绸之路主要地名中英古今对照表 304\n译后记 308\n出版后记 310",
                page=13,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation("body", "text_region", text="第一章 正文", page=14, bbox=[40, 80, 360, 500]),
            make_observation(
                "gazetteer",
                "text_region",
                text="丝绸之路主要地名中英古今对照表\n张湛",
                page=317,
                bbox=[40, 80, 360, 500],
                role_hint="title_text",
            ),
            make_observation("afterword", "text_region", text="译后记", page=321, bbox=[40, 80, 360, 500]),
        ],
    )

    plan = tool.build_toc_driven_skeleton_plan(document)

    located = {entry["title"]: entry for entry in plan["toc_entries"]}
    assert located["丝绸之路主要地名中英古今对照表"]["role"] == "back_matter"
    assert located["丝绸之路主要地名中英古今对照表"]["candidate_pages"] == [317]
    assert plan["back_matter_start_candidates"] == [317]


def test_toc_driven_skeleton_plan_infers_missing_back_matter_pages_from_printed_offsets() -> None:
    tool = _load_tool()
    assert "关于日期的说明" not in tool.FRONT_MATTER_TITLE_KEYWORDS
    document = _document_with_pages(
        doc_id="imjin-like",
        page_count=520,
        observations=[
            make_observation(
                "toc-1",
                "text_region",
                text="目录\n新版序言 1\n前言 3\n关于日期的说明 6\n第一部分 东亚三国 1",
                page=26,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation(
                "toc-2",
                "text_region",
                text="30 战争之后 423\n参考书目 441\n注释 455\n出版后记 493",
                page=27,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation(
                "date-note",
                "text_region",
                text="关于日期的说明\n本书日期说明。",
                page=25,
                bbox=[40, 80, 360, 500],
                role_hint="title_text",
            ),
            make_observation(
                "part",
                "text_region",
                text="第一部分\n东亚三国",
                page=28,
                bbox=[40, 80, 360, 500],
                role_hint="title_text",
            ),
            make_observation("chapter-30", "text_region", text="30 战争之后", page=449, bbox=[40, 80, 360, 500]),
            make_observation("afterword", "text_region", text="出版后记", page=519, bbox=[40, 80, 360, 500]),
        ],
    )

    plan = tool.build_toc_driven_skeleton_plan(document)

    located = {entry["title"]: entry for entry in plan["toc_entries"]}
    assert located["关于日期的说明"]["role"] == "front_matter"
    assert located["第一部分 东亚三国"]["candidate_pages"] == [28]
    assert located["30 战争之后"]["role"] == "body"
    assert located["参考书目"]["candidate_pages"] == [467]
    assert located["注释"]["candidate_pages"] == [481]
    assert plan["body_start_candidates"][0] == 28
    assert plan["back_matter_start_candidates"] == [467]


def test_toc_driven_skeleton_plan_uses_unpaged_body_part_title_as_body_start() -> None:
    tool = _load_tool()
    document = _document_with_pages(
        doc_id="agincourt-like",
        page_count=580,
        observations=[
            make_observation(
                "toc-1",
                "text_region",
                text="目录\n2015年版序言 iii\n引言 vii\n第一部分 通往阿金库尔之路\n第一章 “正当继承权” 7",
                page=33,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation(
                "toc-2",
                "text_region",
                text="第二部分 阿金库尔远征\n附录 1 关于人数的一个问题 433\n注释 455\n参考文献 515",
                page=34,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation(
                "part",
                "text_region",
                text="第一部分\n通往阿金库尔之路",
                page=35,
                bbox=[40, 80, 360, 500],
                role_hint="title_text",
            ),
            make_observation(
                "chapter",
                "text_region",
                text="第一章\n“正当继承权”",
                page=41,
                bbox=[40, 80, 360, 500],
                role_hint="title_text",
            ),
        ],
    )

    plan = tool.build_toc_driven_skeleton_plan(document)

    located = {entry["title"]: entry for entry in plan["toc_entries"]}
    assert located["第一部分 通往阿金库尔之路"]["candidate_pages"] == [35]
    assert plan["body_start_candidates"][0] == 35


def test_toc_driven_skeleton_plan_prefers_true_note_title_over_running_header() -> None:
    tool = _load_tool()
    document = _document_with_pages(
        doc_id="millennium-like",
        page_count=584,
        observations=[
            make_observation(
                "toc",
                "text_region",
                text="目录\n第一章 正文 25\n与他们的文献 381\n注释 460\n参考书目 508\n索引 536",
                page=9,
                bbox=[40, 80, 360, 500],
                role_hint="toc_text",
            ),
            make_observation("body", "text_region", text="第一章 正文", page=25, bbox=[40, 80, 360, 500]),
            make_observation(
                "appendix-like",
                "text_region",
                text="附录 克伦威尔时期英格兰的自由灵：浮嚣派与他们的文献",
                page=413,
                bbox=[40, 80, 360, 500],
                role_hint="title_text",
            ),
            make_observation(
                "notes-title",
                "text_region",
                text="注释\n12 Matthew...",
                page=492,
                bbox=[40, 80, 360, 500],
                role_hint="title_text",
            ),
            make_observation(
                "notes-header",
                "text_region",
                text="注释 /461\n中世纪欧洲的启示文学传统...",
                page=493,
                bbox=[40, 80, 360, 500],
            ),
        ],
    )

    plan = tool.build_toc_driven_skeleton_plan(document)

    located = {entry["title"]: entry for entry in plan["toc_entries"]}
    assert located["与他们的文献"]["role"] == "body"
    assert located["注释"]["candidate_pages"][0] == 492
    assert plan["back_matter_start_candidates"] == [492]
