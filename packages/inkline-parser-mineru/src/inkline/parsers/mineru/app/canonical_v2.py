"""Independent ObservedDocument-first orchestration for canonical v2."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from inkline.canonical import (
    build_bookgraph_from_observed,
    build_internal_canonical_from_observed,
    validate_book_skeleton,
    validate_bookgraph,
    validate_internal_canonical,
    validate_observed_document,
    validate_resolved_page_review,
)
from inkline.llm import DEFAULT_OLLAMA_CHAT_URL, DEFAULT_QWEN_MODEL

from ..extraction.io import load_inputs, load_json
from ..normalize.book_skeleton_shadow import build_book_skeleton_shadow
from ..normalize.observed_shadow import build_observed_document_shadow
from ..normalize.page_review_shadow import build_page_review_shadow
from ..normalize.v2_page_assets import materialize_v2_page_assets
from ..reconcile import resolve_source_pdf_path


def build_v2_artifacts(
    *,
    pages: dict[int, list[Any]],
    page_sizes: dict[int, tuple[float, float]],
    metadata: dict[str, Any],
    middle: Any | None,
    source_pdf: str,
    output_dir: Path,
    allow_missing_pdf_text: bool = False,
    use_skeleton_llm: bool = True,
    use_page_review_llm: bool = True,
    llm_model: str = DEFAULT_QWEN_MODEL,
    llm_api_url: str = DEFAULT_OLLAMA_CHAT_URL,
    llm_timeout_seconds: int = 300,
    on_stage_complete: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Build v2 artifacts in dependency order without constructing canonical v1."""

    observed = build_observed_document_shadow(
        pages=pages,
        page_sizes=page_sizes,
        metadata=metadata,
        assets={},
        middle=middle,
        source_pdf=source_pdf,
        allow_missing_pdf_text=allow_missing_pdf_text,
    )
    _emit_stage(on_stage_complete, "observed", observed)
    skeleton = build_book_skeleton_shadow(
        observed,
        use_llm=use_skeleton_llm,
        source_pdf=source_pdf,
        image_output_dir=output_dir / "book_skeleton_toc_llm_pages",
        llm_model=llm_model,
        llm_api_url=llm_api_url,
        llm_timeout_seconds=llm_timeout_seconds,
    )
    _emit_stage(on_stage_complete, "book_skeleton", skeleton)
    page_review = build_page_review_shadow(
        observed,
        skeleton,
        use_llm=use_page_review_llm,
        source_pdf=source_pdf,
        image_output_dir=output_dir / "page_review_llm_pages",
        llm_model=llm_model,
        llm_api_url=llm_api_url,
        llm_timeout_seconds=llm_timeout_seconds,
        checkpoint_path=output_dir / "page_review.checkpoint.json",
    )
    _emit_stage(on_stage_complete, "page_review", page_review)
    artifacts: dict[str, Any] = {
        "observed": observed,
        "book_skeleton": skeleton,
        "page_review": page_review,
        "public_graph": None,
        "internal_canonical": None,
    }
    if page_review["candidate_pages"] and not use_page_review_llm:
        return artifacts
    validate_resolved_page_review(page_review)
    observed_with_assets = materialize_v2_page_assets(
        observed,
        page_review,
        source_pdf=source_pdf,
        output_dir=output_dir,
    )
    artifacts["public_graph"] = build_bookgraph_from_observed(
        observed_with_assets,
        page_review=page_review,
    )
    artifacts["internal_canonical"] = build_internal_canonical_from_observed(
        observed_with_assets,
        page_review=page_review,
    )
    return artifacts


def _emit_stage(
    callback: Callable[[str, dict[str, Any]], None] | None,
    stage: str,
    artifact: dict[str, Any],
) -> None:
    if callback is not None:
        callback(stage, artifact)


def run_v2_cli(args: Any) -> None:
    """Run the v2 path directly from MinerU raw artifacts."""

    args.source_pdf = resolve_source_pdf_path(
        args.source_pdf, allow_missing=args.allow_missing_pdf_text
    )
    if not args.source_pdf:
        raise ValueError("--canonical-version v2 requires --source-pdf")
    output_path = Path(args.output)
    pages, page_sizes = load_inputs(args)
    artifacts = build_v2_artifacts(
        pages=pages,
        page_sizes=page_sizes,
        metadata=_observed_metadata(args, output_path),
        middle=load_json(args.middle),
        source_pdf=str(args.source_pdf),
        output_dir=output_path.parent,
        allow_missing_pdf_text=args.allow_missing_pdf_text,
        use_skeleton_llm=args.book_skeleton_llm,
        use_page_review_llm=args.page_review_llm,
        llm_model=args.book_skeleton_llm_model,
        llm_api_url=args.book_skeleton_llm_api_url,
        llm_timeout_seconds=args.book_skeleton_llm_timeout_seconds,
        on_stage_complete=lambda stage, artifact: _write_stage_artifact(args, stage, artifact),
    )
    _write_optional_artifacts(args, artifacts)
    public_graph = artifacts["public_graph"]
    if public_graph is None:
        print("Withheld public canonical_v2.json: page review candidates remain unresolved")
        return
    validate_bookgraph(public_graph)
    _write_json(output_path, public_graph)
    internal = artifacts["internal_canonical"]
    if args.internal_canonical_output and internal is not None:
        validate_internal_canonical(internal)
        _write_json(Path(args.internal_canonical_output), internal)
    print(f"Wrote {output_path} with {len(public_graph['nodes'])} BookGraph nodes")


def _write_optional_artifacts(args: Any, artifacts: dict[str, Any]) -> None:
    if args.observed_output:
        validate_observed_document(artifacts["observed"])
        _write_json(Path(args.observed_output), artifacts["observed"])
    if args.book_skeleton_output:
        validate_book_skeleton(artifacts["book_skeleton"])
        _write_json(Path(args.book_skeleton_output), artifacts["book_skeleton"])
    if args.page_review_output:
        _write_json(Path(args.page_review_output), artifacts["page_review"])


def _write_stage_artifact(args: Any, stage: str, artifact: dict[str, Any]) -> None:
    if stage == "observed" and args.observed_output:
        validate_observed_document(artifact)
        _write_json(Path(args.observed_output), artifact)
    elif stage == "book_skeleton" and args.book_skeleton_output:
        validate_book_skeleton(artifact)
        _write_json(Path(args.book_skeleton_output), artifact)
    elif stage == "page_review" and args.page_review_output:
        _write_json(Path(args.page_review_output), artifact)


def _observed_metadata(args: Any, output_path: Path) -> dict[str, Any]:
    source_file = str(args.source_pdf or args.content_list_v2 or args.content_list or "")
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
    return Path(os.path.relpath(Path(value).expanduser().resolve(), output_dir.resolve())).as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
