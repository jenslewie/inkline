from __future__ import annotations

import json

from inkline.canonical import validate_document
from inkline.parse import ParseRequest
from inkline.parsers.mineru import normalize_mineru_outputs
import inkline.parsers.mineru.bridge as mineru_bridge
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


def test_normalize_mineru_outputs_produces_valid_canonical(tmp_path) -> None:
    content_list_v2 = tmp_path / "sample_content_list_v2.json"
    middle = tmp_path / "sample_middle.json"
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

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
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
    assert document["metadata"]["parser_name"] == "mineru"
    assert document["metadata"]["schema_version"] == "1.0"
    assert document["metadata"]["mineru"]["version"] == "3.2.3"
    assert document["metadata"]["mineru"]["vlm_model"]["model_name"] == "MinerU2.5-Pro-2605-1.2B"
    marker_config = document["metadata"]["mineru"]["auxiliary_ocr"]["qwen_marker_locator"]
    assert marker_config["enabled"] is False
    assert marker_config["model"] == "qwen3.6:35b-a3b"
    assert marker_config["page_dpi"] == 150
    assert marker_config["block_dpi"] == 200
    assert output.exists()


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
                    {"type": "page_header", "content": {"page_header_content": [{"type": "text", "content": "header"}]}, "bbox": [1, 1, 50, 20]},
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [1, 940, 50, 960]},
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [60, 940, 110, 960]},
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [120, 940, 170, 960]},
                ],
                [
                    _text_item("title", "THE SILK ROAD", [120, 60, 300, 90]),
                    _text_item("paragraph", "这是一段推荐语。" * 20, [110, 120, 900, 260]),
                    _image_item([100, 700, 900, 940]),
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [1, 940, 50, 960]},
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [60, 940, 110, 960]},
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [120, 940, 170, 960]},
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [180, 940, 230, 960]},
                ],
                [
                    _text_item("paragraph", "（美）芮乐伟·韩森著 张湛译", [700, 60, 920, 90]),
                    _text_item("title", "丝绸之路新史", [720, 100, 920, 140]),
                    _text_item("paragraph", "北京联合出版公司", [720, 850, 920, 880]),
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [1, 940, 50, 960]},
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [60, 940, 110, 960]},
                    {"type": "page_footer", "content": {"page_footer_content": [{"type": "text", "content": "footer"}]}, "bbox": [120, 940, 170, 960]},
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
                    {"type": "page_number", "content": {"page_number_content": [{"type": "text", "content": "1"}]}, "bbox": [877, 948, 888, 959]},
                ],
                [
                    _text_item("title", "第一章 起点", [420, 184, 610, 211]),
                    _text_item("paragraph", "这是第一章的正文。" * 20, [119, 281, 896, 537]),
                    {"type": "page_number", "content": {"page_number_content": [{"type": "text", "content": "2"}]}, "bbox": [877, 948, 888, 959]},
                ],
            ]
        ),
        encoding="utf-8",
    )
    middle.write_text(json.dumps({"pdf_info": [{"page_size": [1418, 2092]} for _ in range(6)]}), encoding="utf-8")

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

    page5_blocks = [block for block in document["blocks"] if (block.get("source") or {}).get("page") == 5]
    assert [block["type"] for block in page5_blocks] == ["heading", "paragraph", "paragraph", "paragraph"]
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
    chart_text = "| Region | Start Year | End Year |\n| :--- | :--- | :--- |\n| 尼雅 | 200 BCE | 400 CE |"
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
    middle.write_text(json.dumps({"pdf_info": [{"page_size": [1418, 2092]} for _ in range(2)]}), encoding="utf-8")

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

    assert any(block["type"] == "table" and block["text"] == chart_text for block in document["blocks"])
    page2_blocks = [block for block in document["blocks"] if (block.get("source") or {}).get("page") == 2]
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
