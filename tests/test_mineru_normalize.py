from __future__ import annotations

import json
import os
from pathlib import Path

import inkline.parsers.mineru.bridge as mineru_bridge
from inkline.canonical import BLOCK_TYPES, validate_document
from inkline.llm import DEFAULT_QWEN_MODEL
from inkline.parse import ParseRequest
from inkline.parsers.mineru import normalize_mineru_outputs
from inkline.parsers.mineru.bridge import MinerUParser


def _text_item(raw_type: str, text: str, bbox: list[int]) -> dict:
    key = "title_content" if raw_type == "title" else "paragraph_content"
    return {"type": raw_type, "content": {key: [{"type": "text", "content": text}]}, "bbox": bbox}


def _image_item(bbox: list[int]) -> dict:
    return {
        "type": "image",
        "content": {"image_source": {"path": "images/sample.jpg"}, "content": ""},
        "bbox": bbox,
    }


def _chart_item(text: str, bbox: list[int]) -> dict:
    return {
        "type": "chart",
        "sub_type": "state_timeline",
        "content": {"image_source": {"path": "images/chart.jpg"}, "content": text},
        "bbox": bbox,
    }


def _table_item(html: str, bbox: list[int]) -> dict:
    return {
        "type": "table",
        "content": {"html": html},
        "bbox": bbox,
    }


def test_normalize_mineru_outputs_produces_valid_canonical(tmp_path) -> None:
    content_list_v2 = tmp_path / "sample_content_list_v2.json"
    middle = tmp_path / "sample_middle.json"
    model = tmp_path / "sample_model.json"
    output = tmp_path / "canonical.json"
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    {
                        "type": "paragraph",
                        "bbox": [100, 100, 900, 180],
                        "content": {"text": "A minimal MinerU paragraph."},
                    }
                ]
            ]
        ),
        encoding="utf-8",
    )
    middle.write_text(
        json.dumps({"pdf_info": [{"page_size": [1000, 1400]}]}),
        encoding="utf-8",
    )
    model.write_text("{}", encoding="utf-8")

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        model=model,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="sample",
        title="Sample",
        language="en",
        mineru_version="3.2.3",
        mineru_vl_utils_version="1.0.4",
        vlm_model={
            "local_path": "/cache/MinerU2.5-Pro-2605-1.2B",
            "model_name": "MinerU2.5-Pro-2605-1.2B",
            "model_type": "qwen2_vl",
            "architectures": ["Qwen2VLForConditionalGeneration"],
        },
        marker_locator_repair=False,
    )

    validate_document(document)
    assert {block["type"] for block in document["blocks"]} <= BLOCK_TYPES
    assert document["metadata"]["parser_name"] == "mineru"
    assert document["metadata"]["schema_version"] == "1.0"
    source_files = document["metadata"]["source_files"]
    assert document["metadata"]["source_file"] == "sample_content_list_v2.json"
    assert source_files["content_list_v2"] == "sample_content_list_v2.json"
    assert source_files["middle"] == "sample_middle.json"
    assert "model" not in source_files
    assert "md" not in source_files
    assert all(not Path(path).is_absolute() for path in source_files.values())
    assert document["metadata"]["mineru"]["version"] == "3.2.3"
    assert document["metadata"]["mineru"]["vlm_model"]["model_name"] == "MinerU2.5-Pro-2605-1.2B"
    assert document["metadata"]["mineru"]["vlm_model"]["local_path"] == os.path.relpath(
        "/cache/MinerU2.5-Pro-2605-1.2B", tmp_path
    )
    marker_config = document["metadata"]["mineru"]["auxiliary_ocr"]["qwen_marker_locator"]
    assert marker_config["enabled"] is False
    assert marker_config["model"] == DEFAULT_QWEN_MODEL
    assert marker_config["page_dpi"] == 150
    assert marker_config["block_dpi"] == 200
    assert output.exists()
    report_path = tmp_path / "canonical_note_ref_gaps.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["canonical"] == "canonical.json"
    assert report["summary"]["missing_body_ref_notes"] == 0


