"""Note marker regex patterns and candidates. Defines SECONDARY_MARKER_RE for detecting note markers in model/PDF text, along with visible note candidate enumeration, marker integer extraction, and punctuation boundary definitions."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from ...extraction.text import normalize_note_marker, normalize_ws


TERMINAL_PUNCTUATION = set("。！？；：.!?;:")
CLOSING_PUNCTUATION = set("」』”’）】》)]}")
QUOTE_BOUNDARY_PUNCTUATION = set("「『“‘")
SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
MAX_NOTE_MARKER_DIGITS = 3
BODY_TYPES = {"paragraph", "display_block", "blockquote", "caption", "epigraph_group"}
SECONDARY_MARKER_RE = re.compile(
    r"\\\(\s*\^\{(?P<latex>[^}]+)\}\s*\\\)|"
    r"\$\^\{(?P<dollar>[^}]+)\}\$|"
    r"\^\{(?P<brace>[^}]+)\}"
)

DISQUALIFY_NEXT_PREFIXES = (
    "%",
    "％",
    "‰",
    "世纪",
    "世紀",
    "年代",
    "年",
    "月",
    "日",
    "时",
    "時",
    "分",
    "秒",
    "项",
    "項",
    "件",
    "个",
    "個",
    "人",
    "名",
    "页",
    "頁",
    "章",
    "节",
    "節",
    "卷",
    "米",
    "公里",
    "千米",
    "万元",
    "美元",
    "元",
    "岁",
    "歲",
    "多",
    "余",
    "餘",
)


def _first_match_group(match: re.Match[str]) -> str:
    for group in match.groups():
        if group:
            return group
    return ""


def _marker_int(value: Any) -> Optional[int]:
    try:
        return int(normalize_note_marker(str(value or "")))
    except ValueError:
        return None


def _visible_note_candidates(text: str) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    index = 0
    while index < len(text):
        latex = _latex_marker_at(text, index)
        if latex is not None:
            end, marker = latex
            raw = text[index:end]
            if _is_candidate_marker(text, index, end, raw):
                out.append((raw, marker, "superscript_digit"))
            index = end
            continue
        if not _is_note_digit(text[index]):
            index += 1
            continue
        year_split_end = _note_before_year_end(text, index)
        end = year_split_end or index + 1
        if year_split_end is None:
            while end < len(text) and _is_note_digit(text[end]):
                end += 1
        raw = text[index:end]
        marker = _normalize_marker_digits(raw)
        if 1 <= len(marker) <= MAX_NOTE_MARKER_DIGITS and _is_candidate_marker(text, index, end, raw):
            reason = "superscript_digit" if _is_superscript_marker(raw) else "digit_after_terminal_punctuation"
            out.append((raw, marker, reason))
        index = end
    return out


def _strip_secondary_marker_markup(text: str) -> str:
    return normalize_ws(SECONDARY_MARKER_RE.sub("", text))


def _candidate_marker_offsets(text: str) -> List[int]:
    offsets: List[int] = []
    index = 0
    while index < len(text):
        if text[index] not in TERMINAL_PUNCTUATION:
            index += 1
            continue
        end = index + 1
        while end < len(text) and text[end] in CLOSING_PUNCTUATION:
            end += 1
        if not _next_text_disqualifies_marker(text[end:]):
            offsets.append(end)
        index = end
    return offsets


def _is_candidate_marker(text: str, start: int, end: int, raw_marker: str) -> bool:
    if start > 0 and _is_note_digit(text[start - 1]):
        return False
    split_before_year = _note_before_year_end(text, start) == end
    if end < len(text) and _is_note_digit(text[end]) and not split_before_year:
        return False
    if _next_text_disqualifies_marker(text[end:]) and not split_before_year:
        return False
    if _is_superscript_marker(raw_marker):
        return True
    return _has_terminal_left_boundary(text, start)


def _has_terminal_left_boundary(text: str, start: int) -> bool:
    index = start - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    while index >= 0 and text[index] in CLOSING_PUNCTUATION | QUOTE_BOUNDARY_PUNCTUATION:
        index -= 1
    return index >= 0 and text[index] in TERMINAL_PUNCTUATION


def _note_before_year_end(text: str, start: int) -> Optional[int]:
    if not _has_terminal_left_boundary(text, start):
        return None
    run_end = start
    while run_end < len(text) and _is_note_digit(text[run_end]):
        run_end += 1
    if run_end >= len(text) or text[run_end] != "年":
        return None
    marker_length = (run_end - start) - 4
    if 1 <= marker_length <= MAX_NOTE_MARKER_DIGITS:
        return start + marker_length
    return None


def _next_text_disqualifies_marker(next_text: str) -> bool:
    stripped = next_text.lstrip()
    if not stripped:
        return False
    if stripped[0].isdigit() or stripped[0].isascii() and stripped[0].isalpha():
        return True
    return any(stripped.startswith(prefix) for prefix in DISQUALIFY_NEXT_PREFIXES)


def _is_note_digit(char: str) -> bool:
    return char.isdigit() or char in "⁰¹²³⁴⁵⁶⁷⁸⁹"


def _normalize_digits(value: str) -> str:
    return value.translate(FULLWIDTH_DIGITS).translate(SUPERSCRIPT_DIGITS)


def _normalize_marker_digits(value: str) -> str:
    latex = _latex_marker_at(value, 0)
    if latex is not None and latex[0] == len(value):
        return latex[1]
    return _normalize_digits(value)


def _is_superscript_marker(value: str) -> bool:
    latex = _latex_marker_at(value, 0)
    if latex is not None and latex[0] == len(value):
        return True
    return bool(value) and all(char in "⁰¹²³⁴⁵⁶⁷⁸⁹" for char in value)


def _latex_marker_at(text: str, start: int) -> Optional[Tuple[int, str]]:
    for prefix, suffix in (("$^{", "}$"), ("^{", "}")):
        if not text.startswith(prefix, start):
            continue
        digit_start = start + len(prefix)
        digit_end = digit_start
        while digit_end < len(text) and _is_note_digit(text[digit_end]):
            digit_end += 1
        if digit_end == digit_start or not text.startswith(suffix, digit_end):
            continue
        return digit_end + len(suffix), _normalize_digits(text[digit_start:digit_end])
    return None


def _ends_with_terminal_or_quote(text: str) -> bool:
    stripped = text.strip()
    while stripped and stripped[-1] in CLOSING_PUNCTUATION | QUOTE_BOUNDARY_PUNCTUATION:
        stripped = stripped[:-1].rstrip()
    return bool(stripped and stripped[-1] in TERMINAL_PUNCTUATION)
