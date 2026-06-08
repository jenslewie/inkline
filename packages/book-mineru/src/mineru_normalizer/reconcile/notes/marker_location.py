"""Evidence extraction and cross-block body-ref location for Qwen markers.

Functions here locate a note marker's inline position within block text
(using offset helpers from marker_offsets) and extract source evidence
from Qwen page items.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ...extraction.text import normalize_note_marker, normalize_ws
from .marker_inline import _InlineMarkerLocation, _note_refs
from .marker_offsets import (
    _qwen_fold_bracket_width,
    _qwen_marker_offset_in_text,
    _qwen_marker_text_variants,
    _qwen_visible_marker_at,
    _text_ends_with_normalized,
    _text_ends_with_normalized_ignoring_trailing_punctuation,
    _text_starts_with_normalized,
)
from .marker_patterns import BODY_TYPES, TERMINAL_PUNCTUATION, _marker_int
from .scopes import _NoteContext


def _qwen_marker_page_items(qwen_marker_pages: Any) -> List[Dict[str, Any]]:
    if isinstance(qwen_marker_pages, dict):
        items = qwen_marker_pages.get("pages") or []
    else:
        items = qwen_marker_pages
    out: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        elif hasattr(item, "to_json"):
            converted = item.to_json()
            if isinstance(converted, dict):
                out.append(converted)
    return out


def _locate_qwen_body_ref(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
    page: int,
    marker: str,
    item: Dict[str, Any],
    *,
    allow_existing: bool = False,
) -> Optional[Tuple[Dict[str, Any], _InlineMarkerLocation]]:
    before = str(item.get("before_text") or "")
    after = str(item.get("after_text") or "")
    before_for_match = _qwen_context_without_neighbor_markers(before)
    after_for_match = _qwen_context_without_neighbor_markers(after)
    quote = str(item.get("quote") or "")
    requested_block_id = str(item.get("block_id") or "")
    candidates: List[Tuple[int, Dict[str, Any], _InlineMarkerLocation]] = []
    for block_index, block in enumerate(blocks):
        if block.get("type") not in BODY_TYPES or page not in context.pages_for(block):
            continue
        if requested_block_id and _qwen_block_id(block) != requested_block_id:
            continue
        if not allow_existing and _existing_ref_marker_on_page(block, marker, page, context):
            continue
        text = str(block.get("text") or "")
        offset = _qwen_marker_offset_in_text(text, marker, before_for_match, after_for_match, quote)
        if offset is None:
            continue
        visible_marker = _qwen_visible_marker_at(text, marker, offset)
        candidates.append(
            (
                block_index,
                block,
                _InlineMarkerLocation(
                    char_index=offset,
                    source="qwen_marker_locator",
                    confidence=str(item.get("confidence") or "candidate"),
                    evidence={
                        "inline_position_source": "qwen_marker_locator",
                        "inline_position_confidence": str(item.get("confidence") or "candidate"),
                        "inline_position_offset": offset,
                        "qwen_marker": marker,
                        "qwen_quote": quote,
                        **_qwen_body_ref_source_evidence(item),
                        **_qwen_matching_context_evidence(before, after, before_for_match, after_for_match),
                        **(
                            {
                                "qwen_visible_marker_offset": offset,
                                "qwen_visible_marker_text": visible_marker,
                                "qwen_visible_marker_stripped": True,
                            }
                            if visible_marker
                            else {}
                        ),
                    },
                ),
            )
        )
    if len(candidates) == 1:
        _index, block, inline_location = candidates[0]
        return block, inline_location
    if candidates:
        return None
    if requested_block_id:
        return None
    return _locate_qwen_cross_block_body_ref(blocks, context, page, marker, item, allow_existing=allow_existing)


def _qwen_block_id(block: Dict[str, Any]) -> str:
    return str(block.get("block_id") or block.get("id") or "")


def _qwen_body_ref_source_evidence(item: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for source_key, evidence_key in (
        ("block_id", "qwen_block_id"),
        ("body_ref_source", "qwen_body_ref_source"),
        ("crop_image", "qwen_crop_image"),
        ("crop_bbox_pdf", "qwen_crop_bbox_pdf"),
    ):
        value = item.get(source_key)
        if value:
            out[evidence_key] = value
    return out


def _qwen_context_without_neighbor_markers(value: str) -> str:
    text = str(value or "")
    for marker_text in ("***", "**", "*"):
        text = text.replace(marker_text, "")
    superscript_digits = str.maketrans("", "", "⁰¹²³⁴⁵⁶⁷⁸⁹")
    return text.translate(superscript_digits)


def _qwen_matching_context_evidence(before: str, after: str, before_for_match: str, after_for_match: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if before != before_for_match:
        out["qwen_matching_before_text"] = before_for_match
    if after != after_for_match:
        out["qwen_matching_after_text"] = after_for_match
    return out


def _existing_ref_marker_on_page(block: Dict[str, Any], marker: str, page: int, context: _NoteContext) -> bool:
    for ref in _note_refs(block):
        if normalize_note_marker(ref.get("marker", "")) != marker:
            continue
        source_page = ref.get("source_page")
        if isinstance(source_page, int):
            if source_page == page:
                return True
            continue
        source_pages = ref.get("source_pages")
        if isinstance(source_pages, list):
            pages = {value for value in source_pages if isinstance(value, int)}
            if pages:
                if page in pages:
                    return True
                continue
        if page in context.pages_for(block):
            return True
    return False


def _locate_qwen_cross_block_body_ref(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
    page: int,
    marker: str,
    item: Dict[str, Any],
    *,
    allow_existing: bool = False,
) -> Optional[Tuple[Dict[str, Any], _InlineMarkerLocation]]:
    before = normalize_ws(_qwen_context_without_neighbor_markers(str(item.get("before_text") or "")))
    after = normalize_ws(_qwen_context_without_neighbor_markers(str(item.get("after_text") or "")))
    quote = normalize_ws(str(item.get("quote") or ""))
    if not before or not after:
        return None
    page_blocks = [
        block
        for block in blocks
        if block.get("type") in BODY_TYPES
        and page in context.pages_for(block)
        and normalize_ws(str(block.get("text") or ""))
    ]
    matches: List[Tuple[Dict[str, Any], _InlineMarkerLocation]] = []
    for left, right in zip(page_blocks, page_blocks[1:]):
        if not allow_existing and _existing_ref_marker_on_page(left, marker, page, context):
            continue
        left_text = str(left.get("text") or "")
        right_text = str(right.get("text") or "")
        if not _text_ends_with_normalized(left_text, before) and not _text_ends_with_normalized_ignoring_trailing_punctuation(left_text, before):
            continue
        if not _text_starts_with_normalized(right_text, after):
            continue
        offset = _qwen_cross_block_marker_offset(left_text, marker, before, after, quote)
        matches.append(
            (
                left,
                _InlineMarkerLocation(
                    char_index=offset,
                    source="qwen_marker_locator",
                    confidence=str(item.get("confidence") or "candidate"),
                    evidence={
                        "inline_position_source": "qwen_marker_locator",
                        "inline_position_confidence": str(item.get("confidence") or "candidate"),
                        "inline_position_offset": offset,
                        "qwen_marker": marker,
                        "qwen_quote": str(item.get("quote") or ""),
                        "qwen_cross_block_after_text": after,
                    },
                ),
            )
        )
    return matches[0] if len(matches) == 1 else None


def _qwen_cross_block_marker_offset(text: str, marker: str, before: str, after: str, quote: str) -> int:
    default_offset = len(text)
    if _marker_int(marker) is None or not before or not after or not quote:
        return default_offset
    stripped = normalize_ws(text)
    if not stripped or stripped[-1] not in TERMINAL_PUNCTUATION:
        return default_offset
    if not stripped[:-1].endswith(before):
        return default_offset
    folded_before = _qwen_fold_bracket_width(before)
    folded_after = _qwen_fold_bracket_width(after)
    folded_quote = _qwen_fold_bracket_width(quote)
    marker_is_between_contexts = any(
        f"{before}{marker_text}{after}" in quote
        or f"{folded_before}{marker_text}{folded_after}" in folded_quote
        for marker_text in _qwen_marker_text_variants(marker)
    )
    if not marker_is_between_contexts:
        return default_offset
    for index in range(len(text) - 1, -1, -1):
        if text[index].isspace():
            continue
        if text[index] in TERMINAL_PUNCTUATION:
            return index
        break
    return default_offset