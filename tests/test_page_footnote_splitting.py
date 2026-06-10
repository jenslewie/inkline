from inkline.parsers.mineru.reconcile.footnotes.promote import split_page_footnote_blocks


def _body(block_id: str, page: int, markers: list[str]) -> dict:
    refs = [
        {
            "type": "note_ref",
            "marker": marker,
            "source": "equation_inline",
            "source_page": page,
        }
        for marker in markers
    ]
    return {
        "block_id": block_id,
        "type": "paragraph",
        "text": "正文",
        "source": {"page": page, "bbox": [70, 100, 850, 700]},
        "attrs": {"inline_runs": refs},
    }


def _footnote(block_id: str, page: int, text: str) -> dict:
    return {
        "block_id": block_id,
        "type": "footnote",
        "text": text,
        "source": {"page": page, "bbox": [73, 747, 846, 926]},
        "attrs": {"raw_type": "page_footnote", "role": "page_footnote"},
    }


def test_multiline_footnote_is_not_split_when_mineru_definition_count_matches_refs() -> None:
    blocks = [
        _body("b_body", 236, ["1", "2", "3"]),
        _footnote("b_note_1", 236, "1 第一行\n第二行\n第三行\n第四行"),
        _footnote("b_note_2", 236, "2 第二条"),
        _footnote("b_note_3", 236, "3 第三条"),
    ]

    split_page_footnote_blocks(blocks)

    assert [block["block_id"] for block in blocks] == [
        "b_body",
        "b_note_1",
        "b_note_2",
        "b_note_3",
    ]
    assert blocks[1]["text"] == "1 第一行\n第二行\n第三行\n第四行"


def test_definition_gap_allows_two_physical_lines_to_split() -> None:
    blocks = [
        _body("b_body", 22, ["1", "*"]),
        _footnote("b_note", 22, "1 第一条\n无文字 marker 的第二条"),
    ]

    split_page_footnote_blocks(blocks)

    assert [block["block_id"] for block in blocks] == ["b_body", "b_note", "b_note_2"]
    assert [block["text"] for block in blocks[1:]] == ["1 第一条", "无文字 marker 的第二条"]


def test_definition_gap_splits_only_at_later_marker_boundary() -> None:
    blocks = [
        _body("b_body", 62, ["1", "2"]),
        _footnote("b_note", 62, "1 第一条首行\n第一条续行\n2 第二条首行\n第二条续行"),
    ]

    split_page_footnote_blocks(blocks)

    assert [block["text"] for block in blocks[1:]] == [
        "1 第一条首行\n第一条续行",
        "2 第二条首行\n第二条续行",
    ]
    assert blocks[1]["attrs"]["split_reason"] == "page_footnote_explicit_line_marker"


def test_definition_gap_splits_embedded_marker_after_sentence_boundary() -> None:
    blocks = [
        _body("b_body", 63, ["1", "2"]),
        _footnote(
            "b_note",
            63,
            "1 第一条脚注的完整内容。2 第二条脚注的完整内容。",
        ),
    ]

    split_page_footnote_blocks(blocks)

    assert [block["block_id"] for block in blocks] == [
        "b_body",
        "b_note",
        "b_note_2",
    ]
    assert [block["text"] for block in blocks[1:]] == [
        "1 第一条脚注的完整内容。",
        "2 第二条脚注的完整内容。",
    ]


def test_embedded_citation_number_is_not_used_as_split_boundary() -> None:
    blocks = [
        _body("b_body", 63, ["1", "2"]),
        _footnote(
            "b_note",
            63,
            "1 Journal 3, no.2 (2005): 21-26. 第二条编号未出现在明确句末边界。",
        ),
    ]

    split_page_footnote_blocks(blocks)

    assert [block["block_id"] for block in blocks] == ["b_body", "b_note"]


def test_later_explicit_line_marker_splits_without_definition_gap() -> None:
    blocks = [
        _body("b_body", 277, ["1"]),
        _footnote(
            "b_note",
            277,
            "无可见编号的第一条。\n1 有明确编号的第二条。",
        ),
    ]

    split_page_footnote_blocks(blocks)

    assert [block["text"] for block in blocks[1:]] == [
        "无可见编号的第一条。",
        "1 有明确编号的第二条。",
    ]
    assert blocks[1]["attrs"]["split_reason"] == "page_footnote_explicit_line_marker"
