"""Note page and body-reference candidate helpers for the Qwen marker locator.

The GLM-OCR engine has been removed; the remaining helpers in this module
compute problem-page plans and body-reference candidate blocks that the
Qwen marker locator uses to decide which pages to inspect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

from ...extraction.text import normalize_ws
from ..block_access import block_bbox, block_page, block_pages
from .marker_patterns import BODY_TYPES, _marker_int
from .keys import leading_note_marker
from .scopes import _EndnoteSectionStrategy, _NoteContext


@dataclass(frozen=True)
class _ProblemPagePlan:
    footnote_pages: Set[int]
    body_ref_pages: Set[int]
    body_candidate_block_ids: Set[int] = field(default_factory=set)


def _problem_page_plan(blocks: List[Dict[str, Any]]) -> _ProblemPagePlan:
    footnotes_by_page = _page_footnotes_by_page(blocks)
    footnote_pages: Set[int] = set()
    body_ref_pages: Set[int] = set()
    refs_by_page = _body_ref_items_by_page(blocks)
    body_candidate_block_ids: Set[int] = set()
    for page, footnotes in footnotes_by_page.items():
        markers = [leading_note_marker(str(block.get("text") or ""), include_superscript=True) for block in footnotes]
        if any(marker is None for marker in markers):
            footnote_pages.add(page)
        defs = {marker for marker in markers if marker}
        refs = {str(marker) for _idx, _block, marker in refs_by_page.get(page, [])}
        if defs and not defs.issubset(refs):
            body_ref_pages.add(page)
            body_candidate_block_ids.update(_fallback_page_body_candidate_block_ids(blocks, page))
        body_candidate_block_ids.update(_anchored_body_candidate_block_ids(blocks, page, markers, refs_by_page.get(page, [])))
    body_candidate_block_ids.update(_endnote_body_candidate_block_ids(blocks))
    for block in blocks:
        if id(block) in body_candidate_block_ids:
            body_ref_pages.update(block_pages(block))
    return _ProblemPagePlan(
        footnote_pages=footnote_pages,
        body_ref_pages=body_ref_pages,
        body_candidate_block_ids=body_candidate_block_ids,
    )


def _page_footnotes_by_page(blocks: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    out: Dict[int, List[Dict[str, Any]]] = {}
    for block in blocks:
        if block.get("type") != "footnote":
            continue
        attrs = block.get("attrs") or {}
        if attrs.get("role") != "page_footnote":
            continue
        page = block_page(block)
        if page is None:
            continue
        out.setdefault(page, []).append(block)
    for page_blocks in out.values():
        page_blocks.sort(key=lambda block: _footnote_sort_key(block))
    return out


def _footnote_sort_key(block: Dict[str, Any]) -> tuple[float, float, str]:
    bbox = block_bbox(block) or []
    y = float(bbox[1]) if len(bbox) >= 2 else 0.0
    x = float(bbox[0]) if len(bbox) >= 1 else 0.0
    return (y, x, str(block.get("id") or ""))


def _body_ref_items_by_page(blocks: List[Dict[str, Any]]) -> Dict[int, List[tuple[int, Dict[str, Any], int]]]:
    out: Dict[int, List[tuple[int, Dict[str, Any], int]]] = {}
    for block_index, block in enumerate(blocks):
        if block.get("type") not in BODY_TYPES:
            continue
        fallback_pages = block_pages(block)
        attrs = block.get("attrs") or {}
        for ref in attrs.get("note_refs") or []:
            if not isinstance(ref, dict):
                continue
            marker = _marker_int(ref.get("marker"))
            if marker is None:
                continue
            source_page = ref.get("source_page")
            pages = [source_page] if isinstance(source_page, int) else fallback_pages
            for page in pages:
                if isinstance(page, int):
                    out.setdefault(page, []).append((block_index, block, marker))
    for refs in out.values():
        refs.sort(key=lambda item: (item[0], item[2]))
    return out


def _anchored_body_candidate_block_ids(
    blocks: List[Dict[str, Any]],
    page: int,
    footnote_markers: Sequence[Optional[str]],
    refs: Sequence[tuple[int, Dict[str, Any], int]],
) -> Set[int]:
    defs = {marker_int for marker in footnote_markers if (marker_int := _marker_int(marker)) is not None}
    if len(defs) < 3 or not refs:
        return set()
    ref_markers = {marker for _idx, _block, marker in refs}
    candidate_ids: Set[int] = set()
    for missing in sorted(defs - ref_markers):
        left = max((marker for marker in defs if marker < missing and marker in ref_markers), default=None)
        right = min((marker for marker in defs if marker > missing and marker in ref_markers), default=None)
        if left is None or right is None:
            continue
        anchor_span = _closest_anchor_span(refs, left, right)
        if anchor_span is None:
            continue
        left_index, right_index = anchor_span
        if right_index - left_index < 2:
            continue
        for block in blocks[left_index + 1:right_index]:
            if _is_body_ref_candidate_block(block, page):
                candidate_ids.add(id(block))
    return candidate_ids


def _endnote_body_candidate_block_ids(blocks: List[Dict[str, Any]]) -> Set[int]:
    context = _NoteContext(blocks)
    candidates: Set[int] = set()
    for scope_key, defs in _chapter_endnote_defs_by_scope(blocks, context).items():
        refs = _body_ref_items_for_scope(blocks, context, scope_key)
        candidates.update(_anchored_scope_candidate_block_ids(blocks, context, refs, defs, scope_key=scope_key))
    book_defs = _book_endnote_defs(blocks, context)
    if book_defs:
        refs = _body_ref_items_for_scope(blocks, context, None)
        candidates.update(_anchored_scope_candidate_block_ids(blocks, context, refs, book_defs, scope_key=None))
    return candidates


def _chapter_endnote_defs_by_scope(blocks: List[Dict[str, Any]], context: _NoteContext) -> Dict[str, Set[int]]:
    out: Dict[str, Set[int]] = {}
    for candidate in _EndnoteSectionStrategy("chapter_endnote", scope_required=True).collect(blocks, context):
        marker = _marker_int(candidate.marker)
        if marker is not None and candidate.scope_key:
            out.setdefault(candidate.scope_key, set()).add(marker)
    return out


def _book_endnote_defs(blocks: List[Dict[str, Any]], context: _NoteContext) -> Set[int]:
    out: Set[int] = set()
    for candidate in _EndnoteSectionStrategy("book_endnote", scope_required=False).collect(blocks, context):
        marker = _marker_int(candidate.marker)
        if marker is not None:
            out.add(marker)
    return out


def _body_ref_items_for_scope(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
    scope_key: Optional[str],
) -> List[tuple[int, Dict[str, Any], int]]:
    out: List[tuple[int, Dict[str, Any], int]] = []
    for block_index, block in enumerate(blocks):
        if block.get("type") not in BODY_TYPES:
            continue
        if scope_key is not None and context.scope_for(block) != scope_key:
            continue
        attrs = block.get("attrs") or {}
        for ref in attrs.get("note_refs") or []:
            if not isinstance(ref, dict):
                continue
            marker = _marker_int(ref.get("marker"))
            if marker is not None:
                out.append((block_index, block, marker))
    out.sort(key=lambda item: (item[0], item[2]))
    return out


def _anchored_scope_candidate_block_ids(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
    refs: Sequence[tuple[int, Dict[str, Any], int]],
    defs: Set[int],
    *,
    scope_key: Optional[str],
) -> Set[int]:
    if len(defs) < 3 or not refs:
        return set()
    ref_markers = {marker for _idx, _block, marker in refs}
    candidate_ids: Set[int] = set()
    for missing in sorted(defs - ref_markers):
        left = max((marker for marker in defs if marker < missing and marker in ref_markers), default=None)
        right = min((marker for marker in defs if marker > missing and marker in ref_markers), default=None)
        if left is None or right is None:
            continue
        anchor_span = _closest_anchor_span(refs, left, right)
        if anchor_span is None:
            continue
        left_index, right_index = anchor_span
        if right_index - left_index < 2:
            continue
        for block in blocks[left_index + 1:right_index]:
            if _is_scope_body_ref_candidate_block(block, context, scope_key):
                candidate_ids.add(id(block))
    return candidate_ids


def _closest_anchor_span(refs: Sequence[tuple[int, Dict[str, Any], int]], left_anchor: int, right_anchor: int) -> Optional[tuple[int, int]]:
    spans: List[tuple[int, int]] = []
    left_indexes = [block_index for block_index, _block, marker in refs if marker == left_anchor]
    right_indexes = [block_index for block_index, _block, marker in refs if marker == right_anchor]
    for left_index in left_indexes:
        for right_index in right_indexes:
            if left_index < right_index:
                spans.append((left_index, right_index))
    if not spans:
        return None
    return min(spans, key=lambda span: span[1] - span[0])


def _fallback_page_body_candidate_block_ids(blocks: List[Dict[str, Any]], page: int) -> Set[int]:
    return {
        id(block)
        for block in blocks
        if _is_body_ref_candidate_block(block, page)
    }


def _is_body_ref_candidate_block(block: Dict[str, Any], page: int) -> bool:
    if block.get("type") not in BODY_TYPES:
        return False
    if page not in block_pages(block):
        return False
    if (block.get("attrs") or {}).get("note_refs"):
        return False
    if not normalize_ws(str(block.get("text") or "")):
        return False
    return block_bbox(block) is not None


def _is_scope_body_ref_candidate_block(block: Dict[str, Any], context: _NoteContext, scope_key: Optional[str]) -> bool:
    if block.get("type") not in BODY_TYPES:
        return False
    if scope_key is not None and context.scope_for(block) != scope_key:
        return False
    if (block.get("attrs") or {}).get("note_refs"):
        return False
    if not normalize_ws(str(block.get("text") or "")):
        return False
    return block_bbox(block) is not None