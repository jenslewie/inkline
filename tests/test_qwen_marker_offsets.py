from inkline.parsers.mineru.reconcile.notes.marker_inline import (
    _inline_runs_text,
    _InlineMarkerLocation,
    _insert_inline_note_run,
)
from inkline.parsers.mineru.reconcile.notes.marker_location import (
    _locate_qwen_body_ref,
)
from inkline.parsers.mineru.reconcile.notes.marker_offsets import (
    _qwen_marker_offset_in_text,
)
from inkline.parsers.mineru.reconcile.notes.marker_recovery import (
    _strip_qwen_visible_marker,
    _update_existing_qwen_ref_inline_location,
)
from inkline.parsers.mineru.reconcile.notes.markers import (
    recover_missing_note_refs,
)
from inkline.parsers.mineru.reconcile.notes.resolver import _NoteContext, resolve_note_links


def test_qwen_symbol_marker_before_omitted_comma() -> None:
    text = (
        "最近几十年来考古学家拼合了上千件类似的文书，包括契约、诉讼、收据、货单、药方，"
        "以及一件让人痛心的人口买卖合同：一名女奴在一千多年前的某个赶集的日子以120枚银币"
        "的价格被出售。这些文书用汉语、梵语，以及其他死语言写成。"
    )

    offset = _qwen_marker_offset_in_text(
        text,
        "*",
        "汉语、梵语",
        "以及其他死语言写成",
        "汉语、梵语*，以及其他死语言写成",
    )

    assert offset == text.index("，以及其他死语言写成")


def test_qwen_does_not_override_existing_equation_inline_run() -> None:
    block = {
        "block_id": "b000080",
        "type": "paragraph",
        "text": "用来助焊以及鞣革的硇砂 是某些商路上的最重要的货物。",
        "source": {"page": 21},
        "attrs": {
            "note_refs": [
                {
                    "marker": "*",
                    "source": "equation_inline",
                    "source_page": 21,
                    "raw_marker": "^{*}",
                    "target_note_id": "note_b000087",
                }
            ],
            "inline_runs": [
                {"type": "text", "text": "用来助焊以及鞣革的硇砂  "},
                {
                    "type": "note_ref",
                    "marker": "*",
                    "source": "equation_inline",
                    "source_page": 21,
                    "target_note_id": "note_b000087",
                },
                {"type": "text", "text": " 是某些商路上的最重要的货物。"},
            ],
        },
    }

    changed = _update_existing_qwen_ref_inline_location(
        block,
        "*",
        21,
        {
            "marker": "*",
            "before_text": "助焊以及鞣革的",
            "after_text": "是某些商路上的",
            "quote": "助焊以及鞣革的*是某些商路上的",
            "confidence": "high",
        },
        _InlineMarkerLocation(
            char_index=10,
            source="qwen_marker_locator",
            confidence="high",
            evidence={},
        ),
    )

    assert changed is False
    ref = next(run for run in block["attrs"]["inline_runs"] if run["type"] == "note_ref")
    assert "inline_position_source" not in ref
    assert block["attrs"]["inline_runs"][0]["text"].endswith("硇砂  ")


def test_qwen_overrides_invalid_existing_equation_inline_run() -> None:
    block = {
        "block_id": "b1",
        "type": "paragraph",
        "text": "正确正文。",
        "source": {"page": 1},
        "attrs": {
            "note_refs": [
                {
                    "marker": "*",
                    "source": "equation_inline",
                    "source_page": 1,
                    "raw_marker": "^{*}",
                    "target_note_id": "note_1",
                }
            ],
            "inline_runs": [
                {"type": "text", "text": "错误正文"},
                {
                    "type": "note_ref",
                    "marker": "*",
                    "source": "equation_inline",
                    "source_page": 1,
                    "target_note_id": "note_1",
                },
            ],
        },
    }

    changed = _update_existing_qwen_ref_inline_location(
        block,
        "*",
        1,
        {
            "marker": "*",
            "before_text": "正确",
            "after_text": "正文",
            "quote": "正确*正文",
            "confidence": "high",
        },
        _InlineMarkerLocation(
            char_index=2,
            source="qwen_marker_locator",
            confidence="high",
            evidence={},
        ),
    )

    assert changed is True
    ref = next(run for run in block["attrs"]["inline_runs"] if run["type"] == "note_ref")
    assert "inline_offset" not in ref
    assert ref["raw_marker"] == "^{*}"
    assert ref["target_note_id"] == "note_1"
    assert [run["type"] for run in block["attrs"]["inline_runs"]] == ["text", "note_ref", "text"]
    assert _inline_runs_text(block["attrs"]["inline_runs"]) == block["text"]


