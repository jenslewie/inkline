"""Tests for strip_footnote_marker — the shared canonical helper used by
EPUB rendering and RAG chunking to remove leading footnote markers from
display text.

Canonical footnote.text preserves original markers for traceability;
strip_footnote_marker is a display-layer operation that downstream
consumers call when they need clean text."""

from inkline.canonical import strip_footnote_marker

# ── note_marker attr present ─────────────────────────────────────────


def test_marker_star_with_space():
    """'* note' → 'note' when note_marker='*'"""
    assert strip_footnote_marker("* note", {"note_marker": "*"}) == "note"


def test_marker_digit_with_period():
    """'1. note' → 'note' when note_marker='1'"""
    assert strip_footnote_marker("1. note", {"note_marker": "1"}) == "note"


def test_marker_digit_with_space():
    """'1 注释。' → '注释。' when note_marker='1'"""
    assert strip_footnote_marker("1 注释。", {"note_marker": "1"}) == "注释。"


def test_marker_superscript_digit():
    """'³ text' → 'text' when note_marker='3'"""
    assert strip_footnote_marker("³ text", {"note_marker": "3"}) == "text"


def test_marker_multi_digit_superscript():
    """'¹² explanation' → 'explanation' when note_marker='12'"""
    assert strip_footnote_marker("¹² explanation", {"note_marker": "12"}) == "explanation"


def test_marker_multi_digit_literal():
    """'12 more text' → 'more text' when note_marker='12'"""
    assert strip_footnote_marker("12 more text", {"note_marker": "12"}) == "more text"


# ── No note_marker attr — heuristic fallback ────────────────────────


def test_fallback_digit_with_space():
    """'1 note' → 'note' (heuristic, no note_marker)"""
    assert strip_footnote_marker("1 note") == "note"


def test_fallback_digit_with_period():
    """'1. note' → 'note' (heuristic)"""
    assert strip_footnote_marker("1. note") == "note"


def test_fallback_star_with_space():
    """'* text' → 'text' (heuristic)"""
    assert strip_footnote_marker("* text") == "text"


def test_fallback_double_star():
    """'** text' → 'text' (heuristic)"""
    assert strip_footnote_marker("** text") == "text"


def test_fallback_superscript_no_marker_attr():
    """'³ Lothar was here' → 'Lothar was here' (heuristic)"""
    assert strip_footnote_marker("³ Lothar was here") == "Lothar was here"


def test_fallback_dagger():
    """'† dagger note' → 'dagger note' (heuristic)"""
    assert strip_footnote_marker("† dagger note") == "dagger note"


def test_fallback_section_sign():
    """'§ section note' → 'section note' (heuristic)"""
    assert strip_footnote_marker("§ section note") == "section note"


# ── Negative: should NOT strip ──────────────────────────────────────


def test_no_strip_3rd_edition():
    """'3rd edition' must NOT be stripped (no delimiter after '3')"""
    assert strip_footnote_marker("3rd edition") == "3rd edition"


def test_no_strip_3rd_edition_with_marker_attr():
    """'3rd edition' unchanged even when note_marker='3' (no delimiter)"""
    assert strip_footnote_marker("3rd edition", {"note_marker": "3"}) == "3rd edition"


def test_no_strip_plain_number_no_delimiter():
    """'3text' unchanged — digit directly followed by letters, no delimiter"""
    assert strip_footnote_marker("3text") == "3text"


def test_no_strip_regular_text():
    """Regular text without any marker pattern should be unchanged"""
    assert strip_footnote_marker("这是一段正文。") == "这是一段正文。"


def test_no_strip_text_starting_with_year():
    """'1999年发生了大事' should not be stripped (4-digit year, no space)"""
    assert strip_footnote_marker("1999年发生了大事") == "1999年发生了大事"


def test_no_strip_year_with_space():
    """'1999 年发生了大事' should not be stripped (4-digit year + space)"""
    assert strip_footnote_marker("1999 年发生了大事") == "1999 年发生了大事"


