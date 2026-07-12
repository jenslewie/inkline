"""CLI entry point for building a BookSkeleton directly from MinerU raw artifacts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from inkline.canonical import validate_book_skeleton, validate_observed_document
from inkline.llm import DEFAULT_OLLAMA_CHAT_URL, DEFAULT_QWEN_MODEL

from ..extraction.io import load_inputs, load_json
from ..normalize.book_skeleton_shadow import build_book_skeleton_shadow
from ..normalize.observed_shadow import build_observed_document_shadow
from ..reconcile import resolve_source_pdf_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a BookSkeleton directly from MinerU raw artifacts."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--content-list-v2",
        dest="content_list_v2",
        help="MinerU content_list_v2.json; preferred input.",
    )
    input_group.add_argument(
        "--content-list",
        dest="content_list",
        help="MinerU content_list.json fallback input.",
    )
    parser.add_argument("--middle", help="MinerU middle.json for page geometry and title evidence.")
    parser.add_argument("--source-pdf", help="Original PDF used to render TOC images for --llm.")
    parser.add_argument(
        "--allow-missing-pdf-text",
        action="store_true",
        help="Allow a PDF without a readable text layer when deriving observation metrics.",
    )
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--output", required=True, help="BookSkeleton JSON output path.")
    parser.add_argument(
        "--llm",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use the local multimodal LLM to read rendered TOC pages.",
    )
    parser.add_argument("--llm-model", default=DEFAULT_QWEN_MODEL)
    parser.add_argument("--llm-api-url", default=DEFAULT_OLLAMA_CHAT_URL)
    parser.add_argument("--llm-timeout-seconds", type=int, default=300)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.source_pdf = resolve_source_pdf_path(
        args.source_pdf, allow_missing=args.allow_missing_pdf_text
    )
    if args.llm and not args.source_pdf:
        raise ValueError("--llm requires a readable --source-pdf to render TOC page images.")

    pages, page_sizes = load_inputs(args)
    output_path = Path(args.output)
    observed = build_observed_document_shadow(
        pages=pages,
        page_sizes=page_sizes,
        metadata=_observed_metadata(args, output_path),
        middle=load_json(args.middle),
        source_pdf=args.source_pdf,
        allow_missing_pdf_text=args.allow_missing_pdf_text,
    )
    validate_observed_document(observed)
    skeleton = build_book_skeleton_shadow(
        observed,
        use_llm=args.llm,
        source_pdf=args.source_pdf,
        image_output_dir=(
            output_path.parent / f"{output_path.stem}_toc_llm_pages"
        ),
        llm_model=args.llm_model,
        llm_api_url=args.llm_api_url,
        llm_timeout_seconds=args.llm_timeout_seconds,
    )
    validate_book_skeleton(skeleton)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_path} with {len(skeleton['toc_entries'])} TOC entries")


def _observed_metadata(args: argparse.Namespace, output_path: Path) -> dict[str, Any]:
    source_file = args.source_pdf or args.content_list_v2 or args.content_list or ""
    doc_id = args.doc_id or Path(source_file).stem or "mineru_document"
    return {
        "doc_id": doc_id,
        "title": args.title or doc_id,
        "language": args.language,
        "source_file": _relative_to_output(source_file, output_path.parent),
        "parser_name": "mineru",
        "parser_mode": "vlm",
    }


def _relative_to_output(value: str, output_dir: Path) -> str:
    if not value:
        return ""
    path = Path(value).expanduser().resolve()
    base = output_dir.expanduser().resolve()
    return Path(os.path.relpath(path, base)).as_posix()
