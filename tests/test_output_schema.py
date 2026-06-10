from inkline.parsers.mineru.analysis.note_gap_report import build_note_ref_gap_report
from inkline.parsers.mineru.normalize.output_schema import remove_internal_note_ref_indexes


def test_remove_internal_note_ref_indexes_keeps_inline_note_refs() -> None:
    inline_ref = {
        "type": "note_ref",
        "marker": "*",
        "source": "equation_inline",
        "source_page": 17,
        "target_note_id": "note_b000071",
    }
    blocks = [
        {
            "block_id": "b000064",
            "type": "paragraph",
            "text": "正文",
            "source": {"page": 17, "bbox": None},
            "attrs": {
                "note_refs": [{key: value for key, value in inline_ref.items() if key != "type"}],
                "inline_runs": [
                    {"type": "text", "text": "正"},
                    inline_ref,
                    {"type": "text", "text": "文"},
                ],
            },
        },
        {
            "block_id": "b_display",
            "type": "display_block",
            "text": "引文",
            "source": {"page": 18, "bbox": None},
            "attrs": {
                "items": [
                    {
                        "text": "引文",
                        "note_refs": [{"marker": "1"}],
                        "inline_runs": [{"type": "note_ref", "marker": "1"}],
                    }
                ]
            },
        },
    ]

    remove_internal_note_ref_indexes(blocks)

    assert "note_refs" not in blocks[0]["attrs"]
    assert blocks[0]["attrs"]["inline_runs"][1] == inline_ref
    assert "note_refs" not in blocks[1]["attrs"]["items"][0]


def test_note_gap_report_reads_public_inline_note_refs() -> None:
    document = {
        "metadata": {"doc_id": "sample", "title": "Sample"},
        "blocks": [
            {
                "block_id": "b_body",
                "type": "paragraph",
                "text": "正文",
                "source": {"page": 1, "bbox": None},
                "attrs": {
                    "inline_runs": [
                        {"type": "text", "text": "正"},
                        {
                            "type": "note_ref",
                            "marker": "1",
                            "source": "equation_inline",
                            "source_page": 1,
                            "target_note_id": "note_b_note",
                            "target_block_id": "b_note",
                        },
                        {"type": "text", "text": "文"},
                    ]
                },
            },
            {
                "block_id": "b_note",
                "type": "footnote",
                "text": "脚注",
                "source": {"page": 1, "bbox": None},
                "attrs": {"note_id": "note_b_note", "note_marker": "1"},
            },
        ],
    }

    report = build_note_ref_gap_report(document)

    assert report["summary"]["referenced_notes"] == 1
    assert report["summary"]["unresolved_body_note_refs"] == 0
