"""Pure read-only text offset calculation helpers for Qwen marker location.

All functions in this module are pure — they take primitive arguments and
return primitive results.  No block-dict mutation happens here.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from ...extraction.text import normalize_ws
from .marker_patterns import TERMINAL_PUNCTUATION, _marker_int


def _qwen_marker_offset_in_text(
    text: str, marker: str, before_text: str, after_text: str, quote_text: str = ""
) -> Optional[int]:
    before = normalize_ws(before_text)
    after = normalize_ws(after_text)
    quote = normalize_ws(quote_text)
    if not text or (not before and not after):
        return None
    visible_candidates = _qwen_visible_marker_offsets_with_context(text, marker, before, after)
    if len(visible_candidates) == 1:
        return visible_candidates[0]
    if visible_candidates:
        return None
    candidates: List[int] = []
    if after:
        start = 0
        while True:
            index = text.find(after, start)
            if index < 0:
                break
            visible_offset = _qwen_visible_marker_offset_before_after(text, marker, before, index)
            if visible_offset is not None:
                candidates.append(visible_offset)
                start = index + 1
                continue
            if not before or _qwen_prefix_matches_before(text[:index], before):
                candidates.append(
                    _qwen_adjusted_offset_between_before_after(
                        text, marker, before, after, quote, index
                    )
                )
            elif before:
                omitted_punctuation_offset = _qwen_offset_before_omitted_boundary_punctuation(
                    text, marker, before, after, quote, index
                )
                if omitted_punctuation_offset is not None:
                    candidates.append(omitted_punctuation_offset)
                    start = index + 1
                    continue
                omitted_terminal_offset = _qwen_offset_after_omitted_terminal_phrase(
                    text, before, index
                )
                if omitted_terminal_offset is not None:
                    candidates.append(omitted_terminal_offset)
                    start = index + 1
                    continue
                omitted_fragment_offset = _qwen_offset_after_short_omitted_fragment(
                    text, marker, before, quote, index
                )
                if omitted_fragment_offset is not None:
                    candidates.append(omitted_fragment_offset)
                    start = index + 1
                    continue
                punct_offset = _qwen_offset_around_punctuation(text, marker, before, index)
                if punct_offset is not None:
                    candidates.append(punct_offset)
            start = index + 1
        if not candidates and before:
            candidates.extend(
                _qwen_filter_before_only_offsets(
                    text, marker, after, quote, _qwen_offsets_after_before(text, before)
                )
            )
    elif before:
        candidates.extend(_qwen_offsets_after_before(text, before))
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return None
    return _qwen_marker_offset_in_normalized_text(text, marker, before, after, quote)


def _qwen_visible_marker_offsets_with_context(
    text: str, marker: str, before: str, after: str
) -> List[int]:
    candidates: List[int] = []
    for marker_text in _qwen_marker_text_variants(marker):
        start = 0
        while True:
            offset = text.find(marker_text, start)
            if offset < 0:
                break
            start = offset + 1
            if marker_text.startswith("*") and (
                (offset > 0 and text[offset - 1] == "*")
                or (
                    offset + len(marker_text) < len(text) and text[offset + len(marker_text)] == "*"
                )
            ):
                continue
            prefix = _qwen_text_without_neighbor_markers(text[:offset])
            suffix = _qwen_text_without_neighbor_markers(text[offset + len(marker_text) :])
            if before and not _qwen_prefix_matches_before(prefix, before):
                continue
            if after and not normalize_ws(suffix).startswith(after):
                continue
            candidates.append(offset)
    return sorted(set(candidates))


def _qwen_text_without_neighbor_markers(text: str) -> str:
    for marker_text in ("***", "**", "*"):
        text = text.replace(marker_text, "")
    return text.translate(str.maketrans("", "", "⁰¹²³⁴⁵⁶⁷⁸⁹"))


def _qwen_marker_offset_in_normalized_text(
    text: str, marker: str, before: str, after: str, quote: str
) -> Optional[int]:
    compact, offsets = _normalized_text_with_start_offsets(text)
    candidates: List[int] = []
    if after:
        start = 0
        while True:
            index = compact.find(after, start)
            if index < 0:
                break
            visible_offset = _qwen_visible_marker_offset_before_after(
                compact, marker, before, index
            )
            if visible_offset is not None and 0 <= visible_offset < len(offsets):
                candidates.append(offsets[visible_offset])
                start = index + 1
                continue
            if not before or _qwen_prefix_matches_before(compact[:index], before):
                adjusted_index = _qwen_adjusted_offset_between_before_after(
                    compact, marker, before, after, quote, index
                )
                if 0 <= adjusted_index < len(offsets):
                    candidates.append(offsets[adjusted_index])
                elif adjusted_index == len(offsets):
                    candidates.append(len(text))
            elif before:
                omitted_punctuation_offset = _qwen_offset_before_omitted_boundary_punctuation(
                    compact, marker, before, after, quote, index
                )
                if omitted_punctuation_offset is not None and 0 <= omitted_punctuation_offset < len(
                    offsets
                ):
                    candidates.append(offsets[omitted_punctuation_offset])
                    start = index + 1
                    continue
                omitted_fragment_offset = _qwen_offset_after_short_omitted_fragment(
                    compact, marker, before, quote, index
                )
                if omitted_fragment_offset is not None and 0 <= omitted_fragment_offset < len(
                    offsets
                ):
                    candidates.append(offsets[omitted_fragment_offset])
                    start = index + 1
                    continue
                punct_offset = _qwen_offset_around_punctuation(compact, marker, before, index)
                if punct_offset is not None and 0 <= punct_offset < len(offsets):
                    candidates.append(offsets[punct_offset])
            start = index + 1
        if not candidates and before:
            candidates.extend(
                _qwen_filter_before_only_offsets(
                    text,
                    marker,
                    after,
                    quote,
                    _qwen_offsets_after_before_in_normalized_text(text, compact, offsets, before),
                )
            )
    elif before:
        candidates.extend(
            _qwen_offsets_after_before_in_normalized_text(text, compact, offsets, before)
        )
    return candidates[0] if len(candidates) == 1 else None


def _qwen_offsets_after_before(text: str, before: str) -> List[int]:
    candidates: List[int] = []
    start = 0
    while True:
        index = text.find(before, start)
        if index < 0:
            break
        candidates.append(
            _qwen_offset_after_optional_closing_punctuation(text, index + len(before))
        )
        start = index + 1
    return candidates


def _qwen_offsets_after_before_in_normalized_text(
    text: str, compact: str, offsets: List[int], before: str
) -> List[int]:
    candidates: List[int] = []
    start = 0
    while True:
        index = compact.find(before, start)
        if index < 0:
            break
        end = index + len(before) - 1
        if 0 <= end < len(offsets):
            candidates.append(
                _qwen_offset_after_optional_closing_punctuation(text, offsets[end] + 1)
            )
        elif end == len(offsets):
            candidates.append(len(text))
        start = index + 1
    return candidates


def _qwen_offset_after_optional_closing_punctuation(text: str, offset: int) -> int:
    index = offset
    trailing = _qwen_trailing_closing_punctuation()
    while index < len(text) and text[index] in trailing:
        index += 1
    return index


def _qwen_adjusted_offset_between_before_after(
    text: str, marker: str, before: str, after: str, quote: str, after_index: int
) -> int:
    if _qwen_quote_places_marker_after_after(marker, after, quote):
        return after_index + len(after)
    title_prefix_offset = _qwen_offset_before_omitted_sentence_initial_title(
        text, marker, before, after, quote, after_index
    )
    if title_prefix_offset is not None:
        return title_prefix_offset
    suffix_offset = _qwen_offset_after_suffix_phrase(marker, before, after, quote, after_index)
    if suffix_offset is not None:
        return suffix_offset
    punctuation_offset = _qwen_offset_after_leading_punctuation(
        marker, before, after, quote, after_index
    )
    if punctuation_offset is not None:
        return punctuation_offset
    return after_index + _qwen_numeric_offset_after_leading_punctuation(marker, after, quote)


def _qwen_visible_marker_offset_before_after(
    text: str, marker: str, before: str, after_index: int
) -> Optional[int]:
    for marker_text in _qwen_marker_text_variants(marker):
        marker_start = after_index - len(marker_text)
        if marker_start < 0 or text[marker_start:after_index] != marker_text:
            continue
        if not before or _qwen_prefix_matches_before(text[:marker_start], before):
            return marker_start
    return None


def _qwen_visible_marker_at(text: str, marker: str, offset: int) -> str:
    for marker_text in _qwen_marker_text_variants(marker):
        if text[offset : offset + len(marker_text)] == marker_text:
            return marker_text
    return ""


def _qwen_numeric_offset_after_leading_punctuation(marker: str, after: str, quote: str) -> int:
    if marker.startswith("*") or not after or after[0] not in _qwen_boundary_punctuation():
        return 0
    if not _qwen_quote_places_numeric_after_leading_punctuation(marker, after, quote):
        return 0
    offset = 0
    trailing = _qwen_trailing_closing_punctuation()
    while offset < len(after) and (
        after[offset] in _qwen_boundary_punctuation() or after[offset] in trailing
    ):
        offset += 1
    return offset


def _qwen_quote_places_numeric_after_leading_punctuation(
    marker: str, after: str, quote: str
) -> bool:
    if not quote:
        return False
    offset = 0
    trailing = _qwen_trailing_closing_punctuation()
    while offset < len(after) and (
        after[offset] in _qwen_boundary_punctuation() or after[offset] in trailing
    ):
        offset += 1
    if offset <= 0:
        return False
    leading = after[:offset]
    remainder = after[offset:]
    for marker_text in _qwen_marker_text_variants(marker):
        if f"{leading}{marker_text}{remainder}" in quote:
            return True
    return False


def _qwen_quote_places_marker_after_after(marker: str, after: str, quote: str) -> bool:
    if not after or not quote:
        return False
    folded_after = _qwen_fold_bracket_width(after)
    folded_quote = _qwen_fold_bracket_width(quote)
    for marker_text in _qwen_marker_text_variants(marker):
        if f"{after}{marker_text}" in quote or f"{folded_after}{marker_text}" in folded_quote:
            return True
    return False


def _qwen_offset_before_omitted_sentence_initial_title(
    text: str,
    marker: str,
    before: str,
    after: str,
    quote: str,
    after_index: int,
) -> Optional[int]:
    if not _qwen_book_title_text(before) or not after or after_index <= len(before):
        return None
    if not _qwen_quote_places_marker_between_before_and_after(marker, before, after, quote):
        return None
    title_start = after_index - len(before)
    if text[title_start:after_index] != before:
        return None
    boundary_index = title_start - 1
    while boundary_index >= 0 and text[boundary_index].isspace():
        boundary_index -= 1
    while boundary_index >= 0 and text[boundary_index] in _qwen_trailing_closing_punctuation():
        boundary_index -= 1
    if boundary_index < 0 or text[boundary_index] not in TERMINAL_PUNCTUATION:
        return None
    return title_start


def _qwen_offset_after_suffix_phrase(
    marker: str, before: str, after: str, quote: str, after_index: int
) -> Optional[int]:
    if marker.startswith("*") or not before or not after or len(after) > 12:
        return None
    if not after.startswith("的") or after[-1] not in TERMINAL_PUNCTUATION:
        return None
    if not _qwen_quote_places_marker_between_before_and_after(marker, before, after, quote):
        return None
    return after_index + len(after)


def _qwen_offset_after_leading_punctuation(
    marker: str, before: str, after: str, quote: str, after_index: int
) -> Optional[int]:
    if marker.startswith("*") or not after or after[0] not in TERMINAL_PUNCTUATION:
        return None
    if not _qwen_quote_places_marker_between_before_and_after(marker, before, after, quote):
        return None
    return after_index + _offset_after_terminal_punctuation_cluster(after, 0)


def _qwen_book_title_text(text: str) -> bool:
    text = normalize_ws(text)
    return len(text) >= 3 and text.startswith("《") and text.endswith("》")


def _qwen_quote_places_marker_between_before_and_after(
    marker: str, before: str, after: str, quote: str
) -> bool:
    if not before or not after or not quote:
        return False
    folded_before = _qwen_fold_bracket_width(before)
    folded_after = _qwen_fold_bracket_width(after)
    folded_quote = _qwen_fold_bracket_width(quote)
    for marker_text in _qwen_marker_text_variants(marker):
        if (
            f"{before}{marker_text}{after}" in quote
            or f"{folded_before}{marker_text}{folded_after}" in folded_quote
        ):
            return True
    return False


def _qwen_marker_text_variants(marker: str) -> List[str]:
    variants = [marker]
    superscript = _qwen_superscript_marker(marker)
    if superscript and superscript not in variants:
        variants.append(superscript)
    return variants


def _qwen_superscript_marker(marker: str) -> str:
    if not marker.isdigit():
        return ""
    return marker.translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"))


def _qwen_offset_around_punctuation(
    text: str, marker: str, before: str, after_index: int
) -> Optional[int]:
    if after_index <= 0:
        return None
    prefix = text[:after_index]
    punctuation_start = len(prefix.rstrip(_qwen_boundary_punctuation()))
    if punctuation_start == len(prefix):
        return None
    if not _qwen_prefix_matches_before(prefix[:punctuation_start], before):
        return None
    return punctuation_start if marker.startswith("*") else after_index


def _qwen_offset_after_omitted_terminal_phrase(
    text: str, before: str, after_index: int
) -> Optional[int]:
    before = normalize_ws(before)
    if not before or after_index <= 0:
        return None
    prefix = text[:after_index]
    prefix_content_end = len(prefix.rstrip())
    before_start = prefix.rfind(before, 0, prefix_content_end)
    if before_start < 0:
        return None
    fragment_start = before_start + len(before)
    fragment = prefix[fragment_start:prefix_content_end]
    if not fragment or len(fragment) > 16:
        return None
    terminal_offsets = [
        index for index, char in enumerate(fragment) if char in TERMINAL_PUNCTUATION
    ]
    if not terminal_offsets:
        return None
    terminal_index = terminal_offsets[-1]
    tail = fragment[terminal_index + 1 :]
    if tail.strip(_qwen_trailing_closing_punctuation()):
        return None
    return fragment_start + terminal_index + 1


def _qwen_offset_before_omitted_boundary_punctuation(
    text: str,
    marker: str,
    before: str,
    after: str,
    quote: str,
    after_index: int,
) -> Optional[int]:
    before = normalize_ws(before)
    after = normalize_ws(after)
    if not before or not after or not quote or after_index <= 0:
        return None
    prefix = text[:after_index]
    before_start = prefix.rfind(before)
    if before_start < 0:
        return None
    marker_offset = before_start + len(before)
    fragment = prefix[marker_offset:]
    if (
        not fragment
        or len(fragment) > 4
        or fragment.strip(_qwen_boundary_punctuation() + _qwen_trailing_closing_punctuation())
    ):
        return None
    folded_before = _qwen_fold_bracket_width(before)
    folded_after = _qwen_fold_bracket_width(after)
    folded_fragment = _qwen_fold_bracket_width(fragment)
    folded_quote = _qwen_fold_bracket_width(quote)
    for marker_text in _qwen_marker_text_variants(marker):
        if f"{before}{marker_text}{after}" in quote:
            return marker_offset
        if f"{before}{marker_text}{fragment}{after}" in quote:
            return marker_offset
        if f"{folded_before}{marker_text}{folded_after}" in folded_quote:
            return marker_offset
        if f"{folded_before}{marker_text}{folded_fragment}{folded_after}" in folded_quote:
            return marker_offset
    return None


def _qwen_filter_before_only_offsets(
    text: str, marker: str, after: str, quote: str, offsets: Sequence[int]
) -> List[int]:
    if _marker_int(marker) is None or not after or not quote:
        return list(offsets)
    folded_after = _qwen_fold_bracket_width(after)
    folded_quote = _qwen_fold_bracket_width(quote)
    if after not in quote and folded_after not in folded_quote:
        return list(offsets)
    return [
        offset
        for offset in offsets
        if not (0 <= offset < len(text) and text[offset] in TERMINAL_PUNCTUATION)
    ]


def _qwen_offset_after_short_omitted_fragment(
    text: str, marker: str, before: str, quote: str, after_index: int
) -> Optional[int]:
    before = normalize_ws(before)
    if not marker.startswith("*") or not before or not quote or after_index <= 0:
        return None
    if not any(
        f"{before}{marker_text}" in quote for marker_text in _qwen_marker_text_variants(marker)
    ):
        return None
    prefix = text[:after_index]
    before_start = prefix.rfind(before)
    if before_start < 0:
        return None
    fragment = prefix[before_start + len(before) :]
    if (
        len(fragment) != 1
        or fragment.isspace()
        or fragment in TERMINAL_PUNCTUATION
        or fragment in _qwen_trailing_closing_punctuation()
    ):
        return None
    return after_index


def _qwen_prefix_matches_before(prefix: str, before: str) -> bool:
    normalized = normalize_ws(prefix)
    before = normalize_ws(before)
    if _qwen_prefix_text_matches(normalized, before):
        return True
    if normalized.rstrip(_qwen_trailing_closing_punctuation()).endswith(before):
        return True
    for suffix in _qwen_before_suffixes(before):
        if _qwen_prefix_text_matches(normalized, suffix):
            return True
        if normalized.rstrip(_qwen_trailing_closing_punctuation()).endswith(suffix):
            return True
    return False


def _qwen_prefix_text_matches(prefix: str, before: str) -> bool:
    if prefix.endswith(before):
        return True
    return _qwen_fold_bracket_width(prefix).endswith(_qwen_fold_bracket_width(before))


def _qwen_fold_bracket_width(text: str) -> str:
    return text.translate(str.maketrans({"(": "（", ")": "）", "[": "［", "]": "］"}))


def _qwen_before_suffixes(before: str) -> List[str]:
    before = normalize_ws(before)
    suffixes: List[str] = []
    for length in range(min(8, len(before) - 1), 2, -1):
        suffix = before[-length:]
        if suffix and suffix not in suffixes:
            suffixes.append(suffix)
    return suffixes


def _qwen_boundary_punctuation() -> str:
    return "".join(sorted(TERMINAL_PUNCTUATION | {"，", "、", ",", "；", ";", "：", ":"}))


def _qwen_trailing_closing_punctuation() -> str:
    return "”’」』）】》〉〕〗｝)]}]}"


def _normalized_text_with_start_offsets(text: str) -> Tuple[str, List[int]]:
    chars: List[str] = []
    offsets: List[int] = []
    last_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if last_space:
                continue
            chars.append(" ")
            offsets.append(index)
            last_space = True
            continue
        chars.append(char)
        offsets.append(index)
        last_space = False
    joined = "".join(chars)
    leading = len(joined) - len(joined.lstrip())
    trailing = len(joined.rstrip())
    return joined[leading:trailing], offsets[leading:trailing]


def _text_ends_with_normalized(text: str, suffix: str) -> bool:
    return normalize_ws(text).endswith(normalize_ws(suffix))


def _text_starts_with_normalized(text: str, prefix: str) -> bool:
    return normalize_ws(text).startswith(normalize_ws(prefix))


def _text_ends_with_normalized_ignoring_trailing_punctuation(text: str, suffix: str) -> bool:
    normalized = normalize_ws(text).rstrip(_qwen_boundary_punctuation())
    return normalized.endswith(normalize_ws(suffix))


def _offset_after_terminal_punctuation_cluster(text: str, offset: int) -> int:
    if offset < 0 or offset >= len(text) or text[offset] not in TERMINAL_PUNCTUATION:
        return offset
    index = offset + 1
    trailing = _qwen_trailing_closing_punctuation()
    while index < len(text) and text[index] in trailing:
        index += 1
    return index
