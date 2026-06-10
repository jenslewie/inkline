"""Refinement, alignment, ambiguity resolution, and recovery writes for Qwen markers.

Functions here take located body refs and either update existing inline
locations, align symbol refs from Qwen context, resolve ambiguous placements,
or write new note refs into blocks.  ``_strip_qwen_visible_marker`` mutates
block text (stripping a visible marker) and belongs here rather than in the
pure-read-only ``marker_offsets`` module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ...extraction.text import normalize_note_marker, normalize_ws
from ...schema.models import CanonicalBlock
from .keys import leading_note_marker
from .marker_inline import (
    _InlineMarkerLocation,
    _append_note_ref,
    _inline_note_run_char_index,
    _insert_inline_note_run,
    _note_refs,
)
from .marker_location import (
    _existing_ref_marker_on_page,
    _locate_qwen_body_ref,
    _qwen_marker_page_items,
    _qwen_context_without_neighbor_markers,
)
from .marker_offsets import (
    _offset_after_terminal_punctuation_cluster,
    _qwen_fold_bracket_width,
    _qwen_marker_offset_in_text,
)
from .marker_patterns import BODY_TYPES, TERMINAL_PUNCTUATION, _marker_int, _visible_note_candidates
from .resolver import _PageFootnoteStrategy
from .scopes import _EndnoteSectionStrategy, _NoteContext


def _recover_direct_page_footnote_qwen_refs(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
    page_defs: Dict[int, Set[int]],
    page_symbol_defs: Dict[int, Set[str]],
    *,
    qwen_marker_pages: Any = None,
) -> None:
    if not qwen_marker_pages:
        return

    # Build index structures: existing markers, definition markers, block lookups
    refs_by_page = _body_refs_by_source_page(blocks, context)
    existing_by_page: Dict[int, Set[str]] = {}
    for page, refs in refs_by_page.items():
        existing_by_page[page] = {str(marker) for _idx, _block, marker in refs}
    for block in blocks:
        if block.get("type") not in BODY_TYPES:
            continue
        for ref in _note_refs(block):
            marker = normalize_note_marker(ref.get("marker", ""))
            if not marker:
                continue
            source_page = ref.get("source_page")
            pages = [source_page] if isinstance(source_page, int) else context.pages_for(block)
            for page in pages:
                existing_by_page.setdefault(page, set()).add(marker)

    defs_by_page: Dict[int, Set[str]] = {
        page: {str(marker) for marker in markers}
        for page, markers in page_defs.items()
    }
    for page, markers in page_symbol_defs.items():
        defs_by_page.setdefault(page, set()).update(markers)
    if not defs_by_page:
        return

    block_index: Dict[int, int] = {id(block): index for index, block in enumerate(blocks)}
    blocks_by_id = {str(block.get("block_id")): block for block in blocks if block.get("block_id")}

    for evidence in _qwen_marker_page_items(qwen_marker_pages):
        page = evidence.get("page")
        if not isinstance(page, int):
            continue
        page_defs_text = defs_by_page.get(page) or set()
        if not page_defs_text:
            continue
        existing = existing_by_page.setdefault(page, set())

        # Match phase: locate body refs, refine existing refs, collect new-match candidates
        located_items, ambiguous_keys, ambiguous_anchor_keys = _collect_page_footnote_qwen_matches(
            blocks, context, blocks_by_id, page, page_defs_text, existing, evidence,
        )

        # Apply phase: write non-ambiguous new note refs
        _apply_page_footnote_qwen_matches(
            blocks, context, blocks_by_id, block_index, refs_by_page, existing, page,
            located_items, ambiguous_keys, ambiguous_anchor_keys,
        )


def _collect_page_footnote_qwen_matches(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
    blocks_by_id: Dict[str, Dict[str, Any]],
    page: int,
    page_defs_text: Set[str],
    existing: Set[str],
    evidence: Dict[str, Any],
) -> Tuple[
    List[Tuple[CanonicalBlock, str, Dict[str, Any], _InlineMarkerLocation]],
    Set[Tuple[int, int]],
    Set[Tuple[int, str, str, str]],
]:
    """Locate Qwen body refs for a page's footnote markers and compute ambiguity.

    Refines existing refs where a marker is already present. Returns
    (located_items, ambiguous_keys, ambiguous_anchor_keys) for the
    apply phase to write new note refs.
    """
    located_items: List[Tuple[CanonicalBlock, str, Dict[str, Any], _InlineMarkerLocation]] = []
    for item in evidence.get("body_refs") or []:
        if not isinstance(item, dict):
            continue
        marker = normalize_note_marker(str(item.get("marker") or "").replace("＊", "*"))
        if not marker or marker not in page_defs_text or marker in existing:
            if marker and marker in page_defs_text and marker in existing:
                _refine_existing_qwen_body_ref(blocks, context, blocks_by_id, page, marker, item)
            continue
        located = _locate_qwen_body_ref(blocks, context, page, marker, item)
        if located is None:
            continue
        target, inline_location = located
        if _existing_ref_marker_on_page(target, marker, page, context):
            _update_existing_qwen_ref_inline_location(target, marker, page, item, inline_location)
            _align_symbol_refs_from_qwen_footnote_context(blocks_by_id, target, page, item, inline_location)
            continue
        located_items.append((target, marker, item, inline_location))
    ambiguous_keys = _ambiguous_qwen_location_keys(located_items)
    ambiguous_anchor_keys = _ambiguous_qwen_anchor_keys(located_items)
    return located_items, ambiguous_keys, ambiguous_anchor_keys


def _apply_page_footnote_qwen_matches(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
    blocks_by_id: Dict[str, Dict[str, Any]],
    block_index: Dict[int, int],
    refs_by_page: Dict[int, List[Tuple[int, CanonicalBlock, int]]],
    existing: Set[str],
    page: int,
    located_items: List[Tuple[CanonicalBlock, str, Dict[str, Any], _InlineMarkerLocation]],
    ambiguous_keys: Set[Tuple[int, int]],
    ambiguous_anchor_keys: Set[Tuple[int, str, str, str]],
) -> None:
    """Apply non-ambiguous Qwen page footnote marker matches as new note refs."""
    for target, marker, item, inline_location in located_items:
        if (id(target), inline_location.char_index) in ambiguous_keys or _qwen_anchor_key(target, marker, item) in ambiguous_anchor_keys:
            continue
        _strip_qwen_visible_marker(target, inline_location)
        _append_note_ref(
            target,
            marker,
            source="qwen_marker_locator",
            confidence=str(item.get("confidence") or "candidate"),
            recovery_reason="page_footnote_marker_seen_in_qwen_visual_evidence",
            raw_marker=marker if marker.startswith("*") else f"^{{{marker}}}",
            source_page=page,
            evidence={
                "qwen_before_text": str(item.get("before_text") or ""),
                "qwen_after_text": str(item.get("after_text") or ""),
                "qwen_quote": str(item.get("quote") or ""),
                **inline_location.evidence,
            },
            inline_location=inline_location,
        )
        existing.add(marker)
        marker_int = _marker_int(marker)
        if marker_int is not None:
            refs_by_page.setdefault(page, []).append((block_index[id(target)], target, marker_int))
            refs_by_page[page].sort(key=lambda value: (value[0], value[2]))
        _align_symbol_refs_from_qwen_footnote_context(blocks_by_id, target, page, item, inline_location)


def _recover_direct_scoped_endnote_qwen_refs(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
    *,
    qwen_marker_pages: Any = None,
) -> None:
    if not qwen_marker_pages:
        return
    defs_by_scope = _scoped_endnote_definition_markers(blocks, context)
    if not defs_by_scope:
        return
    existing_by_scope = _existing_body_ref_markers_by_scope(blocks, context)
    located_items: List[Tuple[CanonicalBlock, str, int, Dict[str, Any], _InlineMarkerLocation, Optional[str]]] = []
    for evidence in _qwen_marker_page_items(qwen_marker_pages):
        page = evidence.get("page")
        if not isinstance(page, int):
            continue
        for item in evidence.get("body_refs") or []:
            if not isinstance(item, dict):
                continue
            marker = normalize_note_marker(str(item.get("marker") or "").replace("＊", "*"))
            if not marker:
                continue
            located = _locate_qwen_body_ref(blocks, context, page, marker, item)
            if located is None:
                continue
            target, inline_location = located
            scope = context.scope_for(target)
            if marker not in defs_by_scope.get(scope, set()):
                continue
            if marker in existing_by_scope.get(scope, set()):
                continue
            located_items.append((target, marker, page, item, inline_location, scope))

    ambiguous_keys = _ambiguous_qwen_location_keys(
        [(target, marker, item, inline_location) for target, marker, _page, item, inline_location, _scope in located_items]
    )
    ambiguous_anchor_keys = _ambiguous_qwen_anchor_keys(
        [(target, marker, item, inline_location) for target, marker, _page, item, inline_location, _scope in located_items]
    )
    for target, marker, page, item, inline_location, scope in located_items:
        if (id(target), inline_location.char_index) in ambiguous_keys or _qwen_anchor_key(target, marker, item) in ambiguous_anchor_keys:
            continue
        if marker in existing_by_scope.get(scope, set()):
            continue
        _strip_qwen_visible_marker(target, inline_location)
        _append_note_ref(
            target,
            marker,
            source="qwen_marker_locator",
            confidence=str(item.get("confidence") or "candidate"),
            recovery_reason="chapter_endnote_marker_seen_in_qwen_visual_evidence",
            raw_marker=marker if marker.startswith("*") else f"^{{{marker}}}",
            source_page=page,
            evidence={
                "qwen_before_text": str(item.get("before_text") or ""),
                "qwen_after_text": str(item.get("after_text") or ""),
                "qwen_quote": str(item.get("quote") or ""),
                **inline_location.evidence,
            },
            inline_location=inline_location,
        )
        existing_by_scope.setdefault(scope, set()).add(marker)


def _scoped_endnote_definition_markers(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
) -> Dict[Optional[str], Set[str]]:
    counts: Dict[Optional[str], Dict[str, int]] = {}
    for candidate in _EndnoteSectionStrategy("chapter_endnote", scope_required=True).collect(blocks, context):
        marker = normalize_note_marker(candidate.marker or "")
        if marker and candidate.scope_key:
            scope_counts = counts.setdefault(candidate.scope_key, {})
            scope_counts[marker] = scope_counts.get(marker, 0) + 1
    for candidate in _EndnoteSectionStrategy("book_endnote", scope_required=False).collect(blocks, context):
        marker = normalize_note_marker(candidate.marker or "")
        if marker:
            book_counts = counts.setdefault(None, {})
            book_counts[marker] = book_counts.get(marker, 0) + 1
    return {
        scope: {marker for marker, count in marker_counts.items() if count == 1}
        for scope, marker_counts in counts.items()
    }


def _existing_body_ref_markers_by_scope(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
) -> Dict[Optional[str], Set[str]]:
    out: Dict[Optional[str], Set[str]] = {}
    for block in blocks:
        if block.get("type") not in BODY_TYPES:
            continue
        scope = context.scope_for(block)
        for ref in _note_refs(block):
            marker = normalize_note_marker(ref.get("marker", ""))
            if marker:
                out.setdefault(scope, set()).add(marker)
    return out


def _refine_existing_qwen_body_ref(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
    blocks_by_id: Dict[str, Dict[str, Any]],
    page: int,
    marker: str,
    item: Dict[str, Any],
) -> None:
    located = _locate_qwen_body_ref(blocks, context, page, marker, item, allow_existing=True)
    if located is None:
        return
    target, inline_location = located
    _update_existing_qwen_ref_inline_location(target, marker, page, item, inline_location)
    _align_symbol_refs_from_qwen_footnote_context(blocks_by_id, target, page, item, inline_location)


def _update_existing_qwen_ref_inline_location(
    block: CanonicalBlock,
    marker: str,
    page: int,
    item: Dict[str, Any],
    inline_location: _InlineMarkerLocation,
) -> bool:
    changed = False
    for ref in _note_refs(block):
        if normalize_note_marker(ref.get("marker", "")) != marker or ref.get("source_page") != page:
            continue
        if _has_valid_existing_structured_inline_run(block, ref):
            continue
        visible_location = _visible_raw_marker_inline_location(block, ref)
        if visible_location is not None:
            ref.setdefault("evidence", {}).update(visible_location.evidence)
            _insert_inline_note_run(block, ref, visible_location.char_index)
            changed = True
            continue
        verified_location = _user_verified_inline_location(block, ref)
        if verified_location is not None and verified_location.char_index != inline_location.char_index:
            if _inline_note_run_char_index(block, ref) == verified_location.char_index:
                continue
            ref.setdefault("evidence", {}).update(verified_location.evidence)
            _insert_inline_note_run(block, ref, verified_location.char_index)
            changed = True
            continue
        if _inline_note_run_char_index(block, ref) == inline_location.char_index:
            continue
        evidence = ref.setdefault("evidence", {})
        evidence.update(
            {
                "qwen_before_text": str(item.get("before_text") or ""),
                "qwen_after_text": str(item.get("after_text") or ""),
                "qwen_quote": str(item.get("quote") or ""),
                **inline_location.evidence,
            }
        )
        _insert_inline_note_run(block, ref, inline_location.char_index)
        changed = True
    return changed


def _has_valid_existing_structured_inline_run(block: CanonicalBlock, ref: Dict[str, Any]) -> bool:
    if str(ref.get("source") or "") not in {"equation_inline", "equation_interline", "trailing_text"}:
        return False
    runs = (block.get("attrs") or {}).get("inline_runs") or block.get("inline_runs")
    if not isinstance(runs, list):
        return False
    if not _structured_inline_runs_match_text(runs, str(block.get("text") or "")):
        return False
    marker = normalize_note_marker(ref.get("marker", ""))
    source_page = ref.get("source_page")
    target_note_id = ref.get("target_note_id")
    for run in runs:
        if not isinstance(run, dict) or run.get("type") != "note_ref":
            continue
        if normalize_note_marker(run.get("marker", "")) != marker:
            continue
        if run.get("source") != ref.get("source") or run.get("source_page") != source_page:
            continue
        if target_note_id and run.get("target_note_id") != target_note_id:
            continue
        return True
    return False


def _structured_inline_runs_match_text(runs: Sequence[Any], text: str) -> bool:
    reconstructed = "".join(
        str(run.get("text") or "")
        for run in runs
        if isinstance(run, dict) and run.get("type") == "text"
    )
    return reconstructed == text or normalize_ws(reconstructed) == normalize_ws(text)


def _visible_raw_marker_inline_location(block: CanonicalBlock, ref: Dict[str, Any]) -> Optional[_InlineMarkerLocation]:
    raw_marker = str(ref.get("raw_marker") or "")
    marker = normalize_note_marker(ref.get("marker", ""))
    text = str(block.get("text") or "")
    if not raw_marker or raw_marker.startswith("^{") or not marker or not text:
        return None
    if normalize_note_marker(raw_marker) != marker:
        return None
    offsets: List[int] = []
    start = 0
    while True:
        offset = text.find(raw_marker, start)
        if offset < 0:
            break
        offsets.append(offset)
        start = offset + max(1, len(raw_marker))
    if len(offsets) != 1:
        return None
    offset = offsets[0]
    if not any(raw == raw_marker and normalized == marker for raw, normalized, _reason in _visible_note_candidates(text)):
        return None
    block["text"] = text[:offset] + text[offset + len(raw_marker) :]
    return _InlineMarkerLocation(
        char_index=offset,
        source="canonical_visible_marker",
        confidence="high",
        evidence={
            "visible_raw_marker": raw_marker,
            "visible_raw_marker_stripped": True,
        },
    )


def _user_verified_inline_location(block: CanonicalBlock, ref: Dict[str, Any]) -> Optional[_InlineMarkerLocation]:
    evidence = ref.get("evidence") if isinstance(ref.get("evidence"), dict) else {}
    reason = str(evidence.get("manual_correction_reason") or "")
    if not reason.startswith("user_verified"):
        return None
    before = str(evidence.get("manual_corrected_before_text") or "")
    after = str(evidence.get("manual_corrected_after_text") or "")
    if not before and not after:
        return None
    marker = normalize_note_marker(ref.get("marker", ""))
    offset = _qwen_marker_offset_in_text(str(block.get("text") or ""), marker, before, after, "")
    if offset is None:
        return None
    return _InlineMarkerLocation(
        char_index=offset,
        source="manual_correction",
        confidence="high",
        evidence={"manual_position_preserved": True},
    )


def _align_symbol_refs_from_qwen_footnote_context(
    blocks_by_id: Dict[str, Dict[str, Any]],
    block: CanonicalBlock,
    page: int,
    item: Dict[str, Any],
    inline_location: _InlineMarkerLocation,
) -> None:
    after = normalize_ws(str(item.get("after_text") or ""))
    if not after:
        return
    changed = False
    for ref in _note_refs(block):
        marker = normalize_note_marker(ref.get("marker", ""))
        if not marker.startswith("*") or ref.get("source_page") != page:
            continue
        note_block = blocks_by_id.get(str(ref.get("target_block_id") or ""))
        if not note_block or not _qwen_after_text_matches_note_definition(after, note_block):
            continue
        ref.setdefault("evidence", {})["qwen_symbol_context_after_text"] = after
        if _inline_note_run_char_index(block, ref) != inline_location.char_index:
            _insert_inline_note_run(block, ref, inline_location.char_index)
    _split_adjacent_symbol_numeric_refs_around_terminal_punctuation(block, page, inline_location.char_index)


def _qwen_after_text_matches_note_definition(after: str, note_block: CanonicalBlock) -> bool:
    note_text = normalize_ws(str(note_block.get("text") or ""))
    if not note_text:
        return False
    marker = leading_note_marker(note_text, include_superscript=True) or ""
    if marker:
        note_text = normalize_ws(note_text[len(marker):])
    note_text = note_text.lstrip("*＊.．、 \t")
    return note_text.startswith(after) or _qwen_fold_bracket_width(note_text).startswith(_qwen_fold_bracket_width(after))


def _split_adjacent_symbol_numeric_refs_around_terminal_punctuation(block: CanonicalBlock, page: int, offset: int) -> bool:
    text = str(block.get("text") or "")
    if offset < 0 or offset >= len(text) or text[offset] not in TERMINAL_PUNCTUATION:
        return False
    refs = [
        ref
        for ref in _note_refs(block)
        if ref.get("source_page") == page
        and _inline_note_run_char_index(block, ref) == offset
    ]
    if not any(normalize_note_marker(ref.get("marker", "")).startswith("*") for ref in refs):
        return False
    numeric_refs = [ref for ref in refs if _marker_int(normalize_note_marker(ref.get("marker", ""))) is not None]
    if not numeric_refs:
        return False
    adjusted_offset = _offset_after_terminal_punctuation_cluster(text, offset)
    if adjusted_offset == offset:
        return False
    for ref in numeric_refs:
        ref.setdefault("evidence", {})["symbol_numeric_split_at_punctuation"] = True
        _insert_inline_note_run(block, ref, adjusted_offset)
    return True


def _ambiguous_qwen_location_keys(
    located_items: Sequence[Tuple[CanonicalBlock, str, Dict[str, Any], _InlineMarkerLocation]]
) -> Set[Tuple[int, int]]:
    markers_by_key: Dict[Tuple[int, int], Set[str]] = {}
    for target, marker, _item, inline_location in located_items:
        markers_by_key.setdefault((id(target), inline_location.char_index), set()).add(marker)
    return {key for key, markers in markers_by_key.items() if len(markers) > 1}


def _ambiguous_qwen_anchor_keys(
    located_items: Sequence[Tuple[CanonicalBlock, str, Dict[str, Any], _InlineMarkerLocation]]
) -> Set[Tuple[int, str, str, str]]:
    markers_by_anchor: Dict[Tuple[int, str, str], Set[str]] = {}
    for target, marker, item, _inline_location in located_items:
        key = (id(target), normalize_ws(str(item.get("before_text") or "")), normalize_ws(str(item.get("after_text") or "")))
        markers_by_anchor.setdefault(key, set()).add(marker)
    ambiguous_anchors = {key for key, markers in markers_by_anchor.items() if len(markers) > 1}
    return {
        _qwen_anchor_key(target, marker, item)
        for target, marker, item, _inline_location in located_items
        if (id(target), normalize_ws(str(item.get("before_text") or "")), normalize_ws(str(item.get("after_text") or ""))) in ambiguous_anchors
    }


def _qwen_anchor_key(target: CanonicalBlock, marker: str, item: Dict[str, Any]) -> Tuple[int, str, str, str]:
    return (
        id(target),
        marker,
        normalize_ws(str(item.get("before_text") or "")),
        normalize_ws(str(item.get("after_text") or "")),
    )


def _strip_qwen_visible_marker(block: CanonicalBlock, inline_location: _InlineMarkerLocation) -> None:
    marker_text = str(inline_location.evidence.get("qwen_visible_marker_text") or "")
    offset = inline_location.char_index
    if not marker_text:
        return
    text = str(block.get("text") or "")
    if text[offset : offset + len(marker_text)] != marker_text:
        return
    block["text"] = text[:offset] + text[offset + len(marker_text) :]


def _body_refs_by_source_page(
    blocks: List[CanonicalBlock],
    context: _NoteContext,
) -> Dict[int, List[Tuple[int, CanonicalBlock, int]]]:
    refs_by_page: Dict[int, List[Tuple[int, CanonicalBlock, int]]] = {}
    for block_index, block in enumerate(blocks):
        if block.get("type") not in BODY_TYPES:
            continue
        fallback_pages = context.pages_for(block)
        for ref in _note_refs(block):
            marker = _marker_int(ref.get("marker"))
            if marker is None:
                continue
            source_page = ref.get("source_page")
            pages = [source_page] if isinstance(source_page, int) else fallback_pages
            for page in pages:
                refs_by_page.setdefault(page, []).append((block_index, block, marker))
    for refs in refs_by_page.values():
        refs.sort(key=lambda item: (item[0], item[2]))
    return refs_by_page
