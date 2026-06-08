from mineru_normalizer.canonical.builders import make_paragraph
from mineru_normalizer.schema.models import IdFactory, NoteRef, RawBlock


def test_make_paragraph_copies_equation_inline_offset_to_note_ref() -> None:
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
    ref = paragraph["attrs"]["note_refs"][0]

    assert ref["inline_position"] == "exact"
    assert ref["inline_position_source"] == "equation_inline"
    assert ref["inline_position_confidence"] == "high"
    assert ref["inline_offset"] == 1


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
    ref = paragraph["attrs"]["note_refs"][0]

    assert paragraph["text"] == "正文。"
    assert ref["source"] == "trailing_text"
    assert ref["inline_position"] == "exact"
    assert ref["inline_position_source"] == "trailing_text"
    assert ref["inline_position_confidence"] == "high"
    assert ref["inline_offset"] == len("正文。")


def test_make_paragraph_offsets_match_normalized_canonical_text() -> None:
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
    ref = paragraph["attrs"]["note_refs"][0]

    assert paragraph["text"] == "甲 乙"
    assert ref["inline_offset"] == len("甲")
