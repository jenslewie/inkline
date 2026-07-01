from __future__ import annotations

import inspect
import json
import os
import sys
import time
from argparse import Namespace
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from inkline.canonical import (
    build_bookgraph_from_observed,
    validate_bookgraph,
    validate_document,
    validate_observed_document,
)
from inkline.llm import DEFAULT_OLLAMA_CHAT_URL, DEFAULT_OLLAMA_KEEP_ALIVE, DEFAULT_QWEN_MODEL
from inkline.parse.state import write_run_state
from inkline.parse.types import ParseRequest, ParseResult

DEFAULT_MINERU_BACKEND = "vlm-auto-engine"
DEFAULT_MINERU_METHOD = "auto"
_MINERU_LOGGING_CONFIGURED = False


class MinerURawFiles(TypedDict):
    content_list_v2: Path
    content_list: Path | None
    middle: Path
    model: Path | None
    markdown: Path | None


@dataclass(frozen=True)
class MinerUParser:
    """Inkline parser adapter backed by MinerU."""

    backend: str = DEFAULT_MINERU_BACKEND
    method: str = DEFAULT_MINERU_METHOD
    name: str = "mineru"

    def parse(self, request: ParseRequest) -> ParseResult:
        backend = str(request.options.get("backend", self.backend))
        method = str(request.options.get("method", self.method))
        marker_locator_repair = bool(request.options.get("marker_locator_repair", False))
        marker_locator_page_dpi = int(request.options.get("marker_locator_page_dpi", 150))
        bookgraph_output = request.options.get("bookgraph_output")
        observed_output = request.options.get("observed_output")
        bookgraph_from_observed_output = request.options.get("bookgraph_from_observed_output")
        document = ingest_pdf_with_mineru(
            request.input_path,
            backend=backend,
            method=method,
            output=request.output_path,
            language=request.language,
            marker_locator_repair=marker_locator_repair,
            marker_locator_page_dpi=marker_locator_page_dpi,
            bookgraph_output=Path(bookgraph_output) if bookgraph_output else None,
            observed_output=Path(observed_output) if observed_output else None,
            bookgraph_from_observed_output=(
                Path(bookgraph_from_observed_output)
                if bookgraph_from_observed_output
                else None
            ),
        )
        return ParseResult(
            document=document,
            parser=self.name,
            raw_output_dir=request.output_path.parent / "mineru_raw",
        )


