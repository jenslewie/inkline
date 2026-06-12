"""Main canonical pipeline orchestration.

build_canonical() runs in four layers:

1. Page-level canonicalization:
   - Infer document-level layout stats and create the TextStyleAnalyzer.
   - Process raw MinerU blocks one page at a time with process_page.
   - Append each page's canonical blocks into one global blocks list.
   - Carry only lightweight flow state across pages, such as prev_major_type
     and in_toc. The raw page contents are not first merged into one raw
     document before parsing.

2. Early whole-document cleanup before TextStyleAnalyzer is closed:
   - These passes are not page-level canonicalization because they run after
     all page outputs have been appended to the global blocks list. They are
     kept early because figure/caption cleanup still needs TextStyleAnalyzer.
   - Annotate source-page metadata for already emitted table_continuation
     blocks with extend_table_source_pages. This only marks the previous table
     as continued and extends source.pages; it does not merge table HTML or
     delete continuation blocks.
   - Reconcile figure structure while TextStyleAnalyzer is still available:
     absorb embedded figure text, merge adjacent figure fragments, and attach
     nearby caption blocks to figures.

3. Whole-document structural reconciliation over the global blocks list:
   - Reconcile true split-table continuations across adjacent pages with
     reconcile_table_continuations. This structural pass merges table HTML,
     source spans, and table footnotes, and removes continuation table or
     continuation marker blocks.
   - Run the footnote lifecycle: promote page reference-list entries, split
     page footnote blocks, recover unmarked markers, promote cross-page
     footnote continuations, and merge continuation footnotes.
   - Merge cross-page body paragraphs after float/table/footnote cleanup has
     reduced false flow boundaries.
   - Recover missing note references and resolve note links, optionally using
     the Qwen marker-locator repair loop before the final recovery/link pass.
   - Run display block reconciliation passes for layout-specific,
     CJK-numbered, and generic display-block structures.
   - Normalize display blocks to the public layout schema and remove internal
     note-ref indexes.

4. Canonical assembly:
   - Build metadata, page metadata, source map, assets container, and block
     type metadata.
   - Build the final table of contents from the reconciled canonical blocks.

The list above is documentation only; the executable order is the explicit
function call sequence inside build_canonical().
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from inkline.canonical import SCHEMA_VERSION

from ..analysis.note_gap_report import build_note_ref_gap_report
from ..extraction.text import normalize_note_marker, normalize_ws
from ..analysis.layout import infer_layout_stats
from ..analysis.pdf_page_metrics import PdfPageCache
from ..analysis.text_style import TextStyleAnalyzer
from ..schema.block_types import CANONICAL_BLOCK_TYPES, FOOTNOTE
from ..schema.models import IdFactory, RawBlock
from .output_schema import normalize_display_blocks_for_layout_schema, remove_internal_note_ref_indexes
from .page_processing import build_toc_from_blocks, extend_table_source_pages, process_page
from .page_roles import build_page_metadata
from ..reconcile import (
    merge_continuation_footnotes,
    merge_cross_page_paragraphs,
    promote_cross_page_footnote_continuation_paragraphs,
    promote_page_reference_list_footnotes,
    recover_unmarked_page_footnote_markers,
    recover_missing_note_refs,
    reconcile_cjk_numbered_display_blocks,
    reconcile_display_blocks,
    reconcile_figure_captions,
    reconcile_generic_display_block_structures,
    reconcile_table_continuations,
    resolve_note_links,
    split_page_footnote_blocks,
)
from ..reconcile.notes.qwen_marker_locator import QwenMarkerLocatorConfig, run_qwen_marker_locator_repairs
from ..reconcile.notes.marker_inline import _note_refs
from ..reconcile.notes.trace import trace_note_calls


def build_canonical(
    pages: Dict[int, List[RawBlock]],
    page_sizes: Dict[int, Tuple[float, float]],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    ids = IdFactory()
    layout = infer_layout_stats(pages, page_sizes)
    blocks: List[Dict[str, Any]] = []
    prev_major_type: Optional[str] = None
    in_toc = False
    text_style = TextStyleAnalyzer.from_raw_pages(getattr(args, "source_pdf", None), pages)

    try:
        for page in sorted(pages):
            page_out, prev_major_type, in_toc = process_page(
                ids,
                pages[page],
                layout,
                prev_major_type,
                in_toc,
                text_style=text_style,
            )
            blocks.extend(page_out)

        extend_table_source_pages(blocks)
        reconcile_figure_captions(blocks, text_style=text_style)
    finally:
        text_style.close()

    reconcile_table_continuations(blocks)
    promote_page_reference_list_footnotes(blocks)
    split_page_footnote_blocks(blocks)
    recover_unmarked_page_footnote_markers(blocks)
    promote_cross_page_footnote_continuation_paragraphs(blocks)
    merge_continuation_footnotes(blocks)
    merge_cross_page_paragraphs(blocks, args.source_pdf, layout, allow_missing_pdf_text=getattr(args, "allow_missing_pdf_text", False))
    marker_locator_evidence = []
    marker_locator_enabled = bool(getattr(args, "marker_locator_repair", False))
    with trace_note_calls(getattr(args, "note_trace_log", None)):
        note_cache = PdfPageCache(getattr(args, "source_pdf", None), {p: (layout.page_width, layout.page_height) for p in sorted(pages)}, allow_missing=True, render_zoom=3.0)
        try:
            if marker_locator_enabled:
                marker_locator_config = _qwen_marker_locator_config(args)
                marker_locator_evidence = run_qwen_marker_locator_repairs(
                    blocks,
                    marker_locator_config,
                    missing_body_ref_pages_after_page=lambda evidence: _recover_note_refs_and_missing_pages(
                        blocks,
                        args,
                        layout,
                        note_cache,
                        qwen_marker_pages=evidence,
                    ),
                )
            _recover_and_resolve_note_refs(
                blocks,
                args,
                layout,
                note_cache,
                qwen_marker_pages=marker_locator_evidence,
            )
        finally:
            note_cache.close()
    reconcile_display_blocks(blocks, layout)
    reconcile_cjk_numbered_display_blocks(blocks, layout)
    reconcile_generic_display_block_structures(blocks, layout)
    normalize_display_blocks_for_layout_schema(blocks)
    remove_internal_note_ref_indexes(blocks)

    source_files = {}
    for k in ["content_list_v2", "content_list", "middle", "model", "md", "source_pdf"]:
        v = getattr(args, k, None)
        if v:
            source_files[k] = str(v)

    source_file = (
        getattr(args, "source_pdf", None)
        or getattr(args, "md", None)
        or getattr(args, "content_list_v2", None)
        or getattr(args, "content_list", None)
        or ""
    )
    page_metadata = build_page_metadata(pages, layout, title=args.title, blocks=blocks)
    canonical = {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "doc_id": args.doc_id or infer_doc_id(args),
            "title": args.title,
            "language": args.language,
            "source_file": str(source_file),
            "source_files": source_files,
            "parser_name": "mineru",
            "parser_mode": str(getattr(args, "parser_mode", "vlm")),
            "mineru": {
                "version": getattr(args, "mineru_version", None),
                "vlm_utils_version": getattr(args, "mineru_vl_utils_version", None),
                "vlm_model": getattr(args, "vlm_model", None),
                "normalizer": "mineru_to_canonical.py",
                "normalizer_version": "0.3.0",
                "layout_stats": {
                    "page_width": layout.page_width,
                    "page_height": layout.page_height,
                    "body_left": layout.body_left,
                    "body_right": layout.body_right,
                },
                "auxiliary_ocr": {
                    "qwen_marker_locator": {
                        "enabled": marker_locator_enabled,
                        "repair_enabled": marker_locator_enabled,
                        "model": getattr(args, "marker_locator_model", "qwen3.6:35b-a3b"),
                        "keep_alive": getattr(args, "marker_locator_keep_alive", "2h"),
                        "body_mode": getattr(args, "marker_locator_body_mode", "page_then_block"),
                        "page_dpi": _marker_locator_page_dpi(args),
                        "block_dpi": _marker_locator_block_dpi(args),
                        "pages": sorted({item.page for item in marker_locator_evidence}),
                        "evidence": [
                            {"page": item.page, "kind": item.kind}
                            for item in marker_locator_evidence
                        ],
                        "artifact_dir": str(_qwen_marker_locator_artifact_dir(args)) if marker_locator_enabled else None,
                        "timing_log": str(_qwen_marker_locator_timing_log_path(args)) if marker_locator_enabled else None,
                    }
                },
                "note_trace_log": getattr(args, "note_trace_log", None) or None,
                "note_recovery_mode": str(getattr(args, "note_recovery_mode", "qwen")),
                "type_system": {
                    "block_types": list(CANONICAL_BLOCK_TYPES),
                    "content_forms": [],
                    "note": "display_block is layout-first; semantic forms are not emitted.",
                },
            },
        },
        "toc": [],
        "pages": page_metadata,
        "blocks": blocks,
        "assets": {"images": []},
        "source_map": [
            {
                "block_id": block["block_id"],
                "page": (block.get("source") or {}).get("page"),
                "bbox": (block.get("source") or {}).get("bbox"),
                "parser_raw_id": (block.get("attrs") or {}).get("parser_raw_id"),
            }
            for block in blocks
        ],
    }
    canonical["toc"] = build_toc_from_blocks(blocks)
    return canonical


def _recover_note_refs_and_missing_pages(
    blocks: List[Dict[str, Any]],
    args: argparse.Namespace,
    layout: Any,
    note_cache: PdfPageCache,
    *,
    qwen_marker_pages: List[Any],
) -> List[int]:
    _recover_and_resolve_note_refs(
        blocks,
        args,
        layout,
        note_cache,
        qwen_marker_pages=qwen_marker_pages,
    )
    return _missing_or_unreliable_body_ref_pages(blocks, qwen_marker_pages=qwen_marker_pages)


def _recover_and_resolve_note_refs(
    blocks: List[Dict[str, Any]],
    args: argparse.Namespace,
    layout: Any,
    note_cache: PdfPageCache,
    *,
    qwen_marker_pages: List[Any],
) -> None:
    recover_missing_note_refs(
        blocks,
        args.source_pdf,
        layout,
        model_json=getattr(args, "model", None),
        pdf_cache=note_cache,
        qwen_marker_pages=qwen_marker_pages,
        recovery_mode=getattr(args, "note_recovery_mode", "qwen"),
    )
    _clear_note_referenced_by(blocks)
    resolve_note_links(blocks)


def _missing_body_ref_pages(blocks: List[Dict[str, Any]]) -> List[int]:
    report = build_note_ref_gap_report({"metadata": {}, "blocks": blocks})
    pages: set[int] = set()
    for item in report.get("missing_body_ref_notes") or []:
        page = item.get("page")
        if isinstance(page, int):
            pages.add(page)
    return sorted(pages)


def _missing_or_unreliable_body_ref_pages(blocks: List[Dict[str, Any]], *, qwen_marker_pages: List[Any] | None = None) -> List[int]:
    pages = set(_missing_body_ref_pages(blocks))
    qwen_markers_by_page = _qwen_body_ref_markers_by_page(qwen_marker_pages or [])
    refs_by_note_id: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
    for block in blocks:
        for ref in _note_refs(block):
            note_id = str(ref.get("target_note_id") or "")
            if note_id:
                refs_by_note_id.setdefault(note_id, []).append((block, ref))

    for block in blocks:
        if block.get("type") != FOOTNOTE:
            continue
        attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
        note_id = str(attrs.get("note_id") or "")
        marker = normalize_note_marker(attrs.get("note_marker", ""))
        if not note_id or not marker:
            continue
        page = (block.get("source") if isinstance(block.get("source"), dict) else {}).get("page")
        if not isinstance(page, int) or marker not in qwen_markers_by_page.get(page, set()):
            continue
        refs = refs_by_note_id.get(note_id) or []
        if refs and any(_has_reliable_inline_ref(ref_block, ref) for ref_block, ref in refs):
            continue
        pages.add(page)
    return sorted(pages)


def _has_reliable_inline_ref(block: Dict[str, Any], ref: Dict[str, Any]) -> bool:
    attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
    runs = attrs.get("inline_runs")
    if not isinstance(runs, list):
        return False
    reconstructed = "".join(
        str(run.get("text") or "")
        for run in runs
        if isinstance(run, dict) and run.get("type") == "text"
    )
    if normalize_ws(reconstructed) != normalize_ws(str(block.get("text") or "")):
        return False
    marker = normalize_note_marker(ref.get("marker", ""))
    return any(
        isinstance(run, dict)
        and run.get("type") == "note_ref"
        and normalize_note_marker(run.get("marker", "")) == marker
        and run.get("source_page") == ref.get("source_page")
        for run in runs
    )


def _qwen_body_ref_markers_by_page(qwen_marker_pages: List[Any]) -> Dict[int, set[str]]:
    out: Dict[int, set[str]] = {}
    for item in qwen_marker_pages:
        if hasattr(item, "to_json"):
            item = item.to_json()
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        if not isinstance(page, int):
            continue
        refs = item.get("body_refs") or []
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            marker = normalize_note_marker(str(ref.get("marker") or "").replace("＊", "*"))
            if marker:
                out.setdefault(page, set()).add(marker)
    return out


def _clear_note_referenced_by(blocks: List[Dict[str, Any]]) -> None:
    for block in blocks:
        attrs = block.get("attrs")
        if isinstance(attrs, dict) and block.get("type") == FOOTNOTE:
            attrs.pop("referenced_by", None)


def infer_doc_id(args: argparse.Namespace) -> str:
    for v in [args.source_pdf, args.md, args.content_list_v2, args.content_list]:
        if v:
            stem = Path(v).stem
            return re.sub(r"[^A-Za-z0-9_\-]+", "_", stem)
    return "mineru_document"


def _qwen_marker_locator_config(args: argparse.Namespace) -> QwenMarkerLocatorConfig:
    source_pdf = getattr(args, "source_pdf", None)
    if not source_pdf:
        raise ValueError("--marker-locator-repair requires --source-pdf")
    return QwenMarkerLocatorConfig(
        source_pdf=Path(source_pdf),
        artifact_dir=_qwen_marker_locator_artifact_dir(args),
        model=getattr(args, "marker_locator_model", "qwen3.6:35b-a3b"),
        api_url=getattr(args, "marker_locator_api_url", "http://127.0.0.1:11434/api/chat"),
        keep_alive=str(getattr(args, "marker_locator_keep_alive", "2h")),
        dpi=_marker_locator_page_dpi(args),
        page_dpi=_marker_locator_page_dpi(args),
        block_dpi=_marker_locator_block_dpi(args),
        max_megapixels=float(getattr(args, "marker_locator_max_megapixels", 0.0)),
        body_mode=str(getattr(args, "marker_locator_body_mode", "page_then_block")),
        reuse_evidence=bool(getattr(args, "marker_locator_reuse_evidence", False)),
        timing_log_path=_qwen_marker_locator_timing_log_path(args),
    )


def _marker_locator_page_dpi(args: argparse.Namespace) -> int:
    configured = getattr(args, "marker_locator_page_dpi", None)
    if configured is not None:
        return int(configured)
    legacy = getattr(args, "marker_locator_dpi", None)
    if legacy is not None:
        return int(legacy)
    return 150


def _marker_locator_block_dpi(args: argparse.Namespace) -> int:
    configured = getattr(args, "marker_locator_block_dpi", None)
    if configured is not None:
        return int(configured)
    legacy = getattr(args, "marker_locator_dpi", None)
    if legacy is not None:
        return int(legacy)
    return 200


def _qwen_marker_locator_artifact_dir(args: argparse.Namespace) -> Path:
    configured = getattr(args, "marker_locator_artifact_dir", None)
    if configured:
        return Path(configured)
    output = Path(getattr(args, "output", "canonical.json"))
    return output.parent / f"{output.stem}_qwen_marker_locator"


def _qwen_marker_locator_timing_log_path(args: argparse.Namespace) -> Path:
    configured = getattr(args, "marker_locator_timing_log", None)
    if configured:
        return Path(configured)
    return _qwen_marker_locator_artifact_dir(args) / "qwen_marker_timing.jsonl"
