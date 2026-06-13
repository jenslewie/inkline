"""Resolve inline note runs to page-footnote and endnote definitions."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, cast

from ...extraction.text import normalize_note_marker
from ...schema.block_types import FOOTNOTE
from ...schema.models import CanonicalBlock
from ..block_access import block_id as _block_id
from ..notes.keys import leading_note_marker as _com_leading_note_marker
from .marker_inline import _note_refs
from .scopes import (
    _EndnoteSectionStrategy,
    _NoteCandidate,
    _NoteContext,
    _NoteResolutionStrategy,
    _pages_for_block,
)

__all__ = ["resolve_note_links"]


class _PageFootnoteStrategy:
    name = "page_footnote"

    def collect(self, blocks: List[CanonicalBlock], context: _NoteContext) -> List[_NoteCandidate]:
        out: List[_NoteCandidate] = []
        for block in blocks:
            if block.get("type") != FOOTNOTE:
                continue
            bid = _block_id(block)
            if not bid:
                continue
            marker = normalize_note_marker(
                (block.get("attrs") or {}).get("note_marker", "")
            ) or _leading_note_marker(block.get("text", ""))
            for page in _pages_for_block(block):
                out.append(
                    _NoteCandidate(
                        block_id=bid,
                        marker=marker,
                        page=page,
                        strategy=self.name,
                        confidence="high" if marker else "medium",
                    )
                )
        return out

    def resolve(
        self,
        ref_block: CanonicalBlock,
        ref: Dict[str, Any],
        candidates: List[_NoteCandidate],
        context: _NoteContext,
    ) -> Optional[_NoteCandidate]:
        marker = normalize_note_marker(ref.get("marker", ""))
        ref_pages = _pages_for_ref(ref_block, ref, context)
        page_candidates = [c for c in candidates if c.strategy == self.name and c.page in ref_pages]
        exact = [c for c in page_candidates if c.marker == marker]
        if len(exact) == 1:
            return exact[0]
        unmarked = [c for c in page_candidates if not c.marker]
        if len(unmarked) == 1 and len(_refs_for_page(ref_block, context, marker)) == 1:
            return unmarked[0]
        return None


def resolve_note_links(blocks: List[Dict[str, Any]]) -> None:
    """Resolve note links — pipeline boundary entry point.

    ``blocks`` arrives from the canonical pipeline as ``List[Dict[str, Any]]``.
    Internally the note subsystem uses ``List[CanonicalBlock]`` for type
    precision.  The cast bridges the two until the full pipeline migration.
    """
    typed_blocks = cast(List[CanonicalBlock], blocks)
    context = _NoteContext(typed_blocks)
    strategies: List[_NoteResolutionStrategy] = [
        _PageFootnoteStrategy(),
        _EndnoteSectionStrategy("chapter_endnote", scope_required=True),
        _EndnoteSectionStrategy("book_endnote", scope_required=False),
    ]
    candidates: List[_NoteCandidate] = []
    for strategy in strategies:
        candidates.extend(strategy.collect(typed_blocks, context))
    if not candidates:
        return

    by_id: Dict[str, CanonicalBlock] = {_block_id(b): b for b in typed_blocks if _block_id(b)}
    _filter_invalid_note_refs(typed_blocks)
    _annotate_note_definitions(candidates, by_id)
    _suppress_lower_confidence_duplicate_page_footnote_refs(typed_blocks, by_id)
    resolved_candidate_by_note: Dict[str, _NoteCandidate] = {}
    for block in typed_blocks:
        refs = _note_refs(block)
        if not refs:
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            existing_target = ref.get("target_block_id")
            if isinstance(existing_target, str) and existing_target in by_id:
                continue
            match = _first_resolution(strategies, block, ref, candidates, context)
            if not match:
                continue
            ref["target_block_id"] = match.block_id
            ref["target_note_id"] = match.note_id
            ref["note_strategy"] = match.strategy
            ref["resolution_confidence"] = match.confidence
            resolved_candidate_by_note.setdefault(match.block_id, match)

    _suppress_lower_confidence_duplicate_page_footnote_refs(typed_blocks, by_id)
    resolved_by_note, resolved_markers_by_note = _resolved_note_indexes(typed_blocks, by_id)

    for candidate in candidates:
        if candidate.block_id not in resolved_by_note:
            continue
        selected = resolved_candidate_by_note.get(candidate.block_id, candidate)
        if selected != candidate:
            continue
        note_block = by_id.get(candidate.block_id)
        if not note_block:
            continue
        attrs = note_block.setdefault("attrs", {})
        attrs.setdefault("note_id", candidate.note_id)
        if candidate.marker:
            attrs.setdefault("note_marker", candidate.marker)
        elif not attrs.get("note_marker"):
            inferred_marker = _single_resolved_marker_for_note(
                candidate.block_id, resolved_markers_by_note
            )
            if (
                inferred_marker
                and note_block.get("type") == FOOTNOTE
                and attrs.get("role") == "page_footnote"
            ):
                attrs["note_marker"] = inferred_marker
                attrs.setdefault("note_marker_source", "resolved_body_ref")
        attrs.setdefault("note_strategy", candidate.strategy)
        if candidate.scope_key:
            attrs.setdefault("note_scope", candidate.scope_key)
        refs = sorted({x for x in resolved_by_note.get(candidate.block_id, []) if x})
        if refs:
            attrs["referenced_by"] = refs


def _resolved_note_indexes(
    blocks: List[CanonicalBlock],
    by_id: Dict[str, CanonicalBlock],
) -> tuple[Dict[str, List[str]], Dict[str, set[str]]]:
    resolved_by_note: Dict[str, List[str]] = {}
    resolved_markers_by_note: Dict[str, set[str]] = {}
    for block in blocks:
        for ref in _note_refs(block):
            target_id = ref.get("target_block_id")
            if isinstance(target_id, str) and target_id in by_id:
                _record_resolved_note_ref(
                    block, ref, target_id, resolved_by_note, resolved_markers_by_note
                )
    return resolved_by_note, resolved_markers_by_note


def _suppress_lower_confidence_duplicate_page_footnote_refs(
    blocks: List[CanonicalBlock], by_id: Dict[str, CanonicalBlock]
) -> None:
    refs_by_target: Dict[str, List[tuple[CanonicalBlock, Dict[str, Any]]]] = {}
    for block in blocks:
        if block.get("type") == FOOTNOTE:
            continue
        for ref in _note_refs(block):
            target_id = ref.get("target_block_id")
            target = by_id.get(str(target_id or ""))
            target_attrs = (
                target.get("attrs")
                if isinstance(target, dict) and isinstance(target.get("attrs"), dict)
                else {}
            )
            if (
                not target
                or target.get("type") != FOOTNOTE
                or target_attrs.get("role") != "page_footnote"
            ):
                continue
            refs_by_target.setdefault(str(target_id), []).append((block, ref))
    for _target_id, entries in refs_by_target.items():
        if len(entries) <= 1:
            continue
        ranked = [(_note_ref_source_rank(ref), block, ref) for block, ref in entries]
        best_rank = max(rank for rank, _block, _ref in ranked)
        if sum(1 for rank, _block, _ref in ranked if rank == best_rank) != 1:
            continue
        for rank, block, ref in ranked:
            if rank == best_rank:
                continue
            _remove_note_ref(block, ref)


def _note_ref_source_rank(ref: Dict[str, Any]) -> int:
    source = str(ref.get("source") or "")
    if source in {"equation_inline", "equation_interline", "trailing_text"}:
        return 100
    if source in {"qwen_marker_locator", "glm_ocr"}:
        return 90
    if source in {"secondary_page_sequence_gap", "secondary_page_missing_ref"}:
        return 60
    if source in {"recovered_text"}:
        return 40
    if source in {"page_single_marker_image"}:
        return 30
    if source in {"page_sequence_gap", "sequence_gap"}:
        return 20
    return 50


def _remove_note_ref(block: CanonicalBlock, ref_to_remove: Dict[str, Any]) -> None:
    attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
    runs = attrs.get("inline_runs")
    if isinstance(runs, list) and any(run is ref_to_remove for run in runs):
        kept_runs = [run for run in runs if run is not ref_to_remove]
        if any(isinstance(run, dict) and run.get("type") == "note_ref" for run in kept_runs):
            attrs["inline_runs"] = kept_runs
        else:
            attrs.pop("inline_runs", None)
        legacy_refs = attrs.get("note_refs")
        if isinstance(legacy_refs, list):
            removed_legacy = False
            kept_legacy = []
            for legacy_ref in legacy_refs:
                if (
                    not removed_legacy
                    and isinstance(legacy_ref, dict)
                    and _same_note_ref(legacy_ref, ref_to_remove)
                ):
                    removed_legacy = True
                    continue
                kept_legacy.append(legacy_ref)
            if kept_legacy:
                attrs["note_refs"] = kept_legacy
            else:
                attrs.pop("note_refs", None)
        return
    refs = [ref for ref in attrs.get("note_refs") or [] if ref is not ref_to_remove]
    if refs:
        attrs["note_refs"] = refs
    else:
        attrs.pop("note_refs", None)


def _record_resolved_note_ref(
    block: CanonicalBlock,
    ref: Dict[str, Any],
    target_block_id: str,
    resolved_by_note: Dict[str, List[str]],
    resolved_markers_by_note: Dict[str, set[str]],
) -> None:
    source_block_id = _block_id(block)
    if source_block_id:
        resolved_by_note.setdefault(target_block_id, []).append(source_block_id)
    marker = normalize_note_marker(ref.get("marker", ""))
    if marker:
        resolved_markers_by_note.setdefault(target_block_id, set()).add(marker)


def _same_note_ref(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return (
        normalize_note_marker(left.get("marker", ""))
        == normalize_note_marker(right.get("marker", ""))
        and str(left.get("source") or "") == str(right.get("source") or "")
        and left.get("source_page") == right.get("source_page")
    )


def _single_resolved_marker_for_note(
    block_id: str, resolved_markers_by_note: Dict[str, set[str]]
) -> Optional[str]:
    markers = resolved_markers_by_note.get(block_id) or set()
    if len(markers) != 1:
        return None
    return next(iter(markers))


def _annotate_note_definitions(
    candidates: List[_NoteCandidate], by_id: Dict[str, CanonicalBlock]
) -> None:
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.block_id in seen:
            continue
        seen.add(candidate.block_id)
        note_block = by_id.get(candidate.block_id)
        if not note_block:
            continue
        attrs = note_block.setdefault("attrs", {})
        attrs.setdefault("note_id", candidate.note_id)
        if candidate.marker:
            attrs.setdefault("note_marker", candidate.marker)
        attrs.setdefault("note_strategy", candidate.strategy)
        if candidate.scope_key:
            attrs.setdefault("note_scope", candidate.scope_key)


def _filter_invalid_note_refs(blocks: List[CanonicalBlock]) -> None:
    for block in blocks:
        attrs = block.get("attrs")
        if not isinstance(attrs, dict):
            continue
        suppressed = list(attrs.get("suppressed_note_refs") or [])
        for ref in list(_note_refs(block)):
            if not _invalid_note_ref_marker(ref.get("marker")):
                continue
            bad = dict(ref)
            bad.pop("type", None)
            bad["suppress_reason"] = "not_a_note_marker"
            suppressed.append(bad)
            _remove_note_ref(block, ref)
        if suppressed:
            attrs["suppressed_note_refs"] = suppressed


def _invalid_note_ref_marker(marker: Any) -> bool:
    text = str(marker or "")
    return "%" in text or "％" in text or "‰" in text


def _first_resolution(
    strategies: Iterable[_NoteResolutionStrategy],
    block: CanonicalBlock,
    ref: Dict[str, Any],
    candidates: List[_NoteCandidate],
    context: _NoteContext,
) -> Optional[_NoteCandidate]:
    for strategy in strategies:
        match = strategy.resolve(block, ref, candidates, context)
        if match:
            return match
    return None


def _pages_for_ref(block: CanonicalBlock, ref: Dict[str, Any], context: _NoteContext) -> List[int]:
    source_page = ref.get("source_page")
    if isinstance(source_page, int):
        return [source_page]
    source_pages = ref.get("source_pages")
    if isinstance(source_pages, list):
        pages = [int(p) for p in source_pages if isinstance(p, int)]
        if pages:
            return pages
    return context.pages_for(block)


def _leading_note_marker(text: str) -> Optional[str]:
    return _com_leading_note_marker(text, include_superscript=True)


def _refs_for_page(
    ref_block: CanonicalBlock, context: _NoteContext, marker: str
) -> List[Dict[str, Any]]:
    refs = []
    for ref in _note_refs(ref_block):
        if normalize_note_marker(ref.get("marker", "")) == marker:
            refs.append(ref)
    return refs
