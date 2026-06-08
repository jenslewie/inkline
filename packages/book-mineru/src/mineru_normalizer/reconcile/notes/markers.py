"""Missing note reference recovery. Recovers missing inline note references by analyzing note definition sequences and Qwen visual evidence. Main entry: recover_missing_note_refs()."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ...analysis.pdf_page_metrics import PdfPageCache
from ...extraction.text import normalize_note_marker, normalize_ws
from .marker_inline import _InlineMarkerLocation, _append_note_ref, _note_refs, _rebuild_inline_note_runs_from_exact_refs
from .marker_patterns import BODY_TYPES, TERMINAL_PUNCTUATION, _marker_int, _visible_note_candidates
from .keys import leading_note_marker
from .resolver import _EndnoteSectionStrategy, _NoteContext, _PageFootnoteStrategy

__all__ = ["recover_missing_note_refs"]


def recover_missing_note_refs(blocks: List[Dict[str, Any]], source_pdf: Any = None, *_args: Any, pdf_cache: Optional[PdfPageCache] = None, **_kwargs: Any) -> None:
    """Recover conservative inline note refs before final note linking.

    MinerU sometimes preserves note bodies but flattens body-side markers into
    ordinary digits, or drops a single marker between two well-formed neighbors.
    This pass uses available note-definition sequences as guardrails and records
    recovered refs in ``attrs.note_refs`` so ``resolve_note_links`` can treat
    explicit, recovered, and inferred refs through the same path.
    """

    context = _NoteContext(blocks)
    scope_defs, page_defs, book_defs = _collect_note_definition_markers(blocks, context)
    page_symbol_defs = _collect_page_symbol_definition_markers(blocks, context)
    if not scope_defs and not page_defs and not book_defs and not page_symbol_defs:
        return

    qwen_marker_pages = _kwargs.get("qwen_marker_pages") or _kwargs.get("marker_locator_pages")
    _recover_direct_page_footnote_qwen_refs(
        blocks,
        context,
        page_defs,
        page_symbol_defs,
        qwen_marker_pages=qwen_marker_pages,
    )
    _recover_direct_scoped_endnote_qwen_refs(
        blocks,
        context,
        qwen_marker_pages=qwen_marker_pages,
    )


def _collect_note_definition_markers(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
) -> Tuple[Dict[str, Set[int]], Dict[int, Set[int]], Set[int]]:
    scope_defs: Dict[str, Set[int]] = {}
    page_defs: Dict[int, Set[int]] = {}
    book_defs: Set[int] = set()

    for candidate in _PageFootnoteStrategy().collect(blocks, context):
        marker = _marker_int(candidate.marker)
        if marker is not None and candidate.page is not None:
            page_defs.setdefault(candidate.page, set()).add(marker)

    chapter_strategy = _EndnoteSectionStrategy("chapter_endnote", scope_required=True)
    for candidate in chapter_strategy.collect(blocks, context):
        marker = _marker_int(candidate.marker)
        if marker is not None and candidate.scope_key:
            scope_defs.setdefault(candidate.scope_key, set()).add(marker)

    book_strategy = _EndnoteSectionStrategy("book_endnote", scope_required=False)
    for candidate in book_strategy.collect(blocks, context):
        marker = _marker_int(candidate.marker)
        if marker is not None:
            book_defs.add(marker)

    return scope_defs, page_defs, book_defs


def _collect_page_symbol_definition_markers(blocks: List[Dict[str, Any]], context: _NoteContext) -> Dict[int, Set[str]]:
    out: Dict[int, Set[str]] = {}
    for block in blocks:
        if block.get("type") != "footnote":
            continue
        attrs = block.get("attrs") or {}
        if attrs.get("role") != "page_footnote":
            continue
        marker = normalize_note_marker(attrs.get("note_marker", "")) or (leading_note_marker(str(block.get("text") or ""), include_superscript=True) or "")
        if not marker.startswith("*"):
            continue
        for page in context.pages_for(block):
            out.setdefault(page, set()).add(marker)
    return out


def _body_refs_by_source_page(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
) -> Dict[int, List[Tuple[int, Dict[str, Any], int]]]:
    refs_by_page: Dict[int, List[Tuple[int, Dict[str, Any], int]]] = {}
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


def _recover_direct_page_footnote_qwen_refs(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
    page_defs: Dict[int, Set[int]],
    page_symbol_defs: Dict[int, Set[str]],
    *,
    qwen_marker_pages: Any = None,
) -> None:
    if not qwen_marker_pages:
        return
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

    block_index = {id(block): index for index, block in enumerate(blocks)}
    blocks_by_id = {str(block.get("block_id")): block for block in blocks if block.get("block_id")}
    for evidence in _qwen_marker_page_items(qwen_marker_pages):
        page = evidence.get("page")
        if not isinstance(page, int):
            continue
        page_defs_text = defs_by_page.get(page) or set()
        if not page_defs_text:
            continue
        existing = existing_by_page.setdefault(page, set())
        located_items: List[Tuple[Dict[str, Any], str, Dict[str, Any], _InlineMarkerLocation]] = []
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
    blocks: List[Dict[str, Any]],
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
    block_index = {id(block): index for index, block in enumerate(blocks)}
    located_items: List[Tuple[Dict[str, Any], str, int, Dict[str, Any], _InlineMarkerLocation, Optional[str]]] = []
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
        if id(target) in block_index:
            _rebuild_inline_note_runs_from_exact_refs(target)


def _scoped_endnote_definition_markers(
    blocks: List[Dict[str, Any]],
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
    blocks: List[Dict[str, Any]],
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
    blocks: List[Dict[str, Any]],
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
    block: Dict[str, Any],
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
        if (
            ref.get("inline_position") == "exact"
            and ref.get("inline_position_source") == "canonical_visible_marker"
        ):
            continue
        visible_location = _visible_raw_marker_inline_location(block, ref)
        if visible_location is not None:
            ref["inline_position"] = "exact"
            ref["inline_position_source"] = visible_location.source
            ref["inline_position_confidence"] = visible_location.confidence
            ref["inline_offset"] = visible_location.char_index
            ref.setdefault("evidence", {}).update(visible_location.evidence)
            changed = True
            continue
        verified_location = _user_verified_inline_location(block, ref)
        if verified_location is not None and verified_location.char_index != inline_location.char_index:
            if (
                ref.get("inline_position") == "exact"
                and ref.get("inline_offset") == verified_location.char_index
                and ref.get("inline_position_source") == verified_location.source
            ):
                continue
            ref["inline_position"] = "exact"
            ref["inline_position_source"] = verified_location.source
            ref["inline_position_confidence"] = verified_location.confidence
            ref["inline_offset"] = verified_location.char_index
            ref.setdefault("evidence", {}).update(verified_location.evidence)
            changed = True
            continue
        if (
            ref.get("inline_position") == "exact"
            and ref.get("inline_offset") == inline_location.char_index
            and ref.get("inline_position_source") == "qwen_marker_locator"
        ):
            continue
        ref["inline_position"] = "exact"
        ref["inline_position_source"] = "qwen_marker_locator"
        ref["inline_position_confidence"] = str(item.get("confidence") or inline_location.confidence)
        ref["inline_offset"] = inline_location.char_index
        evidence = ref.setdefault("evidence", {})
        evidence.update(
            {
                "qwen_before_text": str(item.get("before_text") or ""),
                "qwen_after_text": str(item.get("after_text") or ""),
                "qwen_quote": str(item.get("quote") or ""),
                **inline_location.evidence,
            }
        )
        changed = True
    if changed:
        _rebuild_inline_note_runs_from_exact_refs(block)
    return changed


def _has_valid_existing_structured_inline_run(block: Dict[str, Any], ref: Dict[str, Any]) -> bool:
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


def _visible_raw_marker_inline_location(block: Dict[str, Any], ref: Dict[str, Any]) -> Optional[_InlineMarkerLocation]:
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
            "visible_raw_marker_offset": offset,
            "visible_raw_marker_stripped": True,
        },
    )


def _user_verified_inline_location(block: Dict[str, Any], ref: Dict[str, Any]) -> Optional[_InlineMarkerLocation]:
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
        evidence={
            "manual_position_preserved": True,
            "manual_position_preserved_from_qwen_offset": ref.get("inline_offset"),
        },
    )


def _align_symbol_refs_from_qwen_footnote_context(
    blocks_by_id: Dict[str, Dict[str, Any]],
    block: Dict[str, Any],
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
        if (
            ref.get("inline_position") == "exact"
            and ref.get("inline_offset") == inline_location.char_index
            and ref.get("inline_position_source") == "qwen_marker_locator_symbol_context"
        ):
            continue
        note_block = blocks_by_id.get(str(ref.get("target_block_id") or ""))
        if not note_block or not _qwen_after_text_matches_note_definition(after, note_block):
            continue
        ref["inline_position"] = "exact"
        ref["inline_position_source"] = "qwen_marker_locator_symbol_context"
        ref["inline_position_confidence"] = inline_location.confidence
        ref["inline_offset"] = inline_location.char_index
        ref.setdefault("evidence", {})["qwen_symbol_context_after_text"] = after
        changed = True
    split_changed = _split_same_offset_symbol_numeric_refs_around_terminal_punctuation(block, page, inline_location.char_index)
    if changed or split_changed:
        _rebuild_inline_note_runs_from_exact_refs(block)


def _qwen_after_text_matches_note_definition(after: str, note_block: Dict[str, Any]) -> bool:
    note_text = normalize_ws(str(note_block.get("text") or ""))
    if not note_text:
        return False
    marker = leading_note_marker(note_text, include_superscript=True) or ""
    if marker:
        note_text = normalize_ws(note_text[len(marker):])
    note_text = note_text.lstrip("*＊.．、 \t")
    return note_text.startswith(after) or _qwen_fold_bracket_width(note_text).startswith(_qwen_fold_bracket_width(after))


def _split_same_offset_symbol_numeric_refs_around_terminal_punctuation(block: Dict[str, Any], page: int, offset: int) -> bool:
    text = str(block.get("text") or "")
    if offset < 0 or offset >= len(text) or text[offset] not in TERMINAL_PUNCTUATION:
        return False
    refs = [
        ref
        for ref in _note_refs(block)
        if ref.get("source_page") == page
        and ref.get("inline_position") == "exact"
        and ref.get("inline_offset") == offset
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
        ref["inline_offset"] = adjusted_offset
        ref["inline_position_source"] = ref.get("inline_position_source") or "qwen_marker_locator"
        ref.setdefault("evidence", {})["same_offset_symbol_numeric_split_from"] = offset
    return True


def _offset_after_terminal_punctuation_cluster(text: str, offset: int) -> int:
    if offset < 0 or offset >= len(text) or text[offset] not in TERMINAL_PUNCTUATION:
        return offset
    index = offset + 1
    trailing = _qwen_trailing_closing_punctuation()
    while index < len(text) and text[index] in trailing:
        index += 1
    return index


def _ambiguous_qwen_location_keys(
    located_items: Sequence[Tuple[Dict[str, Any], str, Dict[str, Any], _InlineMarkerLocation]]
) -> Set[Tuple[int, int]]:
    markers_by_key: Dict[Tuple[int, int], Set[str]] = {}
    for target, marker, _item, inline_location in located_items:
        markers_by_key.setdefault((id(target), inline_location.char_index), set()).add(marker)
    return {key for key, markers in markers_by_key.items() if len(markers) > 1}


def _ambiguous_qwen_anchor_keys(
    located_items: Sequence[Tuple[Dict[str, Any], str, Dict[str, Any], _InlineMarkerLocation]]
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


def _qwen_anchor_key(target: Dict[str, Any], marker: str, item: Dict[str, Any]) -> Tuple[int, str, str, str]:
    return (
        id(target),
        marker,
        normalize_ws(str(item.get("before_text") or "")),
        normalize_ws(str(item.get("after_text") or "")),
    )


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


def _qwen_marker_offset_in_text(text: str, marker: str, before_text: str, after_text: str, quote_text: str = "") -> Optional[int]:
    before = normalize_ws(before_text)
    after = normalize_ws(after_text)
    quote = normalize_ws(quote_text)
    if not text or (not before and not after):
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
                candidates.append(_qwen_adjusted_offset_between_before_after(text, marker, before, after, quote, index))
            elif before:
                omitted_punctuation_offset = _qwen_offset_before_omitted_boundary_punctuation(text, marker, before, after, quote, index)
                if omitted_punctuation_offset is not None:
                    candidates.append(omitted_punctuation_offset)
                    start = index + 1
                    continue
                omitted_terminal_offset = _qwen_offset_after_omitted_terminal_phrase(text, before, index)
                if omitted_terminal_offset is not None:
                    candidates.append(omitted_terminal_offset)
                    start = index + 1
                    continue
                omitted_fragment_offset = _qwen_offset_after_short_omitted_fragment(text, marker, before, quote, index)
                if omitted_fragment_offset is not None:
                    candidates.append(omitted_fragment_offset)
                    start = index + 1
                    continue
                punct_offset = _qwen_offset_around_punctuation(text, marker, before, index)
                if punct_offset is not None:
                    candidates.append(punct_offset)
            start = index + 1
        if not candidates and before:
            candidates.extend(_qwen_filter_before_only_offsets(text, marker, after, quote, _qwen_offsets_after_before(text, before)))
    elif before:
        candidates.extend(_qwen_offsets_after_before(text, before))
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return None
    return _qwen_marker_offset_in_normalized_text(text, marker, before, after, quote)


def _qwen_marker_offset_in_normalized_text(text: str, marker: str, before: str, after: str, quote: str) -> Optional[int]:
    compact, offsets = _normalized_text_with_start_offsets(text)
    candidates: List[int] = []
    if after:
        start = 0
        while True:
            index = compact.find(after, start)
            if index < 0:
                break
            visible_offset = _qwen_visible_marker_offset_before_after(compact, marker, before, index)
            if visible_offset is not None and 0 <= visible_offset < len(offsets):
                candidates.append(offsets[visible_offset])
                start = index + 1
                continue
            if not before or _qwen_prefix_matches_before(compact[:index], before):
                adjusted_index = _qwen_adjusted_offset_between_before_after(compact, marker, before, after, quote, index)
                if 0 <= adjusted_index < len(offsets):
                    candidates.append(offsets[adjusted_index])
                elif adjusted_index == len(offsets):
                    candidates.append(len(text))
            elif before:
                omitted_punctuation_offset = _qwen_offset_before_omitted_boundary_punctuation(compact, marker, before, after, quote, index)
                if omitted_punctuation_offset is not None and 0 <= omitted_punctuation_offset < len(offsets):
                    candidates.append(offsets[omitted_punctuation_offset])
                    start = index + 1
                    continue
                omitted_fragment_offset = _qwen_offset_after_short_omitted_fragment(compact, marker, before, quote, index)
                if omitted_fragment_offset is not None and 0 <= omitted_fragment_offset < len(offsets):
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
        candidates.extend(_qwen_offsets_after_before_in_normalized_text(text, compact, offsets, before))
    return candidates[0] if len(candidates) == 1 else None


def _qwen_offsets_after_before(text: str, before: str) -> List[int]:
    candidates: List[int] = []
    start = 0
    while True:
        index = text.find(before, start)
        if index < 0:
            break
        candidates.append(_qwen_offset_after_optional_closing_punctuation(text, index + len(before)))
        start = index + 1
    return candidates


def _qwen_offsets_after_before_in_normalized_text(text: str, compact: str, offsets: List[int], before: str) -> List[int]:
    candidates: List[int] = []
    start = 0
    while True:
        index = compact.find(before, start)
        if index < 0:
            break
        end = index + len(before) - 1
        if 0 <= end < len(offsets):
            candidates.append(_qwen_offset_after_optional_closing_punctuation(text, offsets[end] + 1))
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


def _qwen_adjusted_offset_between_before_after(text: str, marker: str, before: str, after: str, quote: str, after_index: int) -> int:
    if _qwen_quote_places_marker_after_after(marker, after, quote):
        return after_index + len(after)
    title_prefix_offset = _qwen_offset_before_omitted_sentence_initial_title(text, marker, before, after, quote, after_index)
    if title_prefix_offset is not None:
        return title_prefix_offset
    suffix_offset = _qwen_offset_after_suffix_phrase(marker, before, after, quote, after_index)
    if suffix_offset is not None:
        return suffix_offset
    punctuation_offset = _qwen_offset_after_leading_punctuation(marker, before, after, quote, after_index)
    if punctuation_offset is not None:
        return punctuation_offset
    return after_index + _qwen_numeric_offset_after_leading_punctuation(marker, after, quote)


def _qwen_visible_marker_offset_before_after(text: str, marker: str, before: str, after_index: int) -> Optional[int]:
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
    while offset < len(after) and (after[offset] in _qwen_boundary_punctuation() or after[offset] in trailing):
        offset += 1
    return offset


def _qwen_quote_places_numeric_after_leading_punctuation(marker: str, after: str, quote: str) -> bool:
    if not quote:
        return False
    offset = 0
    trailing = _qwen_trailing_closing_punctuation()
    while offset < len(after) and (after[offset] in _qwen_boundary_punctuation() or after[offset] in trailing):
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


def _qwen_offset_after_suffix_phrase(marker: str, before: str, after: str, quote: str, after_index: int) -> Optional[int]:
    if marker.startswith("*") or not before or not after or len(after) > 12:
        return None
    if not after.startswith("的") or after[-1] not in TERMINAL_PUNCTUATION:
        return None
    if not _qwen_quote_places_marker_between_before_and_after(marker, before, after, quote):
        return None
    return after_index + len(after)


def _qwen_offset_after_leading_punctuation(marker: str, before: str, after: str, quote: str, after_index: int) -> Optional[int]:
    if marker.startswith("*") or not after or after[0] not in TERMINAL_PUNCTUATION:
        return None
    if not _qwen_quote_places_marker_between_before_and_after(marker, before, after, quote):
        return None
    return after_index + _offset_after_terminal_punctuation_cluster(after, 0)


def _qwen_book_title_text(text: str) -> bool:
    text = normalize_ws(text)
    return len(text) >= 3 and text.startswith("《") and text.endswith("》")


def _qwen_quote_places_marker_between_before_and_after(marker: str, before: str, after: str, quote: str) -> bool:
    if not before or not after or not quote:
        return False
    folded_before = _qwen_fold_bracket_width(before)
    folded_after = _qwen_fold_bracket_width(after)
    folded_quote = _qwen_fold_bracket_width(quote)
    for marker_text in _qwen_marker_text_variants(marker):
        if f"{before}{marker_text}{after}" in quote or f"{folded_before}{marker_text}{folded_after}" in folded_quote:
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


def _strip_qwen_visible_marker(block: Dict[str, Any], inline_location: _InlineMarkerLocation) -> None:
    marker_text = str(inline_location.evidence.get("qwen_visible_marker_text") or "")
    offset = inline_location.char_index
    if not marker_text:
        return
    text = str(block.get("text") or "")
    if text[offset : offset + len(marker_text)] != marker_text:
        return
    block["text"] = text[:offset] + text[offset + len(marker_text) :]


def _qwen_offset_around_punctuation(text: str, marker: str, before: str, after_index: int) -> Optional[int]:
    if after_index <= 0:
        return None
    prefix = text[:after_index]
    punctuation_start = len(prefix.rstrip(_qwen_boundary_punctuation()))
    if punctuation_start == len(prefix):
        return None
    if not _qwen_prefix_matches_before(prefix[:punctuation_start], before):
        return None
    return punctuation_start if marker.startswith("*") else after_index


def _qwen_offset_after_omitted_terminal_phrase(text: str, before: str, after_index: int) -> Optional[int]:
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
    terminal_offsets = [index for index, char in enumerate(fragment) if char in TERMINAL_PUNCTUATION]
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
    if not fragment or len(fragment) > 4 or fragment.strip(_qwen_boundary_punctuation() + _qwen_trailing_closing_punctuation()):
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


def _qwen_filter_before_only_offsets(text: str, marker: str, after: str, quote: str, offsets: Sequence[int]) -> List[int]:
    if _marker_int(marker) is None or not after or not quote:
        return list(offsets)
    folded_after = _qwen_fold_bracket_width(after)
    folded_quote = _qwen_fold_bracket_width(quote)
    if after not in quote and folded_after not in folded_quote:
        return list(offsets)
    return [offset for offset in offsets if not (0 <= offset < len(text) and text[offset] in TERMINAL_PUNCTUATION)]


def _qwen_offset_after_short_omitted_fragment(text: str, marker: str, before: str, quote: str, after_index: int) -> Optional[int]:
    before = normalize_ws(before)
    if not marker.startswith("*") or not before or not quote or after_index <= 0:
        return None
    if not any(f"{before}{marker_text}" in quote for marker_text in _qwen_marker_text_variants(marker)):
        return None
    prefix = text[:after_index]
    before_start = prefix.rfind(before)
    if before_start < 0:
        return None
    fragment = prefix[before_start + len(before) :]
    if len(fragment) != 1 or fragment.isspace() or fragment in TERMINAL_PUNCTUATION or fragment in _qwen_trailing_closing_punctuation():
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
    return "”’」』）】》〉〕〗｝)]}"


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








