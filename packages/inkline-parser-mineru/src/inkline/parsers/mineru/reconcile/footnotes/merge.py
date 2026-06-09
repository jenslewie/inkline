"""Footnote merging. Handles deduplication of adjacent identical footnotes, merging same-page unmarked continuation footnotes, and merging explicit cross-page footnotes (marked with 接下页/接上页). Contains _merge_footnote_pair() and continuation marker detection."""

from __future__ import annotations

from typing import Dict, List

from ...normalize.builders import union_bbox
from ...extraction.text import normalize_ws
from ..block_access import block_bbox as _bbox, block_page as _block_page
from ..notes.keys import leading_note_marker as _leading_note_marker

_FN_CONT_Y_GAP_MIN = -5.0
_FN_CONT_Y_GAP_MAX = 45.0
_FN_CONT_X_OFFSET_STD = 8.0
_FN_CONT_X_OFFSET_LOOSE = -5.0


def merge_continuation_footnotes(blocks: List[Dict[str, Any]]) -> None:
    _drop_duplicate_adjacent_footnotes(blocks)
    _merge_same_page_unmarked_footnotes(blocks)
    _merge_explicit_cross_page_footnotes(blocks)
    _drop_duplicate_adjacent_footnotes(blocks)
    _merge_same_page_unmarked_footnotes(blocks)


def _drop_duplicate_adjacent_footnotes(blocks: List[Dict[str, Any]]) -> None:
    i = 0
    while i + 1 < len(blocks):
        cur = blocks[i]
        nxt = blocks[i + 1]
        if cur.get("type") != "footnote" or nxt.get("type") != "footnote":
            i += 1
            continue
        if _block_page(cur) != _block_page(nxt):
            i += 1
            continue
        if _compact_footnote_text(cur.get("text", "")) != _compact_footnote_text(nxt.get("text", "")):
            i += 1
            continue
        _merge_duplicate_footnote_attrs(cur, nxt)
        del blocks[i + 1]
        continue
    i += 1


def _compact_footnote_text(text: str) -> str:
    return "".join(normalize_ws(str(text or "")).split())


def _merge_duplicate_footnote_attrs(left: Dict[str, Any], right: Dict[str, Any]) -> None:
    attrs = left.setdefault("attrs", {})
    right_attrs = right.get("attrs") or {}
    attrs["deduped_duplicate_block_id"] = right.get("block_id")
    for key in ("referenced_by", "merged_from"):
        values = list(attrs.get(key) or [])
        for value in right_attrs.get(key) or []:
            if value and value not in values:
                values.append(value)
        if values:
            attrs[key] = values


def _merge_same_page_unmarked_footnotes(blocks: List[Dict[str, Any]]) -> None:
    i = 0
    while i + 1 < len(blocks):
        cur = blocks[i]
        nxt = blocks[i + 1]
        if (
            cur.get("type") == "footnote"
            and nxt.get("type") == "footnote"
            and _block_page(cur) == _block_page(nxt)
            and _leading_note_marker(nxt.get("text", "")) is None
            and (_leading_note_marker(cur.get("text", "")) is not None or _has_next_page_continuation(cur) or _has_previous_page_continuation(cur))
            and _is_footnote_continuation_layout(cur, nxt)
        ):
            _merge_footnote_pair(cur, nxt, "same_page_unmarked_footnote_continuation")
            del blocks[i + 1]
            continue
        i += 1


def _merge_explicit_cross_page_footnotes(blocks: List[Dict[str, Any]]) -> None:
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") != "footnote" or not _has_next_page_continuation(cur):
            i += 1
            continue
        cp = _block_page(cur)
        j = i + 1
        while j < len(blocks):
            nxt = blocks[j]
            np = _block_page(nxt)
            if np is not None and cp is not None and np > cp + 1:
                break
            if nxt.get("type") == "footnote" and np == (cp or 0) + 1 and _has_previous_page_continuation(nxt):
                previous_fragment = nxt
                _merge_footnote_pair(cur, nxt, "explicit_cross_page_footnote_continuation")
                del blocks[j]
                while (
                    j < len(blocks)
                    and blocks[j].get("type") == "footnote"
                    and _block_page(blocks[j]) == np
                    and _leading_note_marker(blocks[j].get("text", "")) is None
                    and _is_footnote_continuation_layout(previous_fragment, blocks[j])
                ):
                    previous_fragment = blocks[j]
                    _merge_footnote_pair(cur, blocks[j], "explicit_cross_page_footnote_continuation")
                    del blocks[j]
                break
            j += 1
        i += 1