def test_small_pdf_page_size_uses_content_coordinate_layout(tmp_path) -> None:
    content_list_v2 = tmp_path / "imjin_style_content_list_v2.json"
    middle = tmp_path / "imjin_style_middle.json"
    output = tmp_path / "canonical.json"
    body_text = "1543年9月23日，一艘大型中国帆船出现在种子岛海岸附近。" * 4
    page_20 = [
        _text_item("title", "1", [508, 120, 531, 139]),
        _text_item("title", "日本：从战国时代到世界强权", [265, 163, 778, 192]),
        _text_item("paragraph", body_text, [148, 327, 891, 430]),
        _text_item(
            "paragraph", "这群外来者的首领，是一个叫五峰的中国人。" * 5, [148, 438, 891, 597]
        ),
        _text_item(
            "paragraph", "随后，长者告诉他们，岛上最大的城镇是赤荻。" * 4, [148, 717, 891, 791]
        ),
    ]
    content_list_v2.write_text(json.dumps([[] for _ in range(19)] + [page_20]), encoding="utf-8")
    middle.write_text(
        json.dumps({"pdf_info": [{"page_size": [425, 680]} for _ in range(20)]}),
        encoding="utf-8",
    )

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="imjin-style",
        title="壬辰战争",
        language="zh-CN",
    )

    layout_stats = document["metadata"]["mineru"]["layout_stats"]
    assert layout_stats["page_width"] == 1000.0
    assert layout_stats["page_height"] == 1000.0
    assert layout_stats["body_right"] <= layout_stats["page_width"]
    page_blocks = [
        block for block in document["blocks"] if (block.get("source") or {}).get("page") == 20
    ]
    assert [block["type"] for block in page_blocks] == [
        "heading",
        "paragraph",
        "paragraph",
        "paragraph",
    ]


def test_large_pdf_page_size_uses_content_coordinate_layout_without_silk_regression(
    tmp_path,
) -> None:
    content_list_v2 = tmp_path / "silk_style_content_list_v2.json"
    middle = tmp_path / "silk_style_middle.json"
    output = tmp_path / "canonical.json"
    page_20 = [
        _text_item(
            "paragraph",
            "近的烽燧报警，这样一直传到最近的可以发兵的军营。" * 5,
            [113, 104, 887, 212],
        ),
        _text_item(
            "paragraph",
            "出土了最大量丝路早期文献的悬泉就是这样一个军营。" * 5,
            [113, 221, 887, 388],
        ),
        _text_item("paragraph", "悬泉还出土了35000多件废弃的文书。" * 6, [114, 396, 886, 475]),
    ]
    content_list_v2.write_text(json.dumps([[] for _ in range(19)] + [page_20]), encoding="utf-8")
    middle.write_text(
        json.dumps({"pdf_info": [{"page_size": [1418, 2092]} for _ in range(20)]}),
        encoding="utf-8",
    )

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="silk-style",
        title="丝绸之路新史",
        language="zh-CN",
    )

    layout_stats = document["metadata"]["mineru"]["layout_stats"]
    assert layout_stats["page_width"] == 1000.0
    assert layout_stats["page_height"] == 1000.0
    assert 100.0 <= layout_stats["body_left"] <= 130.0
    assert 870.0 <= layout_stats["body_right"] <= 900.0
    page_blocks = [
        block for block in document["blocks"] if (block.get("source") or {}).get("page") == 20
    ]
    assert [block["type"] for block in page_blocks] == ["paragraph", "paragraph", "paragraph"]


def test_materialized_image_page_keeps_crop_and_stable_absorbed_ids(tmp_path) -> None:
    content_list_v2 = tmp_path / "image_page_content_list_v2.json"
    middle = tmp_path / "image_page_middle.json"
    output = tmp_path / "canonical.json"
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    _image_item([112, 114, 998, 679]),
                    _text_item("title", "欧亚大陆主要交通线", [146, 687, 480, 715]),
                    _text_item("paragraph", "---- 丝绸之路", [147, 725, 330, 748]),
                    _text_item("paragraph", "□ 古代遗址", [164, 752, 330, 774]),
                ]
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    middle.write_text(json.dumps({"pdf_info": [{"page_size": [1000, 1000]}]}), encoding="utf-8")

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="image-page",
        title="Image Page",
        language="zh-CN",
    )

    figure = document["blocks"][0]
    attrs = figure["attrs"]
    assert figure["block_id"] == "b000001"
    assert attrs["image_path"] == "images/sample.jpg"
    assert attrs.get("layout_role") != "full_page_image"
    assert attrs["absorbed_block_ids"] == ["b000002", "b000003", "b000004"]


