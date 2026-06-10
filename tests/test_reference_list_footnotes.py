from inkline.parsers.mineru.reconcile.footnotes.promote import (
    promote_page_reference_list_footnotes,
    recover_unmarked_page_footnote_markers,
)
from inkline.parsers.mineru.reconcile.footnotes.merge import merge_continuation_footnotes
from inkline.parsers.mineru.reconcile.notes.resolver import resolve_note_links


def _body_block(block_id: str, markers: list[str]) -> dict:
    return {
        "block_id": block_id,
        "type": "paragraph",
        "text": "正文",
        "source": {"page": 137, "bbox": [100, 100, 880, 700]},
        "attrs": {
            "note_refs": [
                {
                    "marker": marker,
                    "source": "equation_inline",
                    "source_page": 137,
                }
                for marker in markers
            ],
            "inline_runs": [
                {
                    "type": "note_ref",
                    "marker": marker,
                    "source": "equation_inline",
                    "source_page": 137,
                }
                for marker in markers
            ],
        },
    }


def _reference_item(block_id: str, text: str) -> dict:
    return {
        "block_id": block_id,
        "type": "list_item",
        "text": text,
        "source": {"page": 137, "bbox": [112, 728, 883, 906]},
        "attrs": {
            "raw_type": "list_item",
            "list_type": "reference_list",
        },
    }


def test_reference_list_uses_body_marker_order_for_unmarked_item() -> None:
    texts = [
        "1 第一条注释。",
        "solidus，一种金币形制。",
        "2 第二条注释。",
        "3 第三条注释。",
    ]
    blocks = [_body_block("b_body", ["1", "*", "2", "3"])]
    blocks.extend(
        _reference_item(f"b_note_{index}", text)
        for index, text in enumerate(texts)
    )

    promote_page_reference_list_footnotes(blocks)
    resolve_note_links(blocks)

    notes = blocks[1:]
    assert [block["type"] for block in notes] == ["footnote"] * 4
    assert [block["attrs"]["note_marker"] for block in notes] == ["1", "*", "2", "3"]
    assert notes[1]["attrs"]["note_marker_source"] == "reference_list_order"
    assert [ref["target_block_id"] for ref in blocks[0]["attrs"]["note_refs"]] == [
        "b_note_0",
        "b_note_1",
        "b_note_2",
        "b_note_3",
    ]


def test_reference_list_does_not_guess_when_marker_order_disagrees() -> None:
    texts = ["1 第一条注释。", "无标记条目。", "2 第二条注释。"]
    blocks = [_body_block("b_body", ["1", "2", "*"])]
    blocks.extend(
        _reference_item(f"b_note_{index}", text)
        for index, text in enumerate(texts)
    )

    promote_page_reference_list_footnotes(blocks)

    assert [block["type"] for block in blocks[1:]] == ["footnote", "footnote", "footnote"]
    assert "note_marker" not in blocks[2]["attrs"]


def test_middle_marker_order_prevents_unmarked_footnote_from_merging() -> None:
    blocks = [
        _body_block("b_body", ["1", "*", "2"]),
        {
            "block_id": "b_note_1",
            "type": "footnote",
            "text": "1 第一条注释。",
            "source": {"page": 137, "bbox": [112, 728, 883, 750]},
            "attrs": {
                "raw_type": "ref_text",
                "role": "page_footnote",
                "_middle_page_inline_markers": ["1", "*", "2"],
            },
        },
        {
            "block_id": "b_note_star",
            "type": "footnote",
            "text": "solidus，一种金币形制。",
            "source": {"page": 137, "bbox": [120, 751, 883, 770]},
            "attrs": {
                "raw_type": "ref_text",
                "role": "page_footnote",
                "_middle_page_inline_markers": ["1", "*", "2"],
            },
        },
        {
            "block_id": "b_note_2",
            "type": "footnote",
            "text": "2 第二条注释。",
            "source": {"page": 137, "bbox": [112, 771, 883, 795]},
            "attrs": {
                "raw_type": "ref_text",
                "role": "page_footnote",
                "_middle_page_inline_markers": ["1", "*", "2"],
            },
        },
    ]

    recover_unmarked_page_footnote_markers(blocks)
    merge_continuation_footnotes(blocks)

    assert [block["block_id"] for block in blocks[1:]] == [
        "b_note_1",
        "b_note_star",
        "b_note_2",
    ]
    assert blocks[2]["attrs"]["note_marker"] == "*"
    assert blocks[2]["attrs"]["note_marker_source"] == "mineru_inline_equation_order"