def _has_next_page_marker(text: str) -> bool:
    return "接下页" in str(text or "")


def _has_previous_page_marker(text: str) -> bool:
    return "接上页" in str(text or "")


def _has_next_page_continuation(blk: Dict[str, Any]) -> bool:
    return _has_next_page_marker(blk.get("text", "")) or bool((blk.get("attrs") or {}).get("continues_on_next_page"))


def _has_previous_page_continuation(blk: Dict[str, Any]) -> bool:
    return _has_previous_page_marker(blk.get("text", "")) or bool((blk.get("attrs") or {}).get("continues_from_previous_page"))


def _clean_continuation_markers(text: str) -> str:
    text = normalize_ws(text)
    for marker in ["（接下页）", "(接下页)", "接下页", "（接上页）", "(接上页)", "接上页"]:
        text = text.replace(marker, "")
    return normalize_ws(text)


def _is_footnote_continuation_layout(cur: Dict[str, Any], nxt: Dict[str, Any]) -> bool:
    cbb = _bbox(cur)
    nbb = _bbox(nxt)
    if not cbb or not nbb:
        return True
    y_gap = float(nbb[1]) - float(cbb[3])
    if not (_FN_CONT_Y_GAP_MIN <= y_gap <= _FN_CONT_Y_GAP_MAX):
        return False
    if _has_next_page_continuation(cur) or _has_previous_page_continuation(cur):
        return float(nbb[0]) >= float(cbb[0]) + _FN_CONT_X_OFFSET_LOOSE
    return float(nbb[0]) >= float(cbb[0]) + _FN_CONT_X_OFFSET_STD


def _merge_footnote_pair(left: Dict[str, Any], right: Dict[str, Any], reason: str) -> None:
    left_next = _has_next_page_continuation(left) or _has_next_page_continuation(right)
    left_prev = _has_previous_page_continuation(left) or _has_previous_page_continuation(right)
    left_text = _clean_continuation_markers(left.get("text", ""))
    right_text = _clean_continuation_markers(right.get("text", ""))
    left["text"] = "\n".join(part for part in [left_text, right_text] if part)
    source = left.setdefault("source", {})
    spans = source.setdefault("spans", [])
    if not spans:
        spans.append({"page": source.get("page"), "bbox": source.get("bbox"), "block_id": left.get("block_id")})
    right_source = right.get("source") or {}
    right_spans = right_source.get("spans") or []
    if right_spans:
        spans.extend(right_spans)
    else:
        spans.append({
            "page": right_source.get("page"),
            "bbox": right_source.get("bbox"),
            "block_id": right.get("block_id"),
        })
    source["bbox"] = union_bbox([source.get("bbox"), (right.get("source") or {}).get("bbox")])
    pages = source.setdefault("pages", [source.get("page")])
    for page in (right.get("source") or {}).get("pages") or [(right.get("source") or {}).get("page")]:
        if page is not None and page not in pages:
            pages.append(page)
    attrs = left.setdefault("attrs", {})
    if left_next:
        attrs["continues_on_next_page"] = True
    if left_prev:
        attrs["continues_from_previous_page"] = True
    if reason == "explicit_cross_page_footnote_continuation":
        attrs.pop("continues_on_next_page", None)
        attrs.pop("continues_from_previous_page", None)
    merged = attrs.setdefault("merged_from", [])
    right_merged = (right.get("attrs") or {}).get("merged_from") or []
    for bid in [left.get("block_id"), right.get("block_id")] + list(right_merged):
        if bid and bid not in merged:
            merged.append(bid)
    attrs["merge_reason"] = reason