def test_flush_right_terminal_display_block_keeps_source_spans(tmp_path) -> None:
    content_list_v2 = tmp_path / "terminal_content_list_v2.json"
    middle = tmp_path / "terminal_middle.json"
    output = tmp_path / "canonical.json"
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    _text_item("paragraph", "正文内容到此结束。", [110, 700, 880, 760]),
                    _text_item("paragraph", "二〇一五年九月", [650, 820, 880, 845]),
                    _text_item("paragraph", "北京", [780, 850, 880, 875]),
                ]
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    middle.write_text(json.dumps({"pdf_info": [{"page_size": [1000, 1000]}]}), encoding="utf-8")

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="terminal",
        title="Terminal",
        language="zh-CN",
    )

    display = next(block for block in document["blocks"] if block["type"] == "display_block")
    assert display["text"] == "二〇一五年九月\n北京"
    assert display["source"]["spans"] == [
        {
            "page": 1,
            "bbox": [650, 820, 880, 845],
            "block_id": "raw:1:1",
            "text": "二〇一五年九月",
        },
        {
            "page": 1,
            "bbox": [780, 850, 880, 875],
            "block_id": "raw:1:2",
            "text": "北京",
        },
    ]


def test_image_ocr_text_drops_generic_english_visual_descriptions(tmp_path) -> None:
    content_list_v2 = tmp_path / "image_ocr_content_list_v2.json"
    middle = tmp_path / "image_ocr_middle.json"
    output = tmp_path / "canonical.json"
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    {
                        "type": "image",
                        "content": {
                            "image_source": {"path": "images/artifact.jpg"},
                            "content": (
                                "Y. 009. g\n"
                                "Statue of a seated figure with raised arm "
                                "(no visible text or symbols)\n"
                                "约特干出土陶猴"
                            ),
                        },
                        "bbox": [151, 146, 855, 904],
                    }
                ]
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    middle.write_text(json.dumps({"pdf_info": [{"page_size": [1000, 1000]}]}), encoding="utf-8")

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="image-ocr",
        title="Image OCR",
        language="zh-CN",
    )

    figure = document["blocks"][0]
    ocr_text = figure["attrs"]["ocr_text_in_image"]
    assert "Y. 009. g" in ocr_text
    assert "约特干出土陶猴" in ocr_text
    assert "Statue of a seated figure" not in ocr_text


def test_small_pdf_page_size_keeps_pdf_coordinate_layout(tmp_path) -> None:
    content_list_v2 = tmp_path / "letter_style_content_list_v2.json"
    middle = tmp_path / "letter_style_middle.json"
    output = tmp_path / "canonical.json"
    page_20 = [
        _text_item(
            "paragraph",
            "This page already uses ordinary PDF user-space coordinates." * 4,
            [72, 72, 540, 760],
        )
    ]
    content_list_v2.write_text(json.dumps([[] for _ in range(19)] + [page_20]), encoding="utf-8")
    middle.write_text(
        json.dumps({"pdf_info": [{"page_size": [612, 792]} for _ in range(20)]}),
        encoding="utf-8",
    )

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="letter-style",
        title="Letter Style",
        language="en",
    )

    layout_stats = document["metadata"]["mineru"]["layout_stats"]
    assert layout_stats["page_width"] == 612.0
    assert layout_stats["page_height"] == 792.0
    assert layout_stats["body_right"] <= layout_stats["page_width"]


def test_input_relative_path_resolves_from_cwd_to_output_dir(tmp_path, monkeypatch) -> None:
    from inkline.parsers.mineru.normalize.core import _input_path_relative_to_output_dir

    work_dir = tmp_path / "workspace" / "job"
    output_dir = tmp_path / "results"
    input_pdf = tmp_path / "workspace" / "input.pdf"
    work_dir.mkdir(parents=True)
    output_dir.mkdir()
    input_pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.chdir(work_dir)

    relative = _input_path_relative_to_output_dir("../input.pdf", output_dir)

    expected = Path(os.path.relpath(input_pdf.resolve(), output_dir.resolve())).as_posix()
    assert relative == expected