def test_qwen_insertion_preserves_other_mineru_inline_runs() -> None:
    block = {
        "block_id": "b1",
        "type": "paragraph",
        "text": "甲 乙 丙",
        "source": {"page": 1},
        "attrs": {
            "note_refs": [
                {
                    "marker": "*",
                    "source": "equation_inline",
                    "source_page": 1,
                    "raw_marker": "^{*}",
                },
                {
                    "marker": "1",
                    "source": "qwen_marker_locator",
                    "source_page": 1,
                    "raw_marker": "^{1}",
                },
            ],
            "inline_runs": [
                {"type": "text", "text": "甲  "},
                {
                    "type": "note_ref",
                    "marker": "*",
                    "source": "equation_inline",
                    "source_page": 1,
                    "raw_marker": "^{*}",
                },
                {"type": "text", "text": " 乙 丙"},
            ],
        },
    }

    changed = _update_existing_qwen_ref_inline_location(
        block,
        "1",
        1,
        {"marker": "1", "before_text": "乙", "after_text": "丙", "quote": "乙1丙"},
        _InlineMarkerLocation(
            char_index=3, source="qwen_marker_locator", confidence="high", evidence={}
        ),
    )

    assert changed is True
    runs = block["attrs"]["inline_runs"]
    assert [run.get("marker") for run in runs if run.get("type") == "note_ref"] == ["*", "1"]
    assert "".join(run.get("text", "") for run in runs if run.get("type") == "text") == "甲   乙 丙"


def test_qwen_insertion_does_not_relocate_unmappable_existing_inline_ref() -> None:
    block = {
        "text": "abcdef",
        "attrs": {
            "inline_runs": [
                {"type": "text", "text": "abcX"},
                {
                    "type": "note_ref",
                    "marker": "1",
                    "source": "equation_inline",
                    "source_page": 1,
                    "raw_marker": "^{1}",
                },
                {"type": "text", "text": "def"},
            ]
        },
    }

    _insert_inline_note_run(
        block,
        {
            "marker": "2",
            "source": "qwen_marker_locator",
            "source_page": 1,
            "raw_marker": "^{2}",
        },
        2,
    )

    runs = block["attrs"]["inline_runs"]
    assert [run.get("marker") for run in runs if run.get("type") == "note_ref"] == ["1", "2"]
    assert _inline_runs_text(runs) == "abcXdef"


def test_qwen_insertion_preserves_resolved_refs_when_text_mapping_fails() -> None:
    block = {
        "text": "abcdef",
        "attrs": {
            "inline_runs": [
                {"type": "text", "text": "abX"},
                {
                    "type": "note_ref",
                    "marker": "1",
                    "source": "equation_inline",
                    "source_page": 1,
                    "raw_marker": "^{1}",
                    "target_block_id": "fn1",
                    "target_note_id": "note_fn1",
                },
                {"type": "text", "text": "cd"},
                {
                    "type": "note_ref",
                    "marker": "2",
                    "source": "equation_inline",
                    "source_page": 1,
                    "raw_marker": "^{2}",
                    "target_block_id": "fn2",
                    "target_note_id": "note_fn2",
                },
                {"type": "text", "text": "ef"},
            ]
        },
    }

    _insert_inline_note_run(
        block,
        {
            "marker": "3",
            "source": "qwen_marker_locator",
            "source_page": 1,
            "raw_marker": "^{3}",
        },
        3,
    )

    runs = block["attrs"]["inline_runs"]
    assert [run.get("marker") for run in runs if run.get("type") == "note_ref"] == [
        "1",
        "2",
        "3",
    ]
    assert [run.get("target_block_id") for run in runs if run.get("type") == "note_ref"][:2] == [
        "fn1",
        "fn2",
    ]


def test_qwen_symbol_marker_before_omitted_comma_with_normalized_spacing() -> None:
    text = "这些文书用汉语、梵语， 以及其他死语言写成。"

    offset = _qwen_marker_offset_in_text(
        text,
        "*",
        "汉语、梵语",
        "以及其他死语言写成",
        "汉语、梵语*，以及其他死语言写成",
    )

    assert offset == text.index("， 以及其他死语言写成")


