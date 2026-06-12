"""Missing note reference recovery. Recovers missing inline note references by analyzing note definition sequences and Qwen visual evidence. Main entry: recover_missing_note_refs()."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple, cast

from ...analysis.pdf_page_metrics import PdfPageCache
from ...extraction.text import normalize_note_marker
from ...schema.block_types import FOOTNOTE
from ...schema.models import CanonicalBlock
from .keys import leading_note_marker
from .marker_location import _locate_qwen_body_ref  # compatibility re-export
from .marker_offsets import _qwen_marker_offset_in_text  # compatibility re-export
from .marker_patterns import _marker_int
from .marker_recovery import (
    _recover_direct_page_footnote_qwen_refs,
    _recover_direct_scoped_endnote_qwen_refs,
    _update_existing_qwen_ref_inline_location,  # compatibility re-export
)
from .resolver import _PageFootnoteStrategy
from .scopes import _EndnoteSectionStrategy, _NoteContext

__all__ = ["recover_missing_note_refs"]


def recover_missing_note_refs(blocks: List[Dict[str, Any]], source_pdf: Any = None, *_args: Any, pdf_cache: Optional[PdfPageCache] = None, **_kwargs: Any) -> None:
    """Recover conservative inline note refs before final note linking.

    MinerU sometimes preserves note bodies but flattens body-side markers into
    ordinary digits, or drops a single marker between two well-formed neighbors.
    This pass uses available note-definition sequences as guardrails and records
    recovered refs directly in ``attrs.inline_runs`` so ``resolve_note_links``
    can annotate the persisted representation in place.

    ``blocks`` arrives from the canonical pipeline as ``List[Dict[str, Any]]``.
    Internally the note subsystem uses ``List[CanonicalBlock]`` for type
    precision.  The cast bridges the two until the full pipeline migration.
    """
    typed_blocks = cast(List[CanonicalBlock], blocks)
    context = _NoteContext(typed_blocks)
    scope_defs, page_defs, book_defs = _collect_note_definition_markers(typed_blocks, context)
    page_symbol_defs = _collect_page_symbol_definition_markers(typed_blocks, context)
    if not scope_defs and not page_defs and not book_defs and not page_symbol_defs:
        return

    qwen_marker_pages = _kwargs.get("qwen_marker_pages") or _kwargs.get("marker_locator_pages")
    _recover_direct_page_footnote_qwen_refs(
        typed_blocks,
        context,
        page_defs,
        page_symbol_defs,
        qwen_marker_pages=qwen_marker_pages,
    )
    _recover_direct_scoped_endnote_qwen_refs(
        typed_blocks,
        context,
        qwen_marker_pages=qwen_marker_pages,
    )


def _collect_note_definition_markers(
    blocks: List[CanonicalBlock],
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


def _collect_page_symbol_definition_markers(blocks: List[CanonicalBlock], context: _NoteContext) -> Dict[int, Set[str]]:
    out: Dict[int, Set[str]] = {}
    for block in blocks:
        if block.get("type") != FOOTNOTE:
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