def test_marker_locator_metadata_paths_are_relative(tmp_path) -> None:
    from argparse import Namespace

    import fitz  # type: ignore

    from inkline.parsers.mineru.normalize.core import build_canonical

    source_pdf = tmp_path / "source.pdf"
    doc = fitz.open()
    doc.new_page(width=100, height=100)
    doc.save(source_pdf)
    doc.close()
    output = tmp_path / "nested" / "canonical.json"
    artifact_dir = tmp_path / "nested" / "canonical_qwen_marker_locator"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "qwen_marker_evidence.json").write_text("[]", encoding="utf-8")
    timing_log = artifact_dir / "qwen_marker_timing.jsonl"
    args = Namespace(
        content_list_v2=tmp_path / "content_list_v2.json",
        content_list=None,
        middle=tmp_path / "middle.json",
        model=tmp_path / "model.json",
        md=tmp_path / "source.md",
        source_pdf=source_pdf,
        output=output,
        doc_id="sample",
        title="Sample",
        language="zh-CN",
        allow_missing_pdf_text=True,
        marker_locator_repair=True,
        marker_locator_model=DEFAULT_QWEN_MODEL,
        marker_locator_keep_alive="5m",
        marker_locator_page_dpi=150,
        marker_locator_block_dpi=200,
        marker_locator_artifact_dir=artifact_dir,
        marker_locator_timing_log=timing_log,
        marker_locator_reuse_evidence=True,
        marker_locator_body_mode="page_then_block",
        marker_locator_dpi=None,
        note_trace_log=None,
        note_recovery_mode="qwen",
        mineru_version="3.2.3",
        mineru_vl_utils_version="1.0.4",
        vlm_model={"local_path": tmp_path / "models" / "vlm", "model_name": "vlm"},
    )

    document = build_canonical({}, {}, args)

    marker_config = document["metadata"]["mineru"]["auxiliary_ocr"]["qwen_marker_locator"]
    assert marker_config["artifact_dir"] == "canonical_qwen_marker_locator"
    assert marker_config["timing_log"] == "canonical_qwen_marker_locator/qwen_marker_timing.jsonl"
    assert (
        marker_config["evidence_path"] == "canonical_qwen_marker_locator/qwen_marker_evidence.json"
    )
    assert (
        document["metadata"]["source_files"]["qwen_marker_evidence"]
        == "canonical_qwen_marker_locator/qwen_marker_evidence.json"
    )
    assert document["metadata"]["mineru"]["vlm_model"]["local_path"] == "../models/vlm"
    assert all(
        not Path(path).is_absolute() for path in document["metadata"]["source_files"].values()
    )


def test_generated_marker_locator_evidence_is_not_listed_as_source_file(tmp_path) -> None:
    from argparse import Namespace

    import fitz  # type: ignore

    from inkline.parsers.mineru.normalize.core import build_canonical

    source_pdf = tmp_path / "source.pdf"
    doc = fitz.open()
    doc.new_page(width=100, height=100)
    doc.save(source_pdf)
    doc.close()
    output = tmp_path / "nested" / "canonical.json"
    artifact_dir = tmp_path / "nested" / "canonical_qwen_marker_locator"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "qwen_marker_evidence.json").write_text("[]", encoding="utf-8")
    args = Namespace(
        content_list_v2=tmp_path / "content_list_v2.json",
        content_list=None,
        middle=tmp_path / "middle.json",
        model=None,
        md=None,
        source_pdf=source_pdf,
        output=output,
        doc_id="sample",
        title="Sample",
        language="zh-CN",
        allow_missing_pdf_text=True,
        marker_locator_repair=True,
        marker_locator_model=DEFAULT_QWEN_MODEL,
        marker_locator_keep_alive="5m",
        marker_locator_page_dpi=150,
        marker_locator_block_dpi=200,
        marker_locator_artifact_dir=artifact_dir,
        marker_locator_timing_log=None,
        marker_locator_reuse_evidence=False,
        marker_locator_body_mode="page_then_block",
        marker_locator_dpi=None,
        note_trace_log=None,
        note_recovery_mode="qwen",
        mineru_version="3.2.3",
        mineru_vl_utils_version="1.0.4",
        vlm_model=None,
    )

    document = build_canonical({}, {}, args)

    assert "qwen_marker_evidence" not in document["metadata"]["source_files"]