def test_qwen_symbol_marker_before_omitted_period() -> None:
    text = "向东包括甘肃省和陕西省。今天的新疆包括了丝绸之路在中国西部的绝大部分。"

    offset = _qwen_marker_offset_in_text(
        text,
        "***",
        "和陕西省",
        "今天的新疆",
        "和陕西省***今天的新疆",
    )

    assert offset == text.index("。今天的新疆")


def test_qwen_numeric_marker_does_not_use_before_only_when_after_is_in_quote() -> None:
    text = "今天的新疆包括了丝绸之路在中国西部的绝大部分。"

    offset = _qwen_marker_offset_in_text(
        text,
        "1",
        "的绝大部分",
        "今天在这里",
        "的绝大部分1今天在这里",
    )

    assert offset is None


def test_qwen_numeric_cross_block_marker_before_terminal_punctuation() -> None:
    blocks = [
        {
            "block_id": "b000102",
            "type": "paragraph",
            "text": "今天的新疆包括了丝绸之路在中国西部的绝大部分。",
            "source": {"page": 23, "bbox": [99, 492, 873, 600]},
            "attrs": {},
        },
        {
            "block_id": "b000103",
            "type": "paragraph",
            "text": "今天在这里可以看到当代新疆壮阔的景色。",
            "source": {"page": 23, "bbox": [98, 608, 873, 745]},
            "attrs": {},
        },
    ]

    located = _locate_qwen_body_ref(
        blocks,
        _NoteContext(blocks),
        23,
        "1",
        {
            "marker": "1",
            "before_text": "的绝大部分",
            "after_text": "今天在这里",
            "quote": "的绝大部分1今天在这里",
            "confidence": "high",
        },
    )

    assert located is not None
    block, inline_location = located
    assert block["block_id"] == "b000102"
    assert inline_location.char_index == blocks[0]["text"].index("。")
    assert inline_location.evidence["qwen_cross_block_after_text"] == "今天在这里"


def test_qwen_body_ref_uses_block_id_to_disambiguate_matching_context() -> None:
    blocks = [
        {
            "block_id": "b1",
            "type": "paragraph",
            "text": "第一段有相同之后的文字。",
            "source": {"page": 1, "bbox": [10, 10, 100, 30]},
            "attrs": {},
        },
        {
            "block_id": "b2",
            "type": "paragraph",
            "text": "第二段有相同之后的文字。",
            "source": {"page": 1, "bbox": [10, 40, 100, 60]},
            "attrs": {},
        },
    ]

    located = _locate_qwen_body_ref(
        blocks,
        _NoteContext(blocks),
        1,
        "1",
        {
            "marker": "1",
            "before_text": "有相同",
            "after_text": "之后的文字",
            "quote": "有相同1之后的文字",
            "confidence": "high",
            "block_id": "b2",
            "body_ref_source": "paragraph_crop",
        },
    )

    assert located is not None
    block, inline_location = located
    assert block["block_id"] == "b2"
    assert inline_location.char_index == blocks[1]["text"].index("之后的文字")
    assert inline_location.evidence["qwen_block_id"] == "b2"


def test_qwen_body_ref_with_block_id_does_not_fallback_to_other_block() -> None:
    blocks = [
        {
            "block_id": "b1",
            "type": "paragraph",
            "text": "第一段有相同之后的文字。",
            "source": {"page": 1, "bbox": [10, 10, 100, 30]},
            "attrs": {},
        }
    ]

    located = _locate_qwen_body_ref(
        blocks,
        _NoteContext(blocks),
        1,
        "1",
        {
            "marker": "1",
            "before_text": "有相同",
            "after_text": "之后的文字",
            "quote": "有相同1之后的文字",
            "confidence": "high",
            "block_id": "missing",
        },
    )

    assert located is None


def test_qwen_body_ref_strips_neighbor_symbol_marker_from_matching_context() -> None:
    blocks = [
        {
            "block_id": "b000102",
            "type": "paragraph",
            "text": "向东包括甘肃省和陕西省。今天的新疆包括了丝绸之路在中国西部的绝大部分。",
            "source": {"page": 23, "bbox": [99, 492, 873, 600]},
            "attrs": {},
        }
    ]

    located = _locate_qwen_body_ref(
        blocks,
        _NoteContext(blocks),
        23,
        "1",
        {
            "marker": "1",
            "before_text": "西省***。",
            "after_text": "今天的",
            "quote": "西省***。1今天的",
            "confidence": "high",
            "block_id": "b000102",
        },
    )

    assert located is not None
    block, inline_location = located
    assert block["block_id"] == "b000102"
    assert inline_location.char_index == blocks[0]["text"].index("今天的")
    assert inline_location.evidence["qwen_matching_before_text"] == "西省。"


