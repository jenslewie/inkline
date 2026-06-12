"""Shared display block helpers and regex patterns."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ..block_access import block_bbox as _bbox, block_page as _block_page
from ..block_merge import _merge_block_pair, _refresh_canonical_quote_attrs
from ..block_nav import _prev_text_non_float
from ...extraction.text import normalize_ws

ERA_MONTH_RE = re.compile(r"^\s*[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]年[正一二三四五六七八九十冬腊]+月\s*$")
LUNAR_DAY_ENTRY_RE = re.compile(
    r"^\s*(?:初[一二三四五六七八九十]|十[一二三四五六七八九]?|二十[一二三四五六七八九]?|三十)日?[甲乙丙丁戊己庚辛壬癸]?[子丑寅卯辰巳午未申酉戌亥]?\b"
)
PAREN_TIME_HEADER_RE = re.compile(r"^\s*[（(][^）)]{1,24}?时[）)]\s*$")
DATE_LINE_RE = re.compile(r"^\s*\d{3,4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$")
NAME_LABEL_LINE_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9·•]{2,18}\s*[：:]\s*$")


def is_era_month_header(block: Dict[str, Any], layout: LayoutStats) -> bool:
    if block.get("type") == "heading":
        return False
    text = str(block.get("text", "")).strip()
    if not ERA_MONTH_RE.match(text):
        return False
    bb = _bbox(block)
    if not bb:
        return True
    bbox_width = float(bb[2]) - float(bb[0])
    if bbox_width > layout.body_width * 0.85:
        return False
    return True


def is_lunar_day_entry(block: Dict[str, Any], layout: LayoutStats) -> bool:
    if block.get("type") == "heading":
        return False
    text = str(block.get("text", "")).strip()
    return bool(LUNAR_DAY_ENTRY_RE.match(text))


def is_parenthetical_time_header(text: str) -> bool:
    return bool(PAREN_TIME_HEADER_RE.match(text or ""))


def force_generic_display_attrs(
    b: Dict[str, Any],
    prev_text: str = "",
    evidence: str = "layout_defined_display_block",
) -> None:
    if b.get("type") == "heading":
        b.pop("level", None)
    b["type"] = "display_block"
    _refresh_canonical_quote_attrs(b, prev_text=prev_text)
    attrs = b.setdefault("attrs", {})
    attrs["layout_role"] = "inline_display_block"
    ev = attrs.setdefault("classification_evidence", [])
    if evidence not in ev:
        ev.append(evidence)


def merge_display_run(
    blocks: List[Dict[str, Any]],
    start: int,
    end_exclusive: int,
    prev_text: str = "",
    reason: str = "generic_layout_display_block_run",
) -> int:
    if start < 0 or start >= len(blocks) or end_exclusive <= start:
        return start + 1
    cur = blocks[start]
    force_generic_display_attrs(cur, prev_text=prev_text, evidence=reason)
    while start + 1 < end_exclusive and start + 1 < len(blocks):
        nxt = blocks[start + 1]
        _merge_block_pair(cur, nxt, reason, {"layout_run": True}, [], joiner="newline")
        del blocks[start + 1]
        end_exclusive -= 1
    force_generic_display_attrs(cur, prev_text=prev_text, evidence=reason)
    return start + 1


# ── display quote continuation helpers ──────────────────────────────────────


def display_run_is_intro_continuation_candidate(b: Dict[str, Any], layout: LayoutStats) -> bool:
    from ..layout_helpers import _canonical_quote_layout

    if b.get("type") != "display_block":
        return False
    return _canonical_quote_layout(b, layout) or bool(_bbox(b))


def is_short_display_text_block(b: Dict[str, Any], layout: LayoutStats, max_len: int = 120) -> bool:
    from ..layout_helpers import _canonical_quote_layout

    if b.get("type") not in {"paragraph", "display_block"}:
        return False
    text = str(b.get("text", "")).strip()
    if not text or len(text) > max_len:
        return False
    bb = _bbox(b)
    if bb:
        width = max(0.0, float(bb[2]) - float(bb[0]))
        near_body_indent = float(bb[0]) <= layout.body_left + max(48.0, layout.body_width * 0.055)
        body_width = width >= layout.body_width * 0.88
        if near_body_indent and body_width:
            return False
    return _canonical_quote_layout(b, layout) or (_bbox(b) is not None and float(_bbox(b)[0]) >= layout.body_left + 35)


def is_left_shifted_intro_before_display_lane_ds(blocks: List[Dict[str, Any]], i: int, layout: LayoutStats) -> bool:
    b = blocks[i]
    if b.get("type") != "paragraph":
        return False
    bb = _bbox(b)
    text = normalize_ws(str(b.get("text", "")))
    if not bb or not text or len(text) > 80 or not text.endswith(("：", ":")):
        return False
    if i + 1 >= len(blocks):
        return False
    nxt = blocks[i + 1]
    nbb = _bbox(nxt)
    if nxt.get("type") != "display_block" or not nbb:
        return False
    if _block_page(nxt) != _block_page(b):
        return False
    next_width = max(0.0, float(nbb[2]) - float(nbb[0]))
    left_shift = float(nbb[0]) - float(bb[0])
    if left_shift < max(34.0, layout.body_width * 0.04):
        return False
    if float(bb[0]) > layout.body_left + max(82.0, layout.body_width * 0.1):
        return False
    current_width = max(0.0, float(bb[2]) - float(bb[0]))
    compact_next = next_width <= layout.body_width * 0.58
    return compact_next and (current_width >= next_width * 1.15 or current_width >= layout.body_width * 0.25)


def looks_like_record_display_text(text: str) -> bool:
    lines = [ln.strip() for ln in str(text or "").split("\n") if ln.strip()]
    if len(lines) < 3:
        return False
    if max(len(ln) for ln in lines) > 42:
        return False
    date_count = sum(bool(DATE_LINE_RE.match(ln)) for ln in lines)
    label_count = sum(bool(NAME_LABEL_LINE_RE.match(ln)) for ln in lines)
    short_ratio = sum(len(ln) <= 24 for ln in lines) / max(1, len(lines))
    if date_count >= 1 and (label_count >= 1 or short_ratio >= 0.75):
        return True
    if date_count >= 2 and short_ratio >= 0.65:
        return True
    return False


def display_quote_multiline_seed(text: str) -> bool:
    lines = [ln.strip() for ln in str(text or "").split("\n") if ln.strip()]
    if len(lines) < 2:
        return False
    if looks_like_record_display_text(text):
        return True
    return max(len(ln) for ln in lines) <= 60 and (sum(len(ln) <= 36 for ln in lines) / len(lines)) >= 0.6


def has_display_attribution_line(text: str) -> bool:
    lines = [ln.strip() for ln in str(text or "").split("\n") if ln.strip()]
    return any(ln.startswith(("——", "--", "- ")) for ln in lines[1:])


def is_single_line_display_continuation_fragment(block: Dict[str, Any], layout: LayoutStats) -> bool:
    text = str(block.get("text", "")).strip()
    bb = _bbox(block)
    if not text or "\n" in text or not bb:
        return False
    height = float(bb[3]) - float(bb[1])
    width = float(bb[2]) - float(bb[0])
    return height <= 30.0 and len(text) <= 60 and width <= layout.body_width * 0.55


def display_lanes_compatible(left: Dict[str, Any], right: Dict[str, Any], layout: LayoutStats) -> bool:
    lbb = _bbox(left)
    rbb = _bbox(right)
    if not lbb or not rbb:
        return False
    left_x0 = float(lbb[0])
    right_x0 = float(rbb[0])
    if abs(left_x0 - right_x0) <= max(36.0, layout.body_width * 0.05):
        return True
    left_width = max(0.0, float(lbb[2]) - left_x0)
    right_width = max(0.0, float(rbb[2]) - right_x0)
    left_compact = left_width <= layout.body_width * 0.58
    right_compact = right_width <= layout.body_width * 0.58
    return left_compact and right_compact and left_x0 >= layout.body_left + 70 and right_x0 >= layout.body_left + 70


_force_generic_quote_attrs = force_generic_display_attrs
force_generic_quote_attrs = force_generic_display_attrs
_is_era_month_header = is_era_month_header
_is_lunar_day_entry = is_lunar_day_entry
_merge_quote_run = merge_display_run
merge_quote_run = merge_display_run
quote_run_is_intro_continuation_candidate = display_run_is_intro_continuation_candidate