def test_qwen_marker_evidence_image_paths_are_relative(tmp_path) -> None:
    output = tmp_path / "nested" / "canonical.json"
    artifact_dir = tmp_path / "nested" / "canonical_qwen_marker_locator"
    artifact_dir.mkdir(parents=True)
    full_page_image = artifact_dir / "page_0001_150dpi_qwen_full_page.png"
    crop_image = artifact_dir / "page_0001_b000001_200dpi_qwen_body_block.png"
    document = {
        "blocks": [
            {
                "attrs": {
                    "qwen_marker_evidence_image": str(full_page_image),
                    "inline_runs": [
                        {
                            "evidence": {"qwen_crop_image": str(crop_image)},
                        }
                    ],
                },
            }
        ]
    }

    from inkline.parsers.mineru.normalize.core import _normalize_qwen_evidence_paths

    _normalize_qwen_evidence_paths(document, output.parent)
    block = document["blocks"][0]

    assert (
        block["attrs"]["qwen_marker_evidence_image"]
        == "canonical_qwen_marker_locator/page_0001_150dpi_qwen_full_page.png"
    )
    evidence = block["attrs"]["inline_runs"][0]["evidence"]
    assert (
        evidence["qwen_crop_image"]
        == "canonical_qwen_marker_locator/page_0001_b000001_200dpi_qwen_body_block.png"
    )


def test_qwen_marker_evidence_image_paths_rewrite_reused_relative_prefix(tmp_path) -> None:
    output = tmp_path / "canonical-after.json"
    artifact_dir = tmp_path / "canonical-after_qwen_marker_locator"
    document = {
        "blocks": [
            {
                "attrs": {
                    "qwen_marker_evidence_image": (
                        "丝绸之路新史/canonical_qwen_marker_locator/"
                        "page_0001_150dpi_qwen_full_page.png"
                    ),
                    "inline_runs": [
                        {
                            "evidence": {
                                "qwen_crop_image": (
                                    "丝绸之路新史/canonical_qwen_marker_locator/"
                                    "page_0001_b000001_200dpi_qwen_body_block.png"
                                )
                            },
                        }
                    ],
                },
            }
        ]
    }

    from inkline.parsers.mineru.normalize.core import _normalize_qwen_evidence_paths

    _normalize_qwen_evidence_paths(document, output.parent, artifact_dir=artifact_dir)
    block = document["blocks"][0]

    assert (
        block["attrs"]["qwen_marker_evidence_image"]
        == "canonical-after_qwen_marker_locator/page_0001_150dpi_qwen_full_page.png"
    )
    evidence = block["attrs"]["inline_runs"][0]["evidence"]
    assert (
        evidence["qwen_crop_image"]
        == "canonical-after_qwen_marker_locator/page_0001_b000001_200dpi_qwen_body_block.png"
    )


def test_build_canonical_normalizes_qwen_marker_evidence_image_paths(tmp_path) -> None:
    from argparse import Namespace

    from inkline.parsers.mineru.normalize.core import build_canonical
    from inkline.parsers.mineru.schema.models import RawBlock

    output = tmp_path / "nested" / "canonical.json"
    artifact_dir = tmp_path / "nested" / "canonical_qwen_marker_locator"
    artifact_dir.mkdir(parents=True)
    crop_image = artifact_dir / "page_0001_b000001_200dpi_qwen_body_block.png"
    args = Namespace(
        content_list_v2=tmp_path / "content_list_v2.json",
        content_list=None,
        middle=tmp_path / "middle.json",
        model=None,
        md=None,
        source_pdf=None,
        output=output,
        doc_id="sample",
        title="Sample",
        language="zh-CN",
        allow_missing_pdf_text=True,
        marker_locator_repair=False,
        marker_locator_model=DEFAULT_QWEN_MODEL,
        marker_locator_keep_alive="5m",
        marker_locator_page_dpi=150,
        marker_locator_block_dpi=200,
        marker_locator_artifact_dir=artifact_dir,
        marker_locator_timing_log=None,
        marker_locator_reuse_evidence=False,
        marker_locator_body_mode="page_then_block",
        marker_locator_dpi=None,
        note_trace_log=None,
        note_recovery_mode="qwen",
        mineru_version="3.2.3",
        mineru_vl_utils_version="1.0.4",
        vlm_model=None,
    )
    pages = {
        1: [
            RawBlock(
                page=1,
                index=0,
                raw_type="paragraph",
                text="Body1",
                bbox=[0, 0, 100, 100],
                raw={},
                inline_runs=[
                    {"type": "text", "text": "Body"},
                    {
                        "type": "note_ref",
                        "text": "1",
                        "marker": "1",
                        "evidence": {"qwen_crop_image": str(crop_image)},
                    },
                ],
            )
        ]
    }

    document = build_canonical(pages, {1: (100, 100)}, args)
    block = document["blocks"][0]

    evidence = block["attrs"]["inline_runs"][1]["evidence"]
    assert (
        evidence["qwen_crop_image"]
        == "canonical_qwen_marker_locator/page_0001_b000001_200dpi_qwen_body_block.png"
    )


