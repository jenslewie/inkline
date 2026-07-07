"""CLI entry point for the mineru-to-canonical command. Parses command-line arguments and delegates to build_canonical()."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from inkline.canonical import (
    build_bookgraph_from_observed,
    build_internal_canonical_from_observed,
    validate_book_skeleton,
    validate_bookgraph,
    validate_document,
    validate_internal_canonical,
    validate_observed_document,
)
from inkline.llm import DEFAULT_OLLAMA_CHAT_URL, DEFAULT_OLLAMA_KEEP_ALIVE, DEFAULT_QWEN_MODEL

from ..analysis.note_gap_report import write_note_ref_gap_report
from ..bridge import find_mineru_run_version_info, get_mineru_version_info
from ..extraction.io import load_inputs, load_json
from ..normalize.assets import materialize_image_assets
from ..normalize.book_skeleton_shadow import build_book_skeleton_shadow
from ..normalize.bookgraph_shadow import build_bookgraph_shadow
from ..normalize.core import (
    _normalize_qwen_evidence_paths,
    _qwen_marker_locator_artifact_dir,
    build_canonical,
)
from ..normalize.observed_shadow import build_observed_document_shadow
from ..reconcile import resolve_source_pdf_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Normalize MinerU VLM outputs to canonical.json")
    p.add_argument(
        "--content-list-v2",
        dest="content_list_v2",
        help="MinerU content_list_v2.json; preferred input",
    )
    p.add_argument(
        "--content-list", dest="content_list", help="MinerU content_list.json fallback input"
    )
    p.add_argument("--middle", help="MinerU middle.json; used for page sizes/layout metadata")
    p.add_argument("--model", help="MinerU model.json; stored as source metadata")
    p.add_argument("--md", help="MinerU markdown file; stored as source metadata")
    p.add_argument("--source-pdf", help="Original PDF path; stored as source metadata")
    p.add_argument(
        "--allow-missing-pdf-text",
        action="store_true",
        help="Allow running without readable PDF text layer; cross-page paragraph merging will fall back to block bbox and may be less accurate",
    )
    p.add_argument(
        "--marker-locator-repair",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use local Qwen visual marker locator to repair targeted problem pages (disabled by default)",
    )
    p.add_argument(
        "--marker-locator-artifact-dir",
        help="Directory for rendered Qwen marker locator pages and evidence JSON; defaults next to the output file",
    )
    p.add_argument(
        "--marker-locator-model",
        default=DEFAULT_QWEN_MODEL,
        help="Local Ollama visual model name for marker location",
    )
    p.add_argument(
        "--marker-locator-api-url",
        default=DEFAULT_OLLAMA_CHAT_URL,
        help="Local Ollama chat endpoint for marker location",
    )
    p.add_argument(
        "--marker-locator-keep-alive",
        default=DEFAULT_OLLAMA_KEEP_ALIVE,
        help="Ollama keep_alive value for Qwen marker locator requests",
    )
    p.add_argument(
        "--marker-locator-dpi",
        type=int,
        default=None,
        help="Deprecated shorthand that sets both page and block DPI for Qwen marker location",
    )
    p.add_argument(
        "--marker-locator-page-dpi",
        type=int,
        default=150,
        help="DPI for Qwen full-page body-ref marker location",
    )
    p.add_argument(
        "--marker-locator-block-dpi",
        type=int,
        default=200,
        help="DPI for Qwen paragraph-block retry marker location",
    )
    p.add_argument(
        "--marker-locator-max-megapixels",
        type=float,
        default=0.0,
        help="Maximum megapixels for one Qwen marker locator image; 0 disables the limit",
    )
    p.add_argument(
        "--marker-locator-body-mode",
        choices=["page", "block", "page_then_block"],
        default="page_then_block",
        help="How Qwen should inspect body-side note refs: full page, individual body block crops, or page first with block retry for missing pages",
    )
    p.add_argument(
        "--marker-locator-reuse-evidence",
        action="store_true",
        help="Reuse existing Qwen marker locator evidence JSON entries when the rendered image name matches",
    )
    p.add_argument(
        "--marker-locator-timing-log",
        help="JSONL timing log for each Qwen marker locator page and model call; defaults inside the artifact directory",
    )
    p.add_argument(
        "--note-recovery-mode",
        choices=["qwen"],
        default="qwen",
        help="Missing note-ref recovery strategy (qwen-only visual evidence recovery)",
    )
    p.add_argument(
        "--note-trace-log",
        help="Write a summary JSON of reconcile.notes function/method call counts for this normalization run",
    )
    p.add_argument("--output", default="canonical.json", help="Output canonical JSON path")
    p.add_argument(
        "--bookgraph-output",
        help="Optional shadow BookGraph canonical_v2.json output path for development validation",
    )
    p.add_argument(
        "--observed-output",
        help="Optional parser-neutral observed_document.json shadow output path",
    )
    p.add_argument(
        "--bookgraph-from-observed-output",
        help="Optional BookGraph output built from observed_document shadow data",
    )
    p.add_argument(
        "--internal-canonical-output",
        help="Optional audit-first internal canonical output built from observed_document data",
    )
    p.add_argument(
        "--book-skeleton-output",
        help="Optional BookSkeleton shadow output built from observed_document data",
    )
    p.add_argument(
        "--book-skeleton-llm",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use local LLM TOC classification when writing --book-skeleton-output",
    )
    p.add_argument(
        "--book-skeleton-llm-model",
        default=DEFAULT_QWEN_MODEL,
        help="Local Ollama model for BookSkeleton TOC classification",
    )
    p.add_argument(
        "--book-skeleton-llm-api-url",
        default=DEFAULT_OLLAMA_CHAT_URL,
        help="Local Ollama chat endpoint for BookSkeleton TOC classification",
    )
    p.add_argument(
        "--book-skeleton-llm-timeout-seconds",
        type=int,
        default=300,
        help="Timeout for BookSkeleton TOC classification model calls",
    )
    p.add_argument("--doc-id", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--language", default="zh-CN")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.source_pdf = resolve_source_pdf_path(
        args.source_pdf, allow_missing=args.allow_missing_pdf_text
    )
    version_info = (
        find_mineru_run_version_info(
            args.content_list_v2,
            args.content_list,
            args.middle,
            args.model,
            args.md,
        )
        or get_mineru_version_info()
    )
    args.mineru_version = version_info.get("mineru_version")
    args.mineru_vl_utils_version = version_info.get("mineru_vl_utils_version")
    args.vlm_model = version_info.get("vlm_model")
    pages, page_sizes = load_inputs(args)
    args._middle = load_json(args.middle)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    canonical = build_canonical(pages, page_sizes, args)
    materialize_image_assets(canonical, args.source_pdf, out.parent)
    _normalize_qwen_evidence_paths(
        canonical,
        out.parent,
        artifact_dir=_qwen_marker_locator_artifact_dir(args),
    )
    validate_document(canonical)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(canonical, f, ensure_ascii=False, indent=2)
    if args.bookgraph_output:
        bookgraph = build_bookgraph_shadow(canonical)
        validate_bookgraph(bookgraph)
        bookgraph_out = Path(args.bookgraph_output)
        bookgraph_out.parent.mkdir(parents=True, exist_ok=True)
        with open(bookgraph_out, "w", encoding="utf-8") as f:
            json.dump(bookgraph, f, ensure_ascii=False, indent=2)
    _write_observed_shadow_outputs(args, pages, page_sizes, canonical)
    report_path, report = write_note_ref_gap_report(canonical, out)
    print(
        f"Wrote {out} with {len(canonical['blocks'])} blocks and {len(canonical['toc'])} toc entries"
    )
    print(
        f"Wrote {report_path} with "
        f"{report['summary']['missing_body_ref_notes']} missing body note ref(s)"
    )


def _write_observed_shadow_outputs(args, pages, page_sizes, canonical) -> None:
    if not (
        args.observed_output
        or args.bookgraph_from_observed_output
        or args.internal_canonical_output
        or args.book_skeleton_output
    ):
        return
    observed = build_observed_document_shadow(
        pages=pages,
        page_sizes=page_sizes,
        metadata=canonical["metadata"],
        assets=canonical.get("assets") or {},
        middle=getattr(args, "_middle", None),
        source_pdf=args.source_pdf,
        allow_missing_pdf_text=args.allow_missing_pdf_text,
    )
    validate_observed_document(observed)
    if args.observed_output:
        _write_json(Path(args.observed_output), observed)
    if args.bookgraph_from_observed_output:
        observed_bookgraph = build_bookgraph_from_observed(observed)
        validate_bookgraph(observed_bookgraph)
        _write_json(Path(args.bookgraph_from_observed_output), observed_bookgraph)
    if args.internal_canonical_output:
        internal_canonical = build_internal_canonical_from_observed(observed)
        validate_internal_canonical(internal_canonical)
        _write_json(Path(args.internal_canonical_output), internal_canonical)
    if args.book_skeleton_output:
        skeleton = build_book_skeleton_shadow(
            observed,
            use_llm=args.book_skeleton_llm,
            llm_model=args.book_skeleton_llm_model,
            llm_api_url=args.book_skeleton_llm_api_url,
            llm_timeout_seconds=args.book_skeleton_llm_timeout_seconds,
        )
        validate_book_skeleton(skeleton)
        _write_json(Path(args.book_skeleton_output), skeleton)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
