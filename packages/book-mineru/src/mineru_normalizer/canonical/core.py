"""Main canonical pipeline orchestration.

build_canonical() runs the normalization pipeline in this order:

1. Infer layout stats and create the TextStyleAnalyzer.
2. Run process_page for each page.
3. Run extend_table_source_pages.
4. Run reconcile_figure_captions while the TextStyleAnalyzer is available.
5. Run reconcile_table_continuations.
6. Run the footnote lifecycle: promote, split, promote cross-page, merge.
7. Run merge_cross_page_paragraphs.
8. Run recover_missing_note_refs and resolve_note_links.
9. Run the display quote reconciliation passes.
10. Run normalize_display_blocks_for_layout_schema.
11. Build metadata and the table of contents.

The list above is documentation only; the executable order is the explicit
function call sequence inside build_canonical().
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..analysis.note_gap_report import build_note_ref_gap_report
from ..analysis.layout import infer_layout_stats
from ..analysis.text_style import TextStyleAnalyzer
from ..schema.models import IdFactory, RawBlock
from .output_schema import normalize_display_blocks_for_layout_schema
from .page_processing import build_toc_from_blocks, extend_table_source_pages, process_page
from ..reconcile import (
    merge_continuation_footnotes,
    merge_cross_page_paragraphs,
    promote_cross_page_footnote_continuation_paragraphs,
    promote_page_reference_list_footnotes,
    recover_missing_note_refs,
    reconcile_cjk_numbered_display_quotes,
    reconcile_display_quotes,
    reconcile_figure_captions,
    reconcile_generic_display_quote_structures,
    reconcile_table_continuations,
    resolve_note_links,
    split_page_footnote_blocks,
)
from ..reconcile.notes.qwen_marker_locator import QwenMarkerLocatorConfig, run_qwen_marker_locator_repairs
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
    promote_cross_page_footnote_continuation_paragraphs(blocks)
    merge_continuation_footnotes(blocks)
    merge_cross_page_paragraphs(blocks, args.source_pdf, layout, allow_missing_pdf_text=getattr(args, "allow_missing_pdf_text", False))
    marker_locator_evidence = []
    marker_locator_enabled = bool(getattr(args, "marker_locator_repair", False))
    with trace_note_calls(getattr(args, "note_trace_log", None)):
        if marker_locator_enabled:
            marker_locator_config = _qwen_marker_locator_config(args)
            marker_locator_evidence = run_qwen_marker_locator_repairs(
                blocks,
                marker_locator_config,
                missing_body_ref_pages_after_page=lambda evidence: _recover_note_refs_and_missing_pages(
                    blocks,
                    qwen_marker_pages=evidence,
                ),
            )
        _recover_and_resolve_note_refs(blocks, qwen_marker_pages=marker_locator_evidence)
    reconcile_display_quotes(blocks, layout)
    reconcile_cjk_numbered_display_quotes(blocks, layout)
    reconcile_generic_display_quote_structures(blocks, layout)
    normalize_display_blocks_for_layout_schema(blocks)

    block_types = ["heading", "paragraph", "toc_item", "display_block", "figure", "caption", "table", "table_continuation", "list_item"]
    if any(b.get("type") == "footnote" for b in blocks):
        block_types.append("footnote")

    source_files = {}
    for k in ["content_list_v2", "content_list", "middle", "model", "md", "source_pdf"]:
        v = getattr(args, k, None)
        if v:
            source_files[k] = str(v)

    canonical = {
        "metadata": {
            "doc_id": args.doc_id or infer_doc_id(args),
            "title": args.title,
            "language": args.language,
            "source_files": source_files,
            "parser_name": "mineru_vlm",
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
                    "model": getattr(args, "marker_locator_model", "qwen3.5:9b"),
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
            "note_trace_log": str(getattr(args, "note_trace_log", "")) or None,
            "note_recovery_mode": "qwen",
            "type_system": {
                "block_types": block_types,
                "content_forms": [],
                "note": "Display text block types are layout-first; semantic forms are not emitted.",
            },
        },
        "toc": [],
        "blocks": blocks,
    }
    canonical["toc"] = build_toc_from_blocks(blocks)
    return canonical


def _recover_note_refs_and_missing_pages(
    blocks: List[Dict[str, Any]],
    *,
    qwen_marker_pages: List[Any],
) -> List[int]:
    _recover_and_resolve_note_refs(blocks, qwen_marker_pages=qwen_marker_pages)
    return _missing_body_ref_pages(blocks)


def _recover_and_resolve_note_refs(
    blocks: List[Dict[str, Any]],
    *,
    qwen_marker_pages: List[Any],
) -> None:
    recover_missing_note_refs(blocks, qwen_marker_pages=qwen_marker_pages)
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


def _clear_note_referenced_by(blocks: List[Dict[str, Any]]) -> None:
    for block in blocks:
        attrs = block.get("attrs")
        if isinstance(attrs, dict) and block.get("type") == "footnote":
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
        model=getattr(args, "marker_locator_model", "qwen3.5:9b"),
        api_url=getattr(args, "marker_locator_api_url", "http://127.0.0.1:11434/api/chat"),
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
    return 300


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