def test_qwen_recovers_scoped_chapter_endnote_ref() -> None:
    blocks = [
        {
            "block_id": "b_chapter",
            "type": "heading",
            "text": "1 第一章",
            "source": {"page": 1},
            "attrs": {},
        },
        {
            "block_id": "b_body",
            "type": "paragraph",
            "text": "正文左侧内容右侧继续。",
            "source": {"page": 2, "bbox": [100, 100, 500, 140]},
            "attrs": {},
        },
        {
            "block_id": "b_notes",
            "type": "heading",
            "text": "注释",
            "source": {"page": 10},
            "attrs": {},
        },
        {
            "block_id": "b_note_1",
            "type": "list_item",
            "text": "1. 第一条注释。",
            "source": {"page": 10},
            "attrs": {},
        },
        {
            "block_id": "b_note_2",
            "type": "list_item",
            "text": "2. 第二条注释。",
            "source": {"page": 10},
            "attrs": {},
        },
    ]

    recover_missing_note_refs(
        blocks,
        qwen_marker_pages={
            "pages": [
                {
                    "page": 2,
                    "body_refs": [
                        {
                            "marker": "1",
                            "before_text": "正文左侧",
                            "after_text": "内容右侧",
                            "quote": "正文左侧1内容右侧",
                            "confidence": "high",
                        }
                    ],
                }
            ]
        },
        recovery_mode="qwen",
    )
    resolve_note_links(blocks)

    refs = [run for run in blocks[1]["attrs"]["inline_runs"] if run.get("type") == "note_ref"]
    assert len(refs) == 1
    assert refs[0]["source"] == "qwen_marker_locator"
    assert refs[0]["target_block_id"] == "b_note_1"
    assert refs[0]["note_strategy"] == "chapter_endnote"
    assert "note_refs" not in blocks[1]["attrs"]
    assert blocks[1]["attrs"]["inline_runs"][1]["type"] == "note_ref"


def test_qwen_recovers_adjacent_visible_symbol_and_numeric_markers() -> None:
    blocks = [
        {
            "block_id": "b_body",
            "type": "paragraph",
            "text": "在763年击败了叛军*。3作为奖赏。",
            "source": {"page": 212},
            "attrs": {},
        },
        {
            "block_id": "b_note_star",
            "type": "footnote",
            "text": "*星号脚注。",
            "source": {"page": 212},
            "attrs": {"role": "page_footnote", "note_marker": "*"},
        },
        {
            "block_id": "b_note_3",
            "type": "footnote",
            "text": "3 数字脚注。",
            "source": {"page": 212},
            "attrs": {"role": "page_footnote", "note_marker": "3"},
        },
    ]

    recover_missing_note_refs(
        blocks,
        qwen_marker_pages={
            "pages": [
                {
                    "page": 212,
                    "body_refs": [
                        {
                            "marker": "*",
                            "block_id": "b_body",
                            "before_text": "击败了叛军",
                            "after_text": "。3作为",
                            "quote": "击败了叛军*。3作为",
                            "confidence": "high",
                        },
                        {
                            "marker": "3",
                            "block_id": "b_body",
                            "before_text": "叛军*。",
                            "after_text": "作为奖赏",
                            "quote": "叛军*。3作为奖赏",
                            "confidence": "high",
                        },
                    ],
                }
            ]
        },
        recovery_mode="qwen",
    )

    assert blocks[0]["text"] == "在763年击败了叛军。作为奖赏。"
    runs = blocks[0]["attrs"]["inline_runs"]
    refs = [run for run in runs if run["type"] == "note_ref"]
    assert {ref["marker"] for ref in refs} == {"*", "3"}
    assert "note_refs" not in blocks[0]["attrs"]
    assert [run["marker"] for run in runs if run["type"] == "note_ref"] == ["*", "3"]
    assert (
        "".join(run.get("text", "") for run in runs if run["type"] == "text") == blocks[0]["text"]
    )


def test_qwen_uses_unique_visible_star_in_requested_block_when_ocr_context_differs() -> None:
    blocks = [
        {
            "block_id": "b_body",
            "type": "paragraph",
            "text": "藏经洞中共有三件汉语摩尼教文献*。",
            "source": {"page": 244, "pages": [244, 245]},
            "attrs": {},
        }
    ]

    located = _locate_qwen_body_ref(
        blocks,
        _NoteContext(blocks),
        245,
        "*",
        {
            "marker": "*",
            "block_id": "b_body",
            "before_text": "摩尼教",
            "after_text": "。",
            "quote": "摩尼教*。",
            "confidence": "high",
        },
    )

    assert located is not None
    block, inline_location = located
    assert block["block_id"] == "b_body"
    assert inline_location.char_index == blocks[0]["text"].index("*")
    assert inline_location.evidence["qwen_unique_visible_marker_fallback"] is True


