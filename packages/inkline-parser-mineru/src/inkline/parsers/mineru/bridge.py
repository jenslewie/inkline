from __future__ import annotations

import inspect
import json
import os
import time
from argparse import Namespace
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from inkline.canonical import validate_document
from inkline.parse.state import write_run_state
from inkline.parse.types import ParseRequest, ParseResult


DEFAULT_MINERU_BACKEND = "vlm-auto-engine"
DEFAULT_MINERU_METHOD = "auto"


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
        marker_locator_repair = bool(request.options.get("marker_locator_repair", True))
        marker_locator_page_dpi = int(request.options.get("marker_locator_page_dpi", 150))
        document = ingest_pdf_with_mineru(
            request.input_path,
            backend=backend,
            method=method,
            output=request.output_path,
            language=request.language,
            marker_locator_repair=marker_locator_repair,
            marker_locator_page_dpi=marker_locator_page_dpi,
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
    source_pdf: str | Path | None,
    output: str | Path,
    doc_id: str | None = None,
    title: str | None = None,
    language: str = "zh-CN",
    mineru_version: str | None = None,
    mineru_vl_utils_version: str | None = None,
    vlm_model: dict[str, Any] | None = None,
    marker_locator_repair: bool = True,
    marker_locator_page_dpi: int = 150,
) -> dict[str, Any]:
    """Run the MinerU normalization pipeline programmatically.

    Heavy optional dependencies are imported inside the function so the rest of
    the monorepo can run without a MinerU/PyMuPDF environment.
    """

    from inkline.parsers.mineru.normalize.core import build_canonical
    from inkline.parsers.mineru.normalize.assets import materialize_image_assets
    from inkline.parsers.mineru.extraction.io import load_inputs

    args = Namespace(
        content_list=None,
        content_list_v2=str(content_list_v2),
        middle=str(middle),
        model=None,
        md=str(markdown) if markdown else None,
        source_pdf=str(source_pdf) if source_pdf else None,
        allow_missing_pdf_text=False,
        output=str(output),
        doc_id=doc_id,
        title=title,
        language=language,
        marker_locator_repair=marker_locator_repair,
        marker_locator_artifact_dir=None,
        marker_locator_model="qwen3.6:35b-a3b",
        marker_locator_api_url="http://127.0.0.1:11434/api/chat",
        marker_locator_keep_alive="2h",
        marker_locator_dpi=None,
        marker_locator_page_dpi=marker_locator_page_dpi,
        marker_locator_block_dpi=200,
        marker_locator_max_megapixels=0.0,
        marker_locator_body_mode="page_then_block",
        marker_locator_reuse_evidence=False,
        marker_locator_timing_log=None,
        note_recovery_mode="qwen",
        note_trace_log=None,
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
    validate_document(canonical)

    import json

    out.write_text(json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8")
    return canonical


def ingest_pdf_with_mineru(
    input_pdf: str | Path,
    *,
    engine: str = "mineru",
    backend: str = DEFAULT_MINERU_BACKEND,
    method: str = DEFAULT_MINERU_METHOD,
    output: str | Path,
    language: str = "zh-CN",
    marker_locator_repair: bool = True,
    marker_locator_page_dpi: int = 150,
) -> dict[str, Any]:
    if engine != "mineru":
        raise ValueError(f"Unsupported PDF engine: {engine}")

    pdf_path = Path(input_pdf).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    raw_dir = output_path.parent / "mineru_raw"
    raw_output_dir = run_mineru_raw(pdf_path, raw_dir, backend=backend, method=method)
    raw_files = find_mineru_raw_files(raw_output_dir)
    version_info = find_mineru_run_version_info(raw_output_dir) or get_mineru_version_info()
    return normalize_mineru_outputs(
        content_list_v2=raw_files["content_list_v2"],
        middle=raw_files["middle"],
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
        raise RuntimeError("MinerU is required for PDF ingestion. Run this command in a MinerU environment.") from exc

    pdf = Path(pdf_path).expanduser().resolve()
    raw_root = Path(output_dir).expanduser().resolve()
    raw_root.mkdir(parents=True, exist_ok=True)
    _configure_mineru_runtime_env(raw_root)
    version_info = get_mineru_version_info()
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
        if _backend_uses_local_vlm_model(backend):
            version_info["vlm_model"] = _resolve_mineru_vlm_model_info()
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
    write_run_state(
        state_path,
        {
            "status": "succeeded",
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


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _configure_mineru_runtime_env(work_dir: Path) -> None:
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")
    os.environ.setdefault("MPLCONFIGDIR", str(work_dir / "cache" / "matplotlib"))
    os.environ.setdefault("YOLO_CONFIG_DIR", str(work_dir / "cache" / "ultralytics"))
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)


def get_mineru_version_info() -> dict[str, Any]:
    """Collect installed MinerU package versions without resolving a model."""
    from importlib.metadata import PackageNotFoundError, version as pkg_version

    info: dict[str, Any] = {}
    try:
        info["mineru_version"] = pkg_version("mineru")
    except PackageNotFoundError:
        info["mineru_version"] = None
    try:
        info["mineru_vl_utils_version"] = pkg_version("mineru-vl-utils")
    except PackageNotFoundError:
        info["mineru_vl_utils_version"] = None

    info["vlm_model"] = None
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
    from mineru.utils.models_download_utils import (  # pyright: ignore[reportMissingImports]
        auto_download_and_get_model_root_path,
    )

    model_root = Path(
        auto_download_and_get_model_root_path("/", repo_mode="vlm")
    ).expanduser().resolve()
    return _model_info_from_path(model_root)


def _backend_uses_local_vlm_model(backend: str) -> bool:
    return (
        backend.startswith(("vlm-", "hybrid-"))
        and not backend.endswith("http-client")
    )


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
