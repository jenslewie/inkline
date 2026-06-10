from inkline.parsers.mineru.reconcile.tables import reconcile_table_continuations


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
