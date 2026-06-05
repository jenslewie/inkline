from mineru_normalizer.reconcile.notes.markers import _locate_qwen_body_ref, _qwen_marker_offset_in_text
from mineru_normalizer.reconcile.notes.resolver import _NoteContext


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