def test_table_first_full_colspan_row_marked_center_aligned(tmp_path) -> None:
    content_list_v2 = tmp_path / "sample_content_list_v2.json"
    middle = tmp_path / "sample_middle.json"
    output = tmp_path / "canonical.json"
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    _table_item(
                        "<table>"
                        '<tr><td colspan="3">表题</td></tr>'
                        "<tr><td>A</td><td>B</td><td>C</td></tr>"
                        "</table>",
                        [100, 100, 900, 300],
                    )
                ]
            ]
        ),
        encoding="utf-8",
    )
    middle.write_text(json.dumps({"pdf_info": [{"page_size": [1000, 1400]}]}), encoding="utf-8")

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="sample",
        title="Sample",
        language="zh-CN",
    )

    table = document["blocks"][0]
    assert table["type"] == "table"
    assert table["attrs"]["cell_alignments"] == {"rows": [[0, "center"]]}


def test_table_first_regular_row_not_marked_center_aligned(tmp_path) -> None:
    content_list_v2 = tmp_path / "sample_content_list_v2.json"
    middle = tmp_path / "sample_middle.json"
    output = tmp_path / "canonical.json"
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    _table_item(
                        "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>",
                        [100, 100, 900, 300],
                    )
                ]
            ]
        ),
        encoding="utf-8",
    )
    middle.write_text(json.dumps({"pdf_info": [{"page_size": [1000, 1400]}]}), encoding="utf-8")

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="sample",
        title="Sample",
        language="zh-CN",
    )

    table = document["blocks"][0]
    assert table["type"] == "table"
    assert "cell_alignments" not in table["attrs"]


def test_snapshot_front_matter_does_not_replace_following_body_text_page(tmp_path) -> None:
    content_list_v2 = tmp_path / "sample_content_list_v2.json"
    middle = tmp_path / "sample_middle.json"
    output = tmp_path / "canonical.json"
    long_1 = "2004年4月，诸多丝路研究的专家汇聚北京，参加国际学术研讨会。" * 6
    long_2 = "在机场换登机牌时，地服人员问我们谁是带队的，我们互相看看迷惑不已。" * 6
    long_3 = "我们在西安过得非常愉快，看到了墓中出土的粟特语和汉语双语墓志。" * 6
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    _text_item("title", "THE SILK ROAD", [30, 482, 117, 863]),
                    _image_item([120, 120, 920, 900]),
                    _text_item("title", "丝绸之路新史", [450, 110, 620, 150]),
                    {
                        "type": "page_header",
                        "content": {"page_header_content": [{"type": "text", "content": "header"}]},
                        "bbox": [1, 1, 50, 20],
                    },
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [1, 940, 50, 960],
                    },
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [60, 940, 110, 960],
                    },
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [120, 940, 170, 960],
                    },
                ],
                [
                    _text_item("title", "THE SILK ROAD", [120, 60, 300, 90]),
                    _text_item("paragraph", "这是一段推荐语。" * 20, [110, 120, 900, 260]),
                    _image_item([100, 700, 900, 940]),
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [1, 940, 50, 960],
                    },
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [60, 940, 110, 960],
                    },
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [120, 940, 170, 960],
                    },
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [180, 940, 230, 960],
                    },
                ],
                [
                    _text_item("paragraph", "（美）芮乐伟·韩森著 张湛译", [700, 60, 920, 90]),
                    _text_item("title", "丝绸之路新史", [720, 100, 920, 140]),
                    _text_item("paragraph", "北京联合出版公司", [720, 850, 920, 880]),
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [1, 940, 50, 960],
                    },
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [60, 940, 110, 960],
                    },
                    {
                        "type": "page_footer",
                        "content": {"page_footer_content": [{"type": "text", "content": "footer"}]},
                        "bbox": [120, 940, 170, 960],
                    },
                ],
                [
                    _text_item("title", "图书在版编目（CIP）数据", [105, 72, 400, 96]),
                    *[
                        _text_item("paragraph", text, [105, 110 + i * 24, 875, 130 + i * 24])
                        for i, text in enumerate(
                            [
                                "丝绸之路新史/（美）韩森著；张湛译",
                                "ISBN 978-7-5502-5341-4",
                                "Copyright © 2012 by Oxford University Press",
                                "版权所有，侵权必究",
                                "北京联合出版公司出版",
                                "2015年9月第1版 2015年9月第1次印刷",
                                "定价：49.80元",
                                "本书若有质量问题，请联系调换。",
                            ]
                            * 3
                        )
                    ],
                ],
                [
                    _text_item("title", "中文版序言", [422, 184, 591, 211]),
                    _text_item("paragraph", long_1, [119, 281, 896, 537]),
                    _text_item("paragraph", long_2, [118, 544, 893, 741]),
                    _text_item("paragraph", long_3, [118, 748, 893, 917]),
                    {
                        "type": "page_number",
                        "content": {"page_number_content": [{"type": "text", "content": "1"}]},
                        "bbox": [877, 948, 888, 959],
                    },
                ],
                [
                    _text_item("title", "第一章 起点", [420, 184, 610, 211]),
                    _text_item("paragraph", "这是第一章的正文。" * 20, [119, 281, 896, 537]),
                    {
                        "type": "page_number",
                        "content": {"page_number_content": [{"type": "text", "content": "2"}]},
                        "bbox": [877, 948, 888, 959],
                    },
                ],
            ]
        ),
        encoding="utf-8",
    )
    middle.write_text(
        json.dumps({"pdf_info": [{"page_size": [1418, 2092]} for _ in range(6)]}), encoding="utf-8"
    )

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="silk",
        title="丝绸之路新史",
        language="zh-CN",
    )

    page5_blocks = [
        block for block in document["blocks"] if (block.get("source") or {}).get("page") == 5
    ]
    assert [block["type"] for block in page5_blocks] == [
        "heading",
        "paragraph",
        "paragraph",
        "paragraph",
    ]
    assert page5_blocks[0]["text"] == "中文版序言"
    assert all(block["type"] != "figure" for block in page5_blocks)
    assert document["pages"][0]["page_role"] == "cover"
    assert document["pages"][1]["page_role"] == "generic"
    assert document["pages"][1]["snapshot"]["required"] is True
    assert document["pages"][3]["page_role"] == "copyright_page"