def normalize_mineru_outputs(
    *,
    content_list_v2: str | Path,
    middle: str | Path,
    markdown: str | Path | None,
    model: str | Path | None = None,
    source_pdf: str | Path | None,
    output: str | Path,
    doc_id: str | None = None,
    title: str | None = None,
    language: str = "zh-CN",
    mineru_version: str | None = None,
    mineru_vl_utils_version: str | None = None,
    vlm_model: dict[str, Any] | None = None,
    marker_locator_repair: bool = False,
    marker_locator_page_dpi: int = 150,
    bookgraph_output: str | Path | None = None,
    observed_output: str | Path | None = None,
    bookgraph_from_observed_output: str | Path | None = None,
) -> dict[str, Any]:
    """Run the MinerU normalization pipeline programmatically.

    Heavy optional dependencies are imported inside the function so the rest of
    the monorepo can run without a MinerU/PyMuPDF environment.
    """

    from inkline.parsers.mineru.analysis.note_gap_report import write_note_ref_gap_report
    from inkline.parsers.mineru.extraction.io import load_inputs
    from inkline.parsers.mineru.normalize.assets import materialize_image_assets
    from inkline.parsers.mineru.normalize.core import (
        _normalize_qwen_evidence_paths,
        _qwen_marker_locator_artifact_dir,
        build_canonical,
    )

    args = Namespace(
        content_list=None,
        content_list_v2=str(content_list_v2),
        middle=str(middle),
        model=str(model) if model else None,
        md=str(markdown) if markdown else None,
        source_pdf=str(source_pdf) if source_pdf else None,
        allow_missing_pdf_text=False,
        output=str(output),
        doc_id=doc_id,
        title=title,
        language=language,
        marker_locator_repair=marker_locator_repair,
        marker_locator_artifact_dir=None,
        marker_locator_model=DEFAULT_QWEN_MODEL,
        marker_locator_api_url=DEFAULT_OLLAMA_CHAT_URL,
        marker_locator_keep_alive=DEFAULT_OLLAMA_KEEP_ALIVE,
        marker_locator_dpi=None,
        marker_locator_page_dpi=marker_locator_page_dpi,
        marker_locator_block_dpi=200,
        marker_locator_max_megapixels=0.0,
        marker_locator_body_mode="page_then_block",
        marker_locator_reuse_evidence=False,
        marker_locator_timing_log=None,
        note_recovery_mode="qwen",
        note_trace_log=None,
        bookgraph_output=str(bookgraph_output) if bookgraph_output else None,
        observed_output=str(observed_output) if observed_output else None,
        bookgraph_from_observed_output=(
            str(bookgraph_from_observed_output) if bookgraph_from_observed_output else None
        ),
        parser_mode="vlm",
        mineru_version=mineru_version,
        mineru_vl_utils_version=mineru_vl_utils_version,
        vlm_model=vlm_model,
    )
    pages, page_sizes = load_inputs(args)
    canonical = build_canonical(pages, page_sizes, args)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    materialize_image_assets(canonical, args.source_pdf, out.parent)
    _normalize_qwen_evidence_paths(
        canonical,
        out.parent,
        artifact_dir=_qwen_marker_locator_artifact_dir(args),
    )
    validate_document(canonical)

    import json

    out.write_text(json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_bookgraph_shadow_if_requested(canonical, args.bookgraph_output)
    _write_observed_shadow_if_requested(
        pages,
        page_sizes,
        canonical,
        args.observed_output,
        args.bookgraph_from_observed_output,
    )
    write_note_ref_gap_report(canonical, out)
    return canonical


def ingest_pdf_with_mineru(
    input_pdf: str | Path,
    *,
    engine: str = "mineru",
    backend: str = DEFAULT_MINERU_BACKEND,
    method: str = DEFAULT_MINERU_METHOD,
    output: str | Path,
    language: str = "zh-CN",
    marker_locator_repair: bool = False,
    marker_locator_page_dpi: int = 150,
    bookgraph_output: str | Path | None = None,
    observed_output: str | Path | None = None,
    bookgraph_from_observed_output: str | Path | None = None,
) -> dict[str, Any]:
    if engine != "mineru":
        raise ValueError(f"Unsupported PDF engine: {engine}")

    pdf_path = Path(input_pdf).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    raw_dir = output_path.parent / "mineru_raw"
    raw_output_dir = run_mineru_raw(pdf_path, raw_dir, backend=backend, method=method)
    raw_files = find_mineru_raw_files(raw_output_dir)
    version_info = find_mineru_run_version_info(raw_output_dir) or get_mineru_version_info(backend)
    return normalize_mineru_outputs(
        content_list_v2=raw_files["content_list_v2"],
        middle=raw_files["middle"],
        model=raw_files.get("model"),
        markdown=raw_files.get("markdown"),
        source_pdf=pdf_path,
        output=output_path,
        doc_id=pdf_path.stem,
        title=pdf_path.stem,
        language=language,
        mineru_version=version_info.get("mineru_version"),
        mineru_vl_utils_version=version_info.get("mineru_vl_utils_version"),
        vlm_model=version_info.get("vlm_model"),
        marker_locator_repair=marker_locator_repair,
        marker_locator_page_dpi=marker_locator_page_dpi,
        bookgraph_output=bookgraph_output,
        observed_output=observed_output,
        bookgraph_from_observed_output=bookgraph_from_observed_output,
    )


def run_mineru_raw(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    backend: str = DEFAULT_MINERU_BACKEND,
    method: str = DEFAULT_MINERU_METHOD,
) -> Path:
    """Run MinerU on one PDF and return the raw output root.

    Heavy MinerU imports stay inside this function so the lightweight packages
    can be imported without a MinerU environment.
    """

    try:
        from mineru.cli.common import do_parse, read_fn  # pyright: ignore[reportMissingImports]
        from mineru.utils.enum_class import MakeMode  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise RuntimeError(
            "MinerU is required for PDF ingestion. Run this command in a MinerU environment."
        ) from exc

    pdf = Path(pdf_path).expanduser().resolve()
    raw_root = Path(output_dir).expanduser().resolve()
    raw_root.mkdir(parents=True, exist_ok=True)
    _configure_mineru_env(raw_root, backend)
    version_info = get_mineru_version_info(backend)
    state_path = raw_root / "run_state.json"
    started_at = _now_iso()
    started_monotonic = time.monotonic()
    write_run_state(
        state_path,
        {
            "status": "running",
            "input_pdf": str(pdf),
            "output_dir": str(raw_root),
            "backend": backend,
            "method": method,
            "mineru_version": version_info.get("mineru_version"),
            "mineru_vl_utils_version": version_info.get("mineru_vl_utils_version"),
            "vlm_model": version_info.get("vlm_model"),
            "started_at": started_at,
            "finished_at": None,
            "duration_seconds": None,
            "pid": os.getpid(),
        },
    )

    kwargs: dict[str, Any] = {
        "output_dir": str(raw_root),
        "pdf_file_names": [pdf.stem],
        "pdf_bytes_list": [read_fn(pdf)],
        "p_lang_list": ["ch"],
        "backend": backend,
        "parse_method": method,
        "f_draw_layout_bbox": False,
        "f_draw_span_bbox": False,
        "f_dump_md": True,
        "f_dump_middle_json": True,
        "f_dump_model_output": True,
        "f_dump_orig_pdf": False,
        "f_dump_content_list": True,
        "f_make_md_mode": MakeMode.MM_MD,
    }
    signature_params = inspect.signature(do_parse).parameters
    if "formula_enable" in signature_params:
        kwargs["formula_enable"] = False
        kwargs["table_enable"] = True
    else:
        kwargs["p_formula_enable"] = False
        kwargs["p_table_enable"] = True

    try:
        do_parse(**kwargs)
    except Exception as exc:
        write_run_state(
            state_path,
            {
                "status": "failed",
                "input_pdf": str(pdf),
                "output_dir": str(raw_root),
                "backend": backend,
                "method": method,
                "mineru_version": version_info.get("mineru_version"),
                "mineru_vl_utils_version": version_info.get("mineru_vl_utils_version"),
                "vlm_model": version_info.get("vlm_model"),
                "started_at": started_at,
                "finished_at": _now_iso(),
                "duration_seconds": round(time.monotonic() - started_monotonic, 3),
                "pid": os.getpid(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    final_version_info = get_mineru_version_info(backend)
    write_run_state(
        state_path,
        {
            "status": "succeeded",
            "input_pdf": str(pdf),
            "output_dir": str(raw_root),
            "backend": backend,
            "method": method,
            "mineru_version": final_version_info.get("mineru_version"),
            "mineru_vl_utils_version": final_version_info.get("mineru_vl_utils_version"),
            "vlm_model": final_version_info.get("vlm_model"),
            "started_at": started_at,
            "finished_at": _now_iso(),
            "duration_seconds": round(time.monotonic() - started_monotonic, 3),
            "pid": os.getpid(),
        },
    )
    return raw_root


def find_mineru_raw_files(raw_output_dir: str | Path) -> MinerURawFiles:
    root = Path(raw_output_dir)
    content_list_v2 = _single_latest(root, "*_content_list_v2.json")
    content_list = _single_latest(root, "*_content_list.json", required=False)
    middle = _single_latest(root, "*_middle.json")
    model = _single_latest(root, "*_model.json", required=False)
    markdown = _single_latest(root, "*.md", required=False)
    assert content_list_v2 is not None
    assert middle is not None
    return {
        "content_list_v2": content_list_v2,
        "content_list": content_list,
        "middle": middle,
        "model": model,
        "markdown": markdown,
    }


def _single_latest(root: Path, pattern: str, *, required: bool = True) -> Path | None:
    matches = sorted(root.rglob(pattern), key=lambda path: path.stat().st_mtime)
    if not matches:
        if required:
            raise FileNotFoundError(f"MinerU did not produce {pattern} under {root}")
        return None
    return matches[-1]


def _write_bookgraph_shadow_if_requested(
    canonical: dict[str, Any], bookgraph_output: str | Path | None
) -> None:
    if not bookgraph_output:
        return
    from inkline.parsers.mineru.normalize.bookgraph_shadow import build_bookgraph_shadow

    graph = build_bookgraph_shadow(canonical)
    validate_bookgraph(graph)
    out = Path(bookgraph_output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_observed_shadow_if_requested(
    pages: dict[int, list[Any]],
    page_sizes: dict[int, tuple[float, float]],
    canonical: dict[str, Any],
    observed_output: str | Path | None,
    bookgraph_from_observed_output: str | Path | None,
) -> None:
    if not observed_output and not bookgraph_from_observed_output:
        return
    from inkline.parsers.mineru.normalize.observed_shadow import (
        build_observed_document_shadow,
    )

    observed = build_observed_document_shadow(
        pages=pages,
        page_sizes=page_sizes,
        metadata=canonical["metadata"],
        assets=canonical.get("assets") or {},
    )
    validate_observed_document(observed)
    if observed_output:
        out = Path(observed_output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding="utf-8")
    if bookgraph_from_observed_output:
        graph = build_bookgraph_from_observed(observed)
        validate_bookgraph(graph)
        out = Path(bookgraph_from_observed_output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _configure_mineru_env(work_dir: Path, backend: str) -> None:
    _configure_mineru_logging()
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")
    os.environ.setdefault("MPLCONFIGDIR", str(work_dir / "cache" / "matplotlib"))
    os.environ.setdefault("YOLO_CONFIG_DIR", str(work_dir / "cache" / "ultralytics"))
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)

    if backend == "pipeline":
        config_path = _write_local_config(work_dir)
        os.environ["MINERU_MODEL_SOURCE"] = "local"
        os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(config_path.resolve())
    elif backend in {"vlm-auto-engine", "vlm-mlx-engine", "hybrid-auto-engine"}:
        _clear_inkline_local_model_config()

    os.environ.pop("MINERU_DEVICE_MODE", None)


def _configure_mineru_logging() -> None:
    global _MINERU_LOGGING_CONFIGURED
    if _MINERU_LOGGING_CONFIGURED:
        return
    if os.environ.get("INKLINE_PRESERVE_LOGURU", "").lower() in {"1", "true", "yes"}:
        _MINERU_LOGGING_CONFIGURED = True
        return
    try:
        from loguru import logger  # pyright: ignore[reportMissingImports]
    except ImportError:
        _MINERU_LOGGING_CONFIGURED = True
        return
    level = os.environ.get("INKLINE_MINERU_LOG_LEVEL", "INFO").upper()
    logger.remove()
    logger.add(sys.stderr, level=level)
    _MINERU_LOGGING_CONFIGURED = True


def _clear_inkline_local_model_config() -> None:
    if os.environ.get("MINERU_MODEL_SOURCE") == "local":
        os.environ.pop("MINERU_MODEL_SOURCE", None)
    config_path = os.environ.get("MINERU_TOOLS_CONFIG_JSON")
    if config_path and Path(config_path).name == "mineru_local_config.json":
        os.environ.pop("MINERU_TOOLS_CONFIG_JSON", None)


def _write_local_config(work_dir: Path) -> Path:
    config_path = work_dir / "mineru_local_config.json"
    models_dir: dict[str, str] = {}
    pipeline_model = _cached_pipeline_model_root(required=False)
    if pipeline_model is not None:
        models_dir["pipeline"] = str(pipeline_model)
    config_path.write_text(
        json.dumps({"models-dir": models_dir}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path


def _cached_pipeline_model_root(*, required: bool) -> Path | None:
    candidates = (
        Path.home() / ".cache/modelscope/hub/models/OpenDataLab/PDF-Extract-Kit-1___0",
        Path.home() / ".cache/modelscope/hub/models/OpenDataLab/PDF-Extract-Kit-1.0",
    )
    for path in candidates:
        if (path / "models" / "Layout" / "PP-DocLayoutV2" / "config.json").exists():
            return path
    if required:
        raise FileNotFoundError("MinerU pipeline model cache was not found.")
    return None


def _cached_vlm_model_root(*, required: bool) -> Path | None:
    for path in _candidate_vlm_model_roots():
        if (path / "config.json").exists() and any(path.glob("*.safetensors")):
            return path
        snapshot_roots = [path] if path.name == "snapshots" else [path / "snapshots"]
        for snapshot_root in snapshot_roots:
            if not snapshot_root.exists():
                continue
            snapshots = sorted(
                (path for path in snapshot_root.iterdir() if path.is_dir()),
                key=lambda path: path.stat().st_mtime,
            )
            for snapshot in reversed(snapshots):
                if (snapshot / "config.json").exists() and any(snapshot.glob("*.safetensors")):
                    return snapshot
    if required:
        raise FileNotFoundError("MinerU VLM model cache was not found.")
    return None


def _candidate_vlm_model_roots() -> list[Path]:
    repos = _mineru_vlm_repositories()
    roots: list[Path] = []
    for repo in repos:
        roots.extend(_huggingface_cache_roots(repo))
        roots.extend(_modelscope_cache_roots(repo))
    return roots


def _mineru_vlm_repositories() -> list[str]:
    try:
        from mineru.utils.enum_class import ModelPath  # pyright: ignore[reportMissingImports]
    except ImportError:
        return []
    repos = [ModelPath.vlm_root_hf, ModelPath.vlm_root_modelscope]
    return [repo for repo in repos if repo]


def _huggingface_cache_roots(repo: str) -> list[Path]:
    if "/" not in repo:
        return []
    owner, name = repo.split("/", 1)
    return [Path.home() / ".cache/huggingface/hub" / f"models--{owner}--{name}" / "snapshots"]


def _modelscope_cache_roots(repo: str) -> list[Path]:
    if "/" not in repo:
        return []
    owner, name = repo.split("/", 1)
    escaped_name = name.replace(".", "___")
    return [
        Path.home() / ".cache/modelscope/hub/models" / owner / escaped_name,
        Path.home() / ".cache/modelscope/hub/models" / owner / name,
    ]


def get_mineru_version_info(backend: str = DEFAULT_MINERU_BACKEND) -> dict[str, Any]:
    """Collect MinerU package version and VLM model metadata.

    Returns a dict with keys:
      - mineru_version: str | None  — pip-installed MinerU package version
      - mineru_vl_utils_version: str | None  — mineru-vl-utils package version
      - vlm_model: dict | None  — VLM model identity when backend is VLM-based
    """
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as pkg_version

    info: dict[str, Any] = {}
    try:
        info["mineru_version"] = pkg_version("mineru")
    except PackageNotFoundError:
        info["mineru_version"] = None
    try:
        info["mineru_vl_utils_version"] = pkg_version("mineru-vl-utils")
    except PackageNotFoundError:
        info["mineru_vl_utils_version"] = None

    is_vlm_backend = backend.startswith("vlm") or backend == "hybrid-auto-engine"
    if not is_vlm_backend:
        info["vlm_model"] = None
        return info

    info["vlm_model"] = _resolve_mineru_vlm_model_info()
    return info


def find_mineru_run_version_info(*paths: str | Path | None) -> dict[str, Any] | None:
    """Read parser provenance persisted beside MinerU raw outputs."""

    checked: set[Path] = set()
    for value in paths:
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        directories = [path] if path.is_dir() else [path.parent]
        directories.extend(path.parents)
        for directory in directories:
            state_path = directory / "run_state.json"
            if state_path in checked:
                continue
            checked.add(state_path)
            if not state_path.is_file():
                continue
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            return {
                "mineru_version": state.get("mineru_version"),
                "mineru_vl_utils_version": state.get("mineru_vl_utils_version"),
                "vlm_model": state.get("vlm_model"),
            }
    return None


def _resolve_mineru_vlm_model_info() -> dict[str, Any] | None:
    model_root = _cached_vlm_model_root(required=False)
    return _model_info_from_path(model_root) if model_root is not None else None


def _model_info_from_path(model_root: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "local_path": str(model_root),
        "model_name": _model_name_from_path(model_root),
    }
    config_path = model_root / "config.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            info["model_type"] = config.get("model_type")
            info["architectures"] = config.get("architectures")
        except (json.JSONDecodeError, OSError):
            pass
    return info


def _model_name_from_path(model_root: Path) -> str:
    for part in model_root.parts:
        if part.startswith("models--"):
            return part.removeprefix("models--").split("--")[-1]
    return model_root.name
