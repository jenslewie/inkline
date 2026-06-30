"""Qwen marker evidence logging, cache, and timing I/O helpers."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from . import api as qwen_api
from . import types as qwen_types


def log_info(message: str, *args: Any) -> None:
    try:
        from loguru import logger  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    logger.info(message, *args)


def log_debug(message: str, *args: Any) -> None:
    try:
        from loguru import logger  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    logger.debug(message, *args)


def log_warning(message: str, *args: Any) -> None:
    try:
        from loguru import logger  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    logger.warning(message, *args)


def new_collect_stats() -> Dict[str, Any]:
    return {
        "pages": 0,
        "cache_hits": 0,
        "model_calls": 0,
        "footnote_defs": 0,
        "body_refs": 0,
        "page_seconds": 0.0,
    }


def update_collect_stats(
    stats: Dict[str, Any],
    cache_hit: bool,
    model_calls: List[Dict[str, Any]],
    footnote_def_count: int,
    body_ref_count: int,
    page_seconds: float,
) -> None:
    stats["pages"] += 1
    stats["cache_hits"] += int(cache_hit)
    stats["model_calls"] += len(model_calls)
    stats["footnote_defs"] += footnote_def_count
    stats["body_refs"] += body_ref_count
    stats["page_seconds"] += page_seconds


def collect_summary(stats: Dict[str, Any], pass_seconds: float) -> Dict[str, Any]:
    return {
        "pages": stats["pages"],
        "cache_hits": stats["cache_hits"],
        "cache_misses": stats["pages"] - stats["cache_hits"],
        "model_calls": stats["model_calls"],
        "footnote_defs": stats["footnote_defs"],
        "body_refs": stats["body_refs"],
        "total_page_seconds": round(float(stats["page_seconds"]), 6),
        "avg_page_seconds": avg_seconds(stats["page_seconds"], stats["pages"]),
        "pass_seconds": pass_seconds,
    }


def avg_seconds(total: float, count: int) -> float:
    return round(total / count, 6) if count else 0.0


def read_existing_evidence(path: Path) -> Dict[tuple[int, str], qwen_types.QwenMarkerPageEvidence]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = payload.get("pages") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return {}
    out: Dict[tuple[int, str], qwen_types.QwenMarkerPageEvidence] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        image = item.get("image")
        if not isinstance(page, int) or not isinstance(image, str):
            continue
        evidence = qwen_types.QwenMarkerPageEvidence(
            page=page,
            image=image,
            crop_bbox_pdf=[float(value) for value in item.get("crop_bbox_pdf") or []],
            dpi=int(item.get("dpi") or 0),
            raw_json=dict(item.get("raw_json") or {}),
            body_refs=qwen_api._clean_body_refs(item.get("body_refs")),
            footnote_defs=qwen_api._clean_footnote_defs(item.get("footnote_defs")),
            prompt_version=int(item.get("prompt_version") or 0),
        )
        if evidence.prompt_version != qwen_types._PROMPT_VERSION:
            continue
        key = (page, Path(image).name)
        existing = out.get(key)
        out[key] = (
            _merge_cached_qwen_evidence(existing, evidence) if existing is not None else evidence
        )
    return out


def _merge_cached_qwen_evidence(
    left: qwen_types.QwenMarkerPageEvidence, right: qwen_types.QwenMarkerPageEvidence
) -> qwen_types.QwenMarkerPageEvidence:
    raw_json = {**left.raw_json, **right.raw_json}
    return qwen_types.QwenMarkerPageEvidence(
        page=right.page,
        image=right.image or left.image,
        crop_bbox_pdf=right.crop_bbox_pdf or left.crop_bbox_pdf,
        dpi=right.dpi or left.dpi,
        raw_json=raw_json,
        body_refs=right.body_refs or left.body_refs,
        footnote_defs=right.footnote_defs or left.footnote_defs,
        prompt_version=right.prompt_version or left.prompt_version,
    )


def write_evidence(path: Path, evidence: Sequence[qwen_types.QwenMarkerPageEvidence]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"engine": "qwen_marker_locator", "pages": [item.to_json() for item in evidence]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def timing_log_path(config: qwen_types.QwenMarkerLocatorConfig) -> Path:
    return config.timing_log_path or (config.artifact_dir / "qwen_marker_timing.jsonl")


def reset_timing_log(config: qwen_types.QwenMarkerLocatorConfig) -> None:
    path = timing_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def write_timing_event(config: qwen_types.QwenMarkerLocatorConfig, event: Dict[str, Any]) -> None:
    path = timing_log_path(config)
    payload = {
        "schema": "qwen_marker_timing.v1",
        **event,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        f.write("\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def duration(start: float) -> float:
    return round(time.perf_counter() - start, 6)