def test_no_strip_three_digit_historical_year():
    """'755 年...' should not be stripped (3-digit year + space)"""
    assert strip_footnote_marker("755 年安史之乱爆发") == "755 年安史之乱爆发"


# ── Edge cases ──────────────────────────────────────────────────────


def test_empty_marker_attr_falls_to_heuristic():
    """Empty note_marker string triggers heuristic fallback"""
    assert strip_footnote_marker("1 note", {"note_marker": ""}) == "note"


def test_none_marker_attr_falls_to_heuristic():
    """None note_marker triggers heuristic fallback"""
    assert strip_footnote_marker("1 note", {"note_marker": None}) == "note"


def test_none_attrs_defaults_to_empty():
    """attrs=None defaults to {} (heuristic fallback)"""
    assert strip_footnote_marker("1 note", None) == "note"


def test_no_attrs_defaults_to_empty():
    """No attrs argument defaults to heuristic"""
    assert strip_footnote_marker("1 note") == "note"


def test_marker_stripped_returns_empty_rest():
    """If marker matches but rest would be empty, return original text"""
    # "1" alone → heuristic finds "1" + end-of-string delimiter, rest=""
    # Should return original text since rest is empty
    assert strip_footnote_marker("1") == "1"


def test_marker_with_chinese_delimiter():
    """'1、列举项目' → '列举项目' when note_marker='1'"""
    assert strip_footnote_marker("1、列举项目", {"note_marker": "1"}) == "列举项目"


def test_marker_with_fullwidth_period():
    """'1．说明' → '说明' when note_marker='1'"""
    assert strip_footnote_marker("1．说明", {"note_marker": "1"}) == "说明"


def test_marker_with_closing_paren():
    """'1) item' → 'item' when note_marker='1'"""
    assert strip_footnote_marker("1) item", {"note_marker": "1"}) == "item"


def test_marker_with_fullwidth_closing_paren():
    """'1）项目' → '项目' when note_marker='1'"""
    assert strip_footnote_marker("1）项目", {"note_marker": "1"}) == "项目"


# ── RAG chunking footnote stripping ─────────────────────────────────


def test_rag_footnote_chunk_strips_marker():
    """Footnote block text in RAG chunks should have marker removed."""
    from inkline.canonical import sample_document
    from inkline.rag.chunks import build_chunks

    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000010",
            "type": "heading",
            "text": "Chapter",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b000011",
            "type": "paragraph",
            "text": "正文内容。",
            "source": {"page": 1},
            "attrs": {},
        },
        {
            "block_id": "b000012",
            "type": "footnote",
            "text": "1 脚注内容。",
            "source": {"page": 1},
            "attrs": {"note_marker": "1", "note_id": "note_1"},
        },
    ]

    chunks = list(build_chunks(document))
    # There should be at least one chunk containing the footnote text
    fn_chunks = [c for c in chunks if "b000012" in c.get("block_ids", [])]
    assert fn_chunks
    # The footnote text in the chunk should NOT start with "1 "
    chunk_text = fn_chunks[0]["text"]
    footnote_line = next(line for line in chunk_text.split("\n\n") if "脚注内容" in line)
    assert footnote_line == "脚注内容。"


def test_rag_footnote_chunk_star_marker():
    """Footnote with '*' marker in RAG chunk should strip it."""
    from inkline.canonical import sample_document
    from inkline.rag.chunks import build_chunks

    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_fn",
            "type": "footnote",
            "text": "* asterisk note",
            "source": {"page": 1},
            "attrs": {"note_marker": "*", "note_id": "note_star"},
        },
    ]

    chunks = list(build_chunks(document))
    fn_chunks = [c for c in chunks if "b_fn" in c.get("block_ids", [])]
    assert fn_chunks
    assert fn_chunks[0]["text"] == "asterisk note"
