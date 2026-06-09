"""Note marker extraction and key generation. Extracts leading note markers from text (digits, asterisks, superscript), generates note_ref keys for deduplication, and provides Chinese numeral to integer conversion."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ...extraction.text import normalize_note_marker, normalize_ws


_CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def note_ref_key(ref: Dict[str, Any]) -> tuple[str, str, int | None]:
    source_page = ref.get("source_page")
    return (
        str(ref.get("marker") or ""),
        str(ref.get("source") or ""),
        int(source_page) if isinstance(source_page, int) else None,
    )


def leading_note_marker(text: str, include_superscript: bool = False) -> Optional[str]:
    text = normalize_ws(text or "")
    if not text:
        return None
    if include_superscript:
        m = re.match(r"^([\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u2070]+)", text)
        if m:
            return normalize_note_marker(m.group(1))
    m = re.match(r"^([*\uff0a]{1,3})", text)
    if m:
        return normalize_note_marker(m.group(1).replace("\uff0a", "*"))
    m = re.match(r"^(\d{1,3})(?=$|\s|[.\uff0e\uff61\u3001)%)\uff09\u300a\u300e\u201c\"'\u2018\u300c\u300e])", text)
    if m:
        return normalize_note_marker(m.group(1))
    head = text.split(" ", 1)[0].rstrip(".\uff0e\uff61\u3001)")
    if head.isdigit() and len(head) <= 3:
        return normalize_note_marker(head)
    if set(head) <= {"*", "\uff0a"}:
        return normalize_note_marker(head.replace("\uff0a", "*"))
    return None


def chinese_to_int(text: str) -> Optional[int]:
    if not text:
        return None
    if text in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[text]
    if text == "十":
        return 10
    if "十" in text:
        left, right = text.split("十", 1)
        tens = _CHINESE_DIGITS.get(left, 1) if left else 1
        ones = _CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return None