def test_chart_and_diagram_snapshot_pages_keep_visual_content_blocks(tmp_path) -> None:
    content_list_v2 = tmp_path / "sample_content_list_v2.json"
    middle = tmp_path / "sample_middle.json"
    output = tmp_path / "canonical.json"
    chart_text = (
        "| Region | Start Year | End Year |\n| :--- | :--- | :--- |\n| 尼雅 | 200 BCE | 400 CE |"
    )
    diagram_page = [
        _text_item("paragraph", "600 CE", [83, 109, 161, 125]),
        _text_item("paragraph", "800 CE", [276, 109, 353, 125]),
        _text_item("paragraph", "1000 CE", [464, 109, 552, 125]),
        _text_item("paragraph", "1200 CE", [654, 109, 743, 125]),
        _text_item("paragraph", "尼雅 & 楼兰", [720, 143, 858, 163]),
        _image_item([162, 196, 298, 226]),
        _text_item("paragraph", "648年成为安西四镇之一", [76, 227, 532, 241]),
        _text_item("paragraph", "龟兹", [722, 203, 775, 223]),
        _image_item([59, 325, 827, 437]),
        _text_item("paragraph", "撒马尔罕", [719, 331, 826, 352]),
        _text_item("paragraph", "长安", [721, 397, 773, 417]),
        _text_item("paragraph", "敦煌", [719, 462, 773, 482]),
        _image_item([76, 518, 692, 562]),
        _text_item("paragraph", "于阗", [720, 525, 772, 544]),
        _text_item("paragraph", "中国", [719, 591, 771, 611]),
        _image_item([107, 647, 276, 692]),
        _text_item("paragraph", "伊朗", [718, 655, 771, 674]),
        _image_item([64, 706, 277, 750]),
        _text_item("paragraph", "伊斯兰世界", [717, 713, 847, 733]),
        _text_item("paragraph", "南亚", [717, 778, 770, 798]),
        _image_item([38, 837, 51, 867]),
        _text_item("paragraph", "欧洲", [717, 843, 770, 863]),
    ]
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    _text_item("title", "年表", [113, 69, 209, 93]),
                    _chart_item(chart_text, [137, 115, 951, 920]),
                ],
                diagram_page,
            ]
        ),
        encoding="utf-8",
    )
    middle.write_text(
        json.dumps({"pdf_info": [{"page_size": [1418, 2092]} for _ in range(2)]}), encoding="utf-8"
    )

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="silk",
        title="丝绸之路新史",
        language="zh-CN",
    )

    assert any(
        block["type"] == "table" and block["text"] == chart_text for block in document["blocks"]
    )
    page2_blocks = [
        block for block in document["blocks"] if (block.get("source") or {}).get("page") == 2
    ]
    assert len(page2_blocks) == 1
    assert page2_blocks[0]["type"] == "figure"
    assert page2_blocks[0]["attrs"]["snapshot_role"] == "page_diagram"
    assert document["pages"][0]["snapshot"]["role"] == "page_chart"
    assert document["pages"][1]["snapshot"]["role"] == "page_diagram"


