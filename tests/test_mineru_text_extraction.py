from inkline.parsers.mineru.extraction.text import extract_text_notes_and_runs


def test_extracts_numeric_inline_equation_as_note_ref() -> None:
    text, notes, runs = extract_text_notes_and_runs(
        [
            {"type": "text", "content": "正文"},
            {"type": "equation_inline", "content": "^{3}"},
            {"type": "text", "content": "继续"},
        ]
    )

    assert text == "正文继续"
    assert [note.marker for note in notes] == ["3"]
    assert [run["type"] for run in runs] == ["text", "note_ref", "text"]


def test_preserves_non_note_inline_equation_as_text() -> None:
    text, notes, runs = extract_text_notes_and_runs(
        [
            {"type": "text", "content": "字母 "},
            {"type": "equation_inline", "content": r"\theta"},
            {"type": "text", "content": " 的发音"},
        ]
    )

    assert text == "字母 θ 的发音"
    assert notes == []
    assert runs == [{"type": "text", "text": "字母 θ 的发音"}]


def test_extracts_combined_numeric_star_marker_as_note_ref() -> None:
    text, notes, runs = extract_text_notes_and_runs(
        [{"type": "equation_inline", "content": "^{1*}"}]
    )

    assert text == ""
    assert [note.marker for note in notes] == ["1*"]
    assert runs == [
        {
            "type": "note_ref",
            "marker": "1*",
            "raw_marker": "^{1*}",
            "source": "equation_inline",
        }
    ]


def test_preserves_complex_non_note_equation_verbatim() -> None:
    text, notes, runs = extract_text_notes_and_runs(
        [{"type": "equation_inline", "content": r"x^{2}+y^{2}"}]
    )

    assert text == r"x^{2}+y^{2}"
    assert notes == []
    assert runs == [{"type": "text", "text": r"x^{2}+y^{2}"}]


def test_collapses_mineru_prose_wraps_inside_single_text_run() -> None:
    text, notes, runs = extract_text_notes_and_runs(
        [
            {
                "type": "text",
                "content": (
                    "在一片低矮的沙丘中，出现了古代果树枯萎的树干。继续往北走\n"
                    "了不到两英里，我很快就看到了最先出现的两间旧屋"
                ),
            }
        ]
    )

    assert text == (
        "在一片低矮的沙丘中，出现了古代果树枯萎的树干。继续往北走"
        "了不到两英里，我很快就看到了最先出现的两间旧屋"
    )
    assert notes == []
    assert runs == [{"type": "text", "text": text}]


def test_preserves_short_structural_newlines_inside_single_text_run() -> None:
    text, notes, runs = extract_text_notes_and_runs(
        [{"type": "text", "content": "502—640年\n鞠氏高昌"}]
    )

    assert text == "502—640年\n鞠氏高昌"
    assert notes == []
    assert runs == [{"type": "text", "text": "502—640年\n鞠氏高昌"}]