def test_qwen_does_not_use_page_unique_star_without_block_or_context_match() -> None:
    blocks = [
        {
            "block_id": "b_body",
            "type": "paragraph",
            "text": "公式 2 * 3 等于 6。",
            "source": {"page": 1},
            "attrs": {},
        },
        {
            "block_id": "b_note",
            "type": "footnote",
            "text": "* 脚注内容。",
            "source": {"page": 1},
            "attrs": {"role": "page_footnote", "note_marker": "*"},
        },
    ]

    recover_missing_note_refs(
        blocks,
        qwen_marker_pages={
            "pages": [
                {
                    "page": 1,
                    "body_refs": [
                        {
                            "marker": "*",
                            "before_text": "完全不存在",
                            "after_text": "也不存在",
                            "quote": "完全不存在*也不存在",
                            "confidence": "high",
                        }
                    ],
                }
            ]
        },
        recovery_mode="qwen",
    )

    assert blocks[0]["text"] == "公式 2 * 3 等于 6。"
    assert "note_refs" not in blocks[0]["attrs"]


def test_qwen_visible_marker_removal_spans_adjacent_text_runs() -> None:
    block = {
        "text": "a¹²b",
        "attrs": {
            "inline_runs": [
                {"type": "text", "text": "a¹"},
                {"type": "text", "text": "²b"},
            ]
        },
    }

    _strip_qwen_visible_marker(
        block,
        _InlineMarkerLocation(
            char_index=1,
            source="qwen_marker_locator",
            confidence="high",
            evidence={"qwen_visible_marker_text": "¹²"},
        ),
    )

    assert block["text"] == "ab"
    assert _inline_runs_text(block["attrs"]["inline_runs"]) == block["text"]


def test_qwen_visible_marker_removal_spans_runs_after_structured_ref() -> None:
    block = {
        "text": "1a¹²b",
        "attrs": {
            "inline_runs": [
                {
                    "type": "note_ref",
                    "marker": "1",
                    "source": "equation_inline",
                    "source_page": 1,
                    "raw_marker": "1",
                },
                {"type": "text", "text": "a¹"},
                {"type": "text", "text": "²b"},
            ]
        },
    }

    _strip_qwen_visible_marker(
        block,
        _InlineMarkerLocation(
            char_index=2,
            source="qwen_marker_locator",
            confidence="high",
            evidence={"qwen_visible_marker_text": "¹²"},
        ),
    )

    assert block["text"] == "1ab"
    assert _inline_runs_text(block["attrs"]["inline_runs"]) == "ab"


def test_qwen_refinement_strips_visible_marker_for_existing_ref() -> None:
    blocks = [
        {
            "block_id": "b_body",
            "type": "paragraph",
            "text": "若言有苦无是处”。²摩尼鼓励。",
            "source": {"page": 245},
            "attrs": {
                "note_refs": [
                    {
                        "marker": "2",
                        "source": "qwen_marker_locator",
                        "source_page": 245,
                        "raw_marker": "^{2}",
                    }
                ]
            },
        },
        {
            "block_id": "b_note",
            "type": "footnote",
            "text": "2 脚注内容。",
            "source": {"page": 245},
            "attrs": {"role": "page_footnote", "note_marker": "2"},
        },
    ]

    recover_missing_note_refs(
        blocks,
        qwen_marker_pages={
            "pages": [
                {
                    "page": 245,
                    "body_refs": [
                        {
                            "marker": "2",
                            "block_id": "b_body",
                            "before_text": "无是处”。",
                            "after_text": "摩尼鼓励",
                            "quote": "无是处”。2摩尼鼓励",
                            "confidence": "high",
                        }
                    ],
                }
            ]
        },
        recovery_mode="qwen",
    )

    assert blocks[0]["text"] == "若言有苦无是处”。摩尼鼓励。"
    runs = blocks[0]["attrs"]["inline_runs"]
    assert [run["marker"] for run in runs if run["type"] == "note_ref"] == ["2"]
    assert (
        "".join(run.get("text", "") for run in runs if run["type"] == "text") == blocks[0]["text"]
    )