def test_visual_label_page_stays_float_like_figure(tmp_path) -> None:
    content_list_v2 = tmp_path / "sample_content_list_v2.json"
    middle = tmp_path / "sample_middle.json"
    output = tmp_path / "canonical.json"
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    _text_item("paragraph", "吐鲁番地区", [440, 80, 560, 105]),
                    _text_item("paragraph", "玄奘求法路线", [120, 160, 260, 185]),
                    _text_item("paragraph", "---- 丝路北道", [320, 160, 460, 185]),
                    _text_item("paragraph", "黄海", [820, 420, 870, 445]),
                    _text_item("paragraph", "四川", [420, 690, 470, 715]),
                    _text_item("paragraph", "东海", [830, 720, 880, 745]),
                    _image_item([80, 120, 900, 860]),
                ]
            ]
        ),
        encoding="utf-8",
    )
    middle.write_text(json.dumps({"pdf_info": [{"page_size": [1418, 2092]}]}), encoding="utf-8")

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="silk",
        title="丝绸之路新史",
        language="zh-CN",
    )

    assert len(document["blocks"]) == 1
    block = document["blocks"][0]
    assert block["type"] == "figure"
    assert block["attrs"]["snapshot_role"] == "visual_label_page"
    assert "吐鲁番地区" in block["attrs"]["ocr_text_in_image"]
    assert document["pages"][0]["snapshot"]["role"] == "visual_label_page"


def test_dense_single_text_image_map_stays_regular_figure(tmp_path) -> None:
    content_list_v2 = tmp_path / "sample_content_list_v2.json"
    middle = tmp_path / "sample_middle.json"
    output = tmp_path / "canonical.json"
    labels = "\n".join(f"地名{i}" for i in range(30))
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    {
                        "type": "image",
                        "sub_type": "text_image",
                        "content": {
                            "image_source": {"path": "images/map.jpg"},
                            "content": labels,
                        },
                        "bbox": [229, 247, 1416, 1542],
                    }
                ]
            ]
        ),
        encoding="utf-8",
    )
    middle.write_text(json.dumps({"pdf_info": [{"page_size": [1418, 2098]}]}), encoding="utf-8")

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="silk",
        title="丝绸之路新史",
        language="zh-CN",
    )

    assert len(document["blocks"]) == 1
    block = document["blocks"][0]
    assert block["type"] == "figure"
    assert block["attrs"]["sub_type"] == "text_image"
    assert "layout_role" not in block["attrs"]
    assert "snapshot_role" not in block["attrs"]
    assert "地名29" in block["attrs"]["ocr_text_in_image"]
    assert document["pages"][0]["snapshot"]["required"] is False


def test_mineru_parser_disables_qwen_marker_repair_at_150_dpi_by_default(
    tmp_path, monkeypatch
) -> None:
    captured = {}

    def fake_ingest(input_pdf, **kwargs):
        captured.update(kwargs)
        return {
            "metadata": {
                "schema_version": "1.0",
                "doc_id": "sample",
                "title": "Sample",
                "language": "en",
                "source_file": str(input_pdf),
                "parser_name": "mineru",
            },
            "blocks": [],
            "toc": [],
        }

    monkeypatch.setattr(mineru_bridge, "ingest_pdf_with_mineru", fake_ingest)
    request = ParseRequest(
        tmp_path / "sample.pdf",
        tmp_path / "canonical.json",
        language="en",
    )

    MinerUParser().parse(request)

    assert captured["marker_locator_repair"] is False
    assert captured["marker_locator_page_dpi"] == 150
