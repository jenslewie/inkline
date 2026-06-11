from inkline.parsers.mineru.normalize.builders import make_paragraph
from inkline.parsers.mineru.schema.models import IdFactory, NoteRef, RawBlock


def test_make_paragraph_preserves_equation_inline_run_order() -> None:
    block = RawBlock(
        page=1,
        index=0,
        raw_type="paragraph",
        text="甲乙",
        bbox=None,
        raw={},
        note_refs=[NoteRef(marker="1", source="equation_inline", raw_marker="^{1}")],
        inline_runs=[
            {"type": "text", "text": "甲"},
            {"type": "note_ref", "marker": "1", "source": "equation_inline", "raw_marker": "^{1}"},
            {"type": "text", "text": "乙"},
        ],
    )

    paragraph = make_paragraph(IdFactory(), block)
    assert "note_refs" not in paragraph["attrs"]
    assert paragraph["attrs"]["inline_runs"] == [
        {"type": "text", "text": "甲"},
        {
            "type": "note_ref",
            "marker": "1",
            "source": "equation_inline",
            "raw_marker": "^{1}",
            "source_page": 1,
        },
        {"type": "text", "text": "乙"},
    ]


def test_make_paragraph_copies_trailing_text_offset_to_note_ref() -> None:
    block = RawBlock(
        page=1,
        index=0,
        raw_type="paragraph",
        text="正文。2",
        bbox=None,
        raw={},
    )

    paragraph = make_paragraph(IdFactory(), block)
    ref = paragraph["attrs"]["inline_runs"][-1]

    assert paragraph["text"] == "正文。"
    assert ref["source"] == "trailing_text"
    assert "inline_offset" not in ref
    assert ref["type"] == "note_ref"


def test_make_paragraph_keeps_mineru_runs_when_text_is_normalized() -> None:
    block = RawBlock(
        page=1,
        index=0,
        raw_type="paragraph",
        text="甲  乙",
        bbox=None,
        raw={},
        note_refs=[NoteRef(marker="1", source="equation_inline", raw_marker="^{1}")],
        inline_runs=[
            {"type": "text", "text": "甲  "},
            {"type": "note_ref", "marker": "1", "source": "equation_inline", "raw_marker": "^{1}"},
            {"type": "text", "text": "乙"},
        ],
    )

    paragraph = make_paragraph(IdFactory(), block)
    assert paragraph["text"] == "甲 乙"
    assert paragraph["attrs"]["inline_runs"][0]["text"] == "甲  "
    assert paragraph["attrs"]["inline_runs"][1]["type"] == "note_ref"
