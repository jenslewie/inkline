from inkline.parsers.mineru.reconcile.table import (
    _is_table_continuation_marker,
    reconcile_table_continuations,
)


def test_table_continuation_preserves_intervening_page_footnote() -> None:
    blocks = [
        {
            "block_id": "b_table_1",
            "type": "table",
            "text": "表3.1",
            "source": {"page": 141, "bbox": [115, 239, 879, 884]},
            "attrs": {
                "html": "<table><tr><td>第一页</td></tr></table>",
                "caption": "表3.1",
                "footnotes": ["(接下页)"],
            },
        },
        {
            "block_id": "b_note_1",
            "type": "footnote",
            "text": "1 Skaff, “Sasanian and Arab-Sasanian Silver Coins”, 93.",
            "source": {"page": 141, "bbox": [115, 916, 566, 931]},
            "attrs": {"raw_type": "page_footnote", "role": "page_footnote"},
        },
        {
            "block_id": "b_table_2",
            "type": "table",
            "text": "(接上页)",
            "source": {"page": 142, "bbox": [103, 93, 870, 685]},
            "attrs": {
                "html": "<table><tr><td>第二页</td></tr></table>",
                "caption": "(接上页)",
                "footnotes": ["资料来源：表格资料。"],
            },
        },
    ]

    reconcile_table_continuations(blocks)

    assert [block["block_id"] for block in blocks] == ["b_table_1", "b_note_1"]
    assert blocks[0]["attrs"]["footnotes"] == ["(接下页)", "资料来源：表格资料。"]
    assert blocks[0]["attrs"]["continuation_block_ids"] == ["b_table_2"]
    assert blocks[1]["type"] == "footnote"
    assert blocks[1]["text"] == "1 Skaff, “Sasanian and Arab-Sasanian Silver Coins”, 93."


def test_table_continuation_notes_exclude_markers() -> None:
    """table_notes should exclude continuation markers even when they exist
    in footnotes. continuation_marker_block_ids should track marker paragraphs."""
    blocks = [
        {
            "block_id": "b_table_1",
            "type": "table",
            "text": "表3.2",
            "source": {"page": 101, "bbox": [100, 200, 800, 884]},
            "attrs": {
                "html": "<table><tr><td>Left</td></tr></table>",
                "caption": "表3.2",
                "footnotes": ["(接下页)"],
            },
        },
        {
            "block_id": "b_marker",
            "type": "paragraph",
            "text": "（接下页）",
            "source": {"page": 101, "bbox": [100, 920, 500, 940]},
            "attrs": {"raw_type": "page_footer"},
        },
        {
            "block_id": "b_note_2",
            "type": "footnote",
            "text": "1 Test note.",
            "source": {"page": 101, "bbox": [100, 950, 700, 970]},
            "attrs": {"raw_type": "page_footnote", "role": "page_footnote"},
        },
        {
            "block_id": "b_table_2",
            "type": "table",
            "text": "(接上页)",
            "source": {"page": 102, "bbox": [103, 93, 870, 685]},
            "attrs": {
                "html": "<table><tr><td>Right</td></tr></table>",
                "caption": "(接上页)",
                "footnotes": ["Source note", "接上页"],
            },
        },
    ]

    reconcile_table_continuations(blocks)

    assert [block["block_id"] for block in blocks] == ["b_table_1", "b_note_2"]
    merged = blocks[0]["attrs"]
    # table_notes should exclude continuation markers
    assert "table_notes" in merged
    for note in merged["table_notes"]:
        assert not _is_table_continuation_marker(note)
    # Real notes should be present in table_notes
    assert "Source note" in merged["table_notes"]
    # footnotes still contains everything (including markers) for backward compat
    assert "(接下页)" in merged["footnotes"]
    # continuation_marker_block_ids should track the marker paragraph
    assert "continuation_marker_block_ids" in merged
    assert merged["continuation_marker_block_ids"] == ["b_marker"]


def test_is_table_continuation_marker() -> None:
    """Verify continuation marker detection covers expected forms."""
    assert _is_table_continuation_marker("接上页")
    assert _is_table_continuation_marker("(接上页)")
    assert _is_table_continuation_marker("（接上页）")
    assert _is_table_continuation_marker("接下页")
    assert _is_table_continuation_marker("(接下页)")
    assert _is_table_continuation_marker("续表")
    assert _is_table_continuation_marker("续上表")
    assert _is_table_continuation_marker("【接上页】")
    assert not _is_table_continuation_marker("Source note")
    assert not _is_table_continuation_marker("资料来源")
    assert not _is_table_continuation_marker("")
    assert not _is_table_continuation_marker(None)