from mineru_normalizer.reconcile.notes.markers import _qwen_marker_offset_in_text


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
