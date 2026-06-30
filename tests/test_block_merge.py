from inkline.parsers.mineru.reconcile.block_merge import (
    _merge_block_pair,
    _refresh_display_block_attrs,
)
from inkline.parsers.mineru.schema.block_types import DISPLAY_BLOCK


def test_merge_block_pair_rebases_right_inline_note_offset() -> None:
    left_text = "最近几十年来考古学家拼合了上千件类似的文书。这些文书"
    right_text = "用汉语、梵语，以及其他死语言写成。"
    right_prefix = "用汉语、梵语"
    left = {
        "block_id": "b000064",
        "type": "paragraph",
        "text": left_text,
        "source": {"page": 16, "bbox": None},
        "attrs": {"raw_type": "paragraph"},
    }
    note_ref = {
        "marker": "*",
        "source": "equation_inline",
        "source_page": 17,
        "raw_marker": "^{*}",
    }
    right = {
        "block_id": "b000065",
        "type": "paragraph",
        "text": right_text,
        "source": {"page": 17, "bbox": None},
        "attrs": {
            "raw_type": "paragraph",
            "inline_runs": [
                {"type": "text", "text": right_prefix + "  "},
                {**note_ref, "type": "note_ref"},
                {"type": "text", "text": " ，以及其他死语言写成。"},
            ],
        },
    }

    _merge_block_pair(
        left,
        right,
        "cross_page_paragraph_continuation",
        {"left_ends_with_terminal_punctuation": False},
        [],
    )

    assert left["text"] == left_text + right_text
    assert "note_refs" not in left["attrs"]
    assert [run["type"] for run in left["attrs"]["inline_runs"]] == ["text", "note_ref", "text"]
    assert left["attrs"]["inline_runs"][0]["text"].endswith(right_prefix + "  ")


def test_refresh_display_block_attrs_preserves_footnote_merge_display_reason() -> None:
    block = {
        "block_id": "b001634",
        "type": DISPLAY_BLOCK,
        "text": "更欲镌龛一所，踌躇瞻眺，余所竟无，唯此一岭，磋峨可劈激地祇于下，龟筮告吉，揆日兴工。",
        "source": {"page": 253, "bbox": [170, 106, 888, 812], "pages": [253, 254]},
        "attrs": {
            "merge_reason": "cross_page_paragraph_continuation_across_footnote",
            "merge_evidence": {"left_ends_with_terminal_punctuation": False},
        },
    }

    _refresh_display_block_attrs(block)

    assert block["type"] == DISPLAY_BLOCK
    assert block["attrs"]["merge_reason"] == "display_block_continuation_across_footnotes"
    assert block["attrs"]["merge_evidence"] == {"footnote_interrupted_display_block": True}
