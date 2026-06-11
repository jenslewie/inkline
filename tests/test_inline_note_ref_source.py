from inkline.parsers.mineru.reconcile.notes.resolver import resolve_note_links


def test_invalid_inline_ref_removes_matching_legacy_fallback() -> None:
    inline_ref = {
        "type": "note_ref",
        "marker": "%",
        "source": "equation_inline",
        "source_page": 1,
    }
    blocks = [
        {
            "block_id": "b_body",
            "type": "paragraph",
            "text": "正文",
            "source": {"page": 1},
            "attrs": {
                "note_refs": [{key: value for key, value in inline_ref.items() if key != "type"}],
                "inline_runs": [
                    {"type": "text", "text": "正文"},
                    inline_ref,
                ],
            },
        },
        {
            "block_id": "b_note",
            "type": "footnote",
            "text": "% 非脚注内容",
            "source": {"page": 1},
            "attrs": {"role": "page_footnote", "note_marker": "%"},
        },
    ]

    resolve_note_links(blocks)

    attrs = blocks[0]["attrs"]
    assert "inline_runs" not in attrs
    assert "note_refs" not in attrs
    assert attrs["suppressed_note_refs"][0]["suppress_reason"] == "not_a_note_marker"
