from inkline.parsers.mineru.reconcile.block_merge import _merge_block_pair


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
