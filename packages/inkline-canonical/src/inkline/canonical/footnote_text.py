from __future__ import annotations

import re
from typing import Any

# Superscript-to-digit translation table, matching the normalization
# used in the parser's normalize_note_marker().
_SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

# Required-delimiter pattern for footnote marker stripping.
# After a marker, at least one delimiter must follow to avoid false
# positives (e.g. "3rd" is NOT stripped when marker is "3").
# Covers: whitespace, period/dot, comma, Chinese punctuation (、．),
# closing paren (ASCII and fullwidth ), and end-of-string.
_DELIMITER_PATTERN = r"(?:[\s.、．,)）]\s*|$)"


def strip_footnote_marker(text: str, attrs: dict[str, Any] | None = None) -> str:
    """Strip the leading original note marker from footnote block text.

    Footnotes from the canonical pipeline often include the original
    marker (e.g. "³ Lothar..." or "3. Note text") as the first word
    or two.  Downstream consumers (EPUB renderer, RAG chunker) provide
    their own numbering or indexing, so the duplicate leading marker
    should be removed.

    When attrs.note_marker is available (the most reliable source), it
    is used.  Otherwise a local heuristic strips a leading sequence
    matching common marker patterns.

    This is a **display-layer** concern — canonical footnote.text
    preserves the original marker for traceability; this function is
    called by downstream consumers that need clean text.
    """
    attrs = attrs or {}

    marker = attrs.get("note_marker")
    if isinstance(marker, str) and marker:
        marker_stripped = marker.strip()
        if not marker_stripped:
            pass  # empty marker — skip to fallback
        else:
            # Normalize the leading superscript run in the text to its
            # digit equivalent, then match the marker against the
            # normalised form.  This handles multi-digit superscript
            # sequences (e.g. ¹² → "12") and single superscripts
            # (³ → "3") equally.
            m = re.match(
                r"^([¹²³⁴⁵⁶⁷⁸⁹⁰]+)",
                text,
            )
            if m:
                normalized_head = m.group(1).translate(_SUPERSCRIPT_MAP)
                if normalized_head == marker_stripped:
                    # Consume the superscript run plus delimiter
                    delim_m = re.match(
                        rf"^[¹²³⁴⁵⁶⁷⁸⁹⁰]+{_DELIMITER_PATTERN}",
                        text,
                    )
                    if delim_m:
                        rest = text[delim_m.end():]
                        if rest:
                            return rest
            # Literal marker form — must be followed by a required delimiter
            # so "3rd" is NOT stripped when marker is "3".
            pattern = rf"^({re.escape(marker_stripped)}){_DELIMITER_PATTERN}"
            m2 = re.match(pattern, text)
            if m2:
                rest = text[m2.end():]
                if rest:
                    return rest
    # Fallback (no note_marker attr): strip a leading marker-like prefix.
    #
    # Plain-ASCII-digit runs are limited to 1-2 digits to avoid stripping
    # year- or quantity-like text ("755 年" / "1999 年" should NOT become
    # "年").  3-digit footnote markers without a note_marker attr are rare
    # in practice; the parser normally provides it.  Non-digit markers
    # (circled/boxed digits, superscript, symbols) have no such limit and
    # are matched greedily.
    m = re.match(
        rf"^(?:\d{{1,2}}|[①-⓿❶-➓¹²³⁴⁵⁶⁷⁸⁹⁰\*†‡§]+){_DELIMITER_PATTERN}",
        text,
    )
    if m and m.end() > 0:
        rest = text[m.end():]
        if rest:
            return rest
    return text
