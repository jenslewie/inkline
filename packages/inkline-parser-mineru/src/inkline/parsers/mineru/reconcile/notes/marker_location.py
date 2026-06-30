"""Evidence extraction and cross-block body-ref location for Qwen markers.

Functions here locate a note marker's inline position within block text
(using offset helpers from marker_offsets) and extract source evidence
from Qwen page items.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from ...extraction.text import normalize_note_marker, normalize_ws
from ...schema.models import CanonicalBlock
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


class _QwenBodyRefMatchInputs(NamedTuple):
    page: int
    marker: str
    item: Dict[str, Any]
    before: str
    after: str
    before_for_match: str
    after_for_match: str
    quote: str
    requested_block_id: str
    allow_existing: bool


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
    out.sort(
        key=lambda evidence: (
            not any(
                isinstance(item, dict) and item.get("block_id")
                for item in evidence.get("body_refs") or []
            )
        )
    )
    return out


def _locate_qwen_body_ref(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
    page: int,
    marker: str,
    item: Dict[str, Any],
    *,
    allow_existing: bool = False,
) -> Optional[Tuple[CanonicalBlock, _InlineMarkerLocation]]:
    before = str(item.get("before_text") or "")
    after = str(item.get("after_text") or "")
    match_inputs = _QwenBodyRefMatchInputs(
        page=page,
        marker=marker,
        item=item,
        before=before,
        after=after,
        before_for_match=_qwen_context_without_neighbor_markers(before),
        after_for_match=_qwen_context_without_neighbor_markers(after),
        quote=str(item.get("quote") or ""),
        requested_block_id=str(item.get("block_id") or ""),
        allow_existing=allow_existing,
    )
    requested_candidates: List[Tuple[int, CanonicalBlock, _InlineMarkerLocation]] = []
    fallback_candidates: List[Tuple[int, CanonicalBlock, _InlineMarkerLocation]] = []
    for block_index, block in enumerate(blocks):
        candidate = _qwen_body_ref_candidate(block_index, block, context, match_inputs)
        if candidate is None:
            continue
        block_id_matches_request = bool(
            match_inputs.requested_block_id
            and _qwen_block_id(block) == match_inputs.requested_block_id
        )
        target_candidates = (
            fallback_candidates
            if match_inputs.requested_block_id and not block_id_matches_request
            else requested_candidates
        )
        target_candidates.append(candidate)
    candidates = requested_candidates
    if match_inputs.requested_block_id and not candidates:
        candidates = fallback_candidates
        crop_match = _select_candidate_by_crop_geometry(candidates, item)
        if crop_match is not None:
            return crop_match
    if len(candidates) == 1:
        _index, block, inline_location = candidates[0]
        return block, inline_location
    if candidates:
        return None
    return _locate_qwen_cross_block_body_ref(
        blocks, context, page, marker, item, allow_existing=allow_existing
    )


def _qwen_body_ref_candidate(
    block_index: int,
    block: CanonicalBlock,
    context: _NoteContext,
    inputs: _QwenBodyRefMatchInputs,
) -> Optional[Tuple[int, CanonicalBlock, _InlineMarkerLocation]]:
    if block.get("type") not in BODY_TYPES or inputs.page not in context.pages_for(block):
        return None
    if (
        not inputs.allow_existing
        and _existing_ref_marker_on_page(block, inputs.marker, inputs.page, context)
    ):
        return None
    text = str(block.get("text") or "")
    offset = _qwen_marker_offset_in_text(
        text,
        inputs.marker,
        inputs.before_for_match,
        inputs.after_for_match,
        inputs.quote,
    )
    visible_marker = (
        _qwen_visible_marker_at(text, inputs.marker, offset) if offset is not None else ""
    )
    block_id_matches_request = bool(
        inputs.requested_block_id and _qwen_block_id(block) == inputs.requested_block_id
    )
    if (
        inputs.requested_block_id
        and not block_id_matches_request
        and not visible_marker
        and not _is_block_crop_body_ref(inputs.item)
    ):
        return None
    used_visible_fallback = False
    if block_id_matches_request and not visible_marker:
        fallback = _unique_distinctive_visible_marker(text, inputs.marker)
        if fallback is not None:
            offset, visible_marker = fallback
            used_visible_fallback = True
    if offset is None:
        return None
    return (
        block_index,
        block,
        _InlineMarkerLocation(
            char_index=offset,
            source="qwen_marker_locator",
            confidence=str(inputs.item.get("confidence") or "candidate"),
            evidence=_qwen_body_ref_location_evidence(
                inputs,
                visible_marker=visible_marker,
                used_visible_fallback=used_visible_fallback,
            ),
        ),
    )


def _qwen_body_ref_location_evidence(
    inputs: _QwenBodyRefMatchInputs,
    *,
    visible_marker: str,
    used_visible_fallback: bool,
) -> Dict[str, Any]:
    evidence = {
        "qwen_marker": inputs.marker,
        "qwen_quote": inputs.quote,
        **_qwen_body_ref_source_evidence(inputs.item),
        **_qwen_matching_context_evidence(
            inputs.before, inputs.after, inputs.before_for_match, inputs.after_for_match
        ),
    }
    if visible_marker:
        evidence.update(
            {
                "qwen_visible_marker_text": visible_marker,
                "qwen_visible_marker_stripped": True,
            }
        )
        if used_visible_fallback:
            evidence["qwen_unique_visible_marker_fallback"] = True
    return evidence


def _unique_distinctive_visible_marker(text: str, marker: str) -> Optional[Tuple[int, str]]:
    matches = _distinctive_visible_markers(text, marker)
    return matches[0] if len(matches) == 1 else None


def _distinctive_visible_markers(text: str, marker: str) -> List[Tuple[int, str]]:
    marker_texts = (
        [marker]
        if marker.startswith("*")
        else [variant for variant in _qwen_marker_text_variants(marker) if variant != marker]
    )
    matches: List[Tuple[int, str]] = []
    for marker_text in marker_texts:
        start = 0
        while marker_text:
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
            matches.append((offset, marker_text))
    return matches


def _qwen_block_id(block: CanonicalBlock) -> str:
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


def _is_block_crop_body_ref(item: Dict[str, Any]) -> bool:
    return str(item.get("body_ref_source") or "") == "paragraph_crop"


def _select_candidate_by_crop_geometry(
    candidates: List[Tuple[int, CanonicalBlock, _InlineMarkerLocation]],
    item: Dict[str, Any],
) -> Optional[Tuple[CanonicalBlock, _InlineMarkerLocation]]:
    if len(candidates) < 2:
        return None
    visible_candidates = [
        candidate
        for candidate in candidates
        if candidate[2].evidence.get("qwen_visible_marker_text")
    ]
    if len(visible_candidates) == 1:
        _index, block, inline_location = visible_candidates[0]
        inline_location.evidence["qwen_stale_block_id_resolved_by_visible_marker"] = True
        return block, inline_location
    if visible_candidates:
        candidates = visible_candidates
    crop_bbox = _numeric_bbox(item.get("crop_bbox_pdf"))
    page_bbox = _numeric_bbox(item.get("qwen_page_crop_bbox_pdf"))
    if crop_bbox is None or page_bbox is None:
        return None
    page_height = page_bbox[3] - page_bbox[1]
    if page_height <= 0:
        return None

    block_bboxes: List[Tuple[CanonicalBlock, _InlineMarkerLocation, List[float]]] = []
    page_bottom = 0.0
    for _index, block, inline_location in candidates:
        bbox = _numeric_bbox((block.get("source") or {}).get("bbox"))
        if bbox is None:
            continue
        block_bboxes.append((block, inline_location, bbox))
        page_bottom = max(page_bottom, bbox[3])
    if len(block_bboxes) < 2:
        return None

    content_height = max(page_height if page_height <= 1200 else 1000.0, page_bottom)
    crop_center_y = (crop_bbox[1] + crop_bbox[3]) / 2
    target_y = ((crop_center_y - page_bbox[1]) / page_height) * content_height
    ranked = sorted(
        (
            (abs(((bbox[1] + bbox[3]) / 2) - target_y), block, inline_location)
            for block, inline_location, bbox in block_bboxes
        ),
        key=lambda value: value[0],
    )
    if len(ranked) >= 2 and abs(ranked[0][0] - ranked[1][0]) < 1.0:
        return None
    _distance, block, inline_location = ranked[0]
    inline_location.evidence["qwen_stale_block_id_resolved_by_crop_geometry"] = True
    return block, inline_location


def _numeric_bbox(value: Any) -> Optional[List[float]]:
    if not isinstance(value, list) or len(value) != 4:
        return None
    out: List[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            return None
        out.append(float(item))
    return out


def _qwen_context_without_neighbor_markers(value: str) -> str:
    text = str(value or "")
    for marker_text in ("***", "**", "*"):
        text = text.replace(marker_text, "")
    superscript_digits = str.maketrans("", "", "⁰¹²³⁴⁵⁶⁷⁸⁹")
    return text.translate(superscript_digits)


def _qwen_matching_context_evidence(
    before: str, after: str, before_for_match: str, after_for_match: str
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if before != before_for_match:
        out["qwen_matching_before_text"] = before_for_match
    if after != after_for_match:
        out["qwen_matching_after_text"] = after_for_match
    return out


def _existing_ref_marker_on_page(
    block: CanonicalBlock, marker: str, page: int, context: _NoteContext
) -> bool:
    for ref in _note_refs(block):
        if normalize_note_marker(ref.get("marker", "")) != marker:
            continue
        source_page = ref.get("source_page")
        if isinstance(source_page, int) and source_page == page:
            return True
        if isinstance(source_page, int):
            continue
        source_pages = ref.get("source_pages")
        if isinstance(source_pages, list):
            pages = {value for value in source_pages if isinstance(value, int)}
            if pages and page in pages:
                return True
            if pages:
                continue
        if page in context.pages_for(block):
            return True
    return False


def _locate_qwen_cross_block_body_ref(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
    page: int,
    marker: str,
    item: Dict[str, Any],
    *,
    allow_existing: bool = False,
) -> Optional[Tuple[CanonicalBlock, _InlineMarkerLocation]]:
    before = normalize_ws(
        _qwen_context_without_neighbor_markers(str(item.get("before_text") or ""))
    )
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
    matches: List[Tuple[CanonicalBlock, _InlineMarkerLocation]] = []
    for left, right in pairwise(page_blocks):
        if not allow_existing and _existing_ref_marker_on_page(left, marker, page, context):
            continue
        left_text = str(left.get("text") or "")
        right_text = str(right.get("text") or "")
        if not _text_ends_with_normalized(
            left_text, before
        ) and not _text_ends_with_normalized_ignoring_trailing_punctuation(left_text, before):
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
                        "qwen_marker": marker,
                        "qwen_quote": str(item.get("quote") or ""),
                        "qwen_cross_block_after_text": after,
                    },
                ),
            )
        )
    return matches[0] if len(matches) == 1 else None


def _qwen_cross_block_marker_offset(
    text: str, marker: str, before: str, after: str, quote: str
) -> int:
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
