from __future__ import annotations

import inspect
import json
import os
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


DEFAULT_MINERU_BACKEND = "vlm-auto-engine"
DEFAULT_MINERU_METHOD = "auto"


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
) -> dict[str, Any]:
    """Run the migrated MinerU normalizer programmatically.

    Heavy optional dependencies are imported inside the function so the rest of
    the monorepo can run without a MinerU/PyMuPDF environment.
    """

    from mineru_normalizer.canonical.core import build_canonical
    from mineru_normalizer.canonical.assets import materialize_image_assets
    from mineru_normalizer.extraction.io import load_inputs

    args = SimpleNamespace(
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
        marker_locator_repair=False,
        marker_locator_artifact_dir=None,
        marker_locator_model="qwen3.5:9b",
        marker_locator_api_url="http://127.0.0.1:11434/api/chat",
        marker_locator_dpi=None,
        marker_locator_page_dpi=300,
        marker_locator_block_dpi=200,
        marker_locator_max_megapixels=0.0,
        marker_locator_body_mode="page_then_block",
        marker_locator_reuse_evidence=False,
        marker_locator_timing_log=None,
        note_trace_log=None,
    )
    pages, page_sizes = load_inputs(args)
    canonical = build_canonical(pages, page_sizes, args)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    materialize_image_assets(canonical, args.source_pdf, out.parent)

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
) -> dict[str, Any]:
    if engine != "mineru":
        raise ValueError(f"Unsupported PDF engine: {engine}")

    pdf_path = Path(input_pdf).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    raw_dir = output_path.parent / "mineru_raw"
    raw_output_dir = run_mineru_raw(pdf_path, raw_dir, backend=backend, method=method)
    raw_files = find_mineru_raw_files(raw_output_dir)
    return normalize_mineru_outputs(
        content_list_v2=raw_files["content_list_v2"],
        middle=raw_files["middle"],
        markdown=raw_files.get("markdown"),
        source_pdf=pdf_path,
        output=output_path,
        doc_id=pdf_path.stem,
        title=pdf_path.stem,
        language=language,
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
        from mineru.cli.common import do_parse, read_fn
        from mineru.utils.enum_class import MakeMode
    except ImportError as exc:
        raise RuntimeError("MinerU is required for PDF ingestion. Run this command in a MinerU environment.") from exc

    pdf = Path(pdf_path).expanduser().resolve()
    raw_root = Path(output_dir).expanduser().resolve()
    raw_root.mkdir(parents=True, exist_ok=True)
    _configure_mineru_env(raw_root, backend)
    state_path = raw_root / "run_state.json"
    started_at = _now_iso()
    started_monotonic = time.monotonic()
    _write_run_state(
        state_path,
        {
            "status": "running",
            "input_pdf": str(pdf),
            "output_dir": str(raw_root),
            "backend": backend,
            "method": method,
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
        _write_run_state(
            state_path,
            {
                "status": "failed",
                "input_pdf": str(pdf),
                "output_dir": str(raw_root),
                "backend": backend,
                "method": method,
                "started_at": started_at,
                "finished_at": _now_iso(),
                "duration_seconds": round(time.monotonic() - started_monotonic, 3),
                "pid": os.getpid(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    _write_run_state(
        state_path,
        {
            "status": "succeeded",
            "input_pdf": str(pdf),
            "output_dir": str(raw_root),
            "backend": backend,
            "method": method,
            "started_at": started_at,
            "finished_at": _now_iso(),
            "duration_seconds": round(time.monotonic() - started_monotonic, 3),
            "pid": os.getpid(),
        },
    )
    return raw_root


def find_mineru_raw_files(raw_output_dir: str | Path) -> dict[str, Path]:
    root = Path(raw_output_dir)
    content_list_v2 = _single_latest(root, "*_content_list_v2.json")
    middle = _single_latest(root, "*_middle.json")
    model = _single_latest(root, "*_model.json", required=False)
    markdown = _single_latest(root, "*.md", required=False)
    return {
        "content_list_v2": content_list_v2,
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


def _write_run_state(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _configure_mineru_env(work_dir: Path, backend: str) -> None:
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")
    os.environ.setdefault("MPLCONFIGDIR", str(work_dir / "cache" / "matplotlib"))
    os.environ.setdefault("YOLO_CONFIG_DIR", str(work_dir / "cache" / "ultralytics"))
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)

    config_path = _write_local_config(work_dir)
    if backend in {"vlm-auto-engine", "vlm-mlx-engine", "hybrid-auto-engine"}:
        os.environ["MINERU_MODEL_SOURCE"] = "local"
        os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(config_path.resolve())
        os.environ.pop("MINERU_DEVICE_MODE", None)


def _write_local_config(work_dir: Path) -> Path:
    config_path = work_dir / "mineru_local_config.json"
    models_dir: dict[str, str] = {}
    pipeline_model = _cached_pipeline_model_root(required=False)
    vlm_model = _cached_vlm_model_root(required=False)
    if pipeline_model is not None:
        models_dir["pipeline"] = str(pipeline_model)
    if vlm_model is not None:
        models_dir["vlm"] = str(vlm_model)
    config_path.write_text(json.dumps({"models-dir": models_dir}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    candidates = (
        Path.home() / ".cache/modelscope/hub/models/OpenDataLab/MinerU2___5-Pro-2604-1___2B",
        Path.home() / ".cache/modelscope/hub/models/OpenDataLab/MinerU2.5-Pro-2604-1.2B",
    )
    for path in candidates:
        if (path / "config.json").exists() and any(path.glob("*.safetensors")):
            return path
    hf_cache = Path.home() / ".cache/huggingface/hub/models--opendatalab--MinerU2.5-Pro-2604-1.2B/snapshots"
    if hf_cache.exists():
        snapshots = sorted((path for path in hf_cache.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)
        for snapshot in reversed(snapshots):
            if (snapshot / "config.json").exists() and any(snapshot.glob("*.safetensors")):
                return snapshot
    if required:
        raise FileNotFoundError("MinerU VLM model cache was not found.")
    return None
