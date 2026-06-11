"""Qwen marker evidence collection, caching, I/O, and timing.

Contains the main evidence collection loop, paragraph body-ref collection,
single-marker retry, evidence read/write, and timing helpers.  Uses module-
level imports from other ``qwen_*`` modules so that monkeypatching works
correctly (patch the definition module namespace).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, cast

from ...analysis.page_geometry import PageGeometry
from ...extraction.text import normalize_ws
from ..block_access import block_id
from ...schema.models import CanonicalBlock
from . import qwen_api
from . import qwen_page_plan
from . import qwen_prompt
from . import qwen_types


def _collect_qwen_marker_evidence(
    blocks: Sequence[CanonicalBlock],
    pages: Sequence[int],
    config: qwen_types.QwenMarkerLocatorConfig,
    *,
    pass_name: str,
    footnote_pages: set[int] | None = None,
    body_ref_pages: set[int] | None = None,
    expected_body_markers_by_page: Dict[int, List[str]] | None = None,
) -> List[qwen_types.QwenMarkerPageEvidence]:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("Qwen marker locator page rendering requires PyMuPDF (`fitz`).") from exc

    cache = _read_existing_evidence(config.artifact_dir / "qwen_marker_evidence.json") if config.reuse_evidence else {}
    evidence: List[qwen_types.QwenMarkerPageEvidence] = []
    use_block_body_refs = config.body_mode == "block"
    geometry = PageGeometry.from_canonical_blocks(cast(Sequence[Dict[str, Any]], blocks)) if use_block_body_refs else None
    body_blocks_by_page = qwen_prompt._body_blocks_by_page(blocks) if use_block_body_refs else {}
    body_ref_source = "paragraph_crops" if use_block_body_refs else "full_page"
    footnote_pages = set() if footnote_pages is None else footnote_pages
    body_ref_pages = set(pages) if body_ref_pages is None else body_ref_pages
    expected_body_markers_by_page = expected_body_markers_by_page or {}
    page_list = list(pages)
    pass_started = _now_iso()
    pass_timer = time.perf_counter()
    pass_stats = _new_collect_stats()
    _log_debug(
        "Qwen marker locator pass `{}`: pages={} body_mode={} dpi={} footnote_pages={} body_ref_pages={}",
        pass_name,
        len(page_list),
        config.body_mode,
        config.dpi,
        len(footnote_pages),
        len(body_ref_pages),
    )
    _write_timing_event(
        config,
        {
            "event": "collect_pass_start",
            "pass": pass_name,
            "started_at": pass_started,
            "pages": page_list,
            "footnote_pages": sorted(footnote_pages),
            "body_ref_pages": sorted(body_ref_pages),
        },
    )
    with fitz.open(config.source_pdf) as doc:
        for page_index, page in enumerate(page_list, start=1):
            if page < 1 or page > doc.page_count:
                _log_warning(
                    "Qwen marker locator pass `{}` page {}/{} skipped: page {} outside PDF page_count={}",
                    pass_name,
                    page_index,
                    len(page_list),
                    page,
                    doc.page_count,
                )
                _write_timing_event(
                    config,
                    {
                        "event": "page_skipped",
                        "pass": pass_name,
                        "page": page,
                        "reason": "outside_pdf_page_range",
                        "page_count": doc.page_count,
                        "finished_at": _now_iso(),
                    },
                )
                continue
            page_started = _now_iso()
            page_timer = time.perf_counter()
            render_timer = time.perf_counter()
            pdf_page = doc[page - 1]
            image_path = config.artifact_dir / f"page_{page:04d}_{config.dpi}dpi_qwen_full_page.png"
            _log_debug(
                "Qwen marker locator pass `{}` page {}/{} (pdf page {}): footnote_defs={} body_refs={} mode={}",
                pass_name,
                page_index,
                len(page_list),
                page,
                page in footnote_pages,
                page in body_ref_pages,
                config.body_mode,
            )
            try:
                qwen_prompt._render_full_page(pdf_page, image_path, config)
            except Exception as exc:
                _write_timing_event(
                    config,
                    {
                        "event": "page_error",
                        "pass": pass_name,
                        "page": page,
                        "stage": "render",
                        "started_at": page_started,
                        "finished_at": _now_iso(),
                        "duration_seconds": _duration(page_timer),
                        "render_seconds": _duration(render_timer),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                raise
            render_duration = _duration(render_timer)

            # Check cache and determine what needs fresh API calls
            cached_item = cache.get((page, image_path.name))
            cache_hit = cached_item is not None
            raw_parts: Dict[str, Any] = dict(cached_item.raw_json) if cached_item is not None else {}
            footnote_cached = cached_item is not None and "footnote_defs" in raw_parts
            body_cached = cached_item is not None and raw_parts.get("body_ref_source") == body_ref_source
            model_calls: List[Dict[str, Any]] = []

            if cached_item is None or (page in footnote_pages and not footnote_cached) or (page in body_ref_pages and not body_cached):
                # Footnote defs pass
                if page in footnote_pages and not footnote_cached:
                    raw_parts, model_calls = _collect_footnote_defs_for_page(
                        image_path, config, raw_parts, pass_name, page,
                        page_started, page_timer, render_duration, cache_hit, model_calls,
                    )

                # Body refs pass
                if page in body_ref_pages and not body_cached:
                    raw_parts, model_calls = _collect_body_refs_for_page(
                        image_path, pdf_page, page, config, raw_parts,
                        use_block_body_refs, body_blocks_by_page, geometry,
                        expected_body_markers_by_page, body_ref_source,
                        pass_name, page_started, page_timer, render_duration, cache_hit, model_calls,
                    )

                # Build evidence item from collected raw data
                item = qwen_types.QwenMarkerPageEvidence(
                    page=page,
                    image=str(image_path),
                    crop_bbox_pdf=[float(pdf_page.rect.x0), float(pdf_page.rect.y0), float(pdf_page.rect.x1), float(pdf_page.rect.y1)],
                    dpi=config.dpi,
                    raw_json=raw_parts,
                    body_refs=qwen_api._clean_body_refs(raw_parts.get("body_refs")),
                    footnote_defs=qwen_api._clean_footnote_defs(raw_parts.get("footnote_defs")),
                )
            else:
                # Complete cache hit — reuse cached item directly
                item = cached_item
            evidence.append(item)
            page_duration = _duration(page_timer)
            _update_collect_stats(pass_stats, cache_hit, model_calls, len(item.footnote_defs), len(item.body_refs), page_duration)
            _log_info(
                "Qwen marker locator pass `{}` page {}/{} done: page={} started_at={} finished_at={} seconds={} render_seconds={} cache_hit={} model_calls={} footnote_defs={} body_refs={}",
                pass_name,
                page_index,
                len(page_list),
                page,
                page_started,
                _now_iso(),
                page_duration,
                render_duration,
                cache_hit,
                len(model_calls),
                len(item.footnote_defs),
                len(item.body_refs),
            )
            _write_timing_event(
                config,
                {
                    "event": "page_end",
                    "pass": pass_name,
                    "page": page,
                    "started_at": page_started,
                    "finished_at": _now_iso(),
                    "duration_seconds": page_duration,
                    "render_seconds": render_duration,
                    "cache_hit": cache_hit,
                    "image": str(image_path),
                    "image_bytes": image_path.stat().st_size if image_path.exists() else None,
                    "requested_footnote_defs": page in footnote_pages,
                    "requested_body_refs": page in body_ref_pages,
                    "model_calls": model_calls,
                    "footnote_def_count": len(item.footnote_defs),
                    "body_ref_count": len(item.body_refs),
                },
            )
    pass_duration = _duration(pass_timer)
    _write_timing_event(
        config,
        {
            "event": "collect_pass_end",
            "pass": pass_name,
            "started_at": pass_started,
            "finished_at": _now_iso(),
            "duration_seconds": pass_duration,
            "evidence_items": len(evidence),
            "summary": _collect_summary(pass_stats, pass_duration),
        },
    )
    _log_info(
        "Qwen marker locator pass `{}` finished: started_at={} finished_at={} pages={} evidence_items={} cache_hits={} model_calls={} footnote_defs={} body_refs={} seconds={} avg_page_seconds={}",
        pass_name,
        pass_started,
        _now_iso(),
        len(page_list),
        len(evidence),
        pass_stats["cache_hits"],
        pass_stats["model_calls"],
        pass_stats["footnote_defs"],
        pass_stats["body_refs"],
        pass_duration,
        _avg_seconds(pass_stats["page_seconds"], pass_stats["pages"]),
    )
    return evidence


def _collect_footnote_defs_for_page(
    image_path: Path,
    config: qwen_types.QwenMarkerLocatorConfig,
    raw_parts: Dict[str, Any],
    pass_name: str,
    page: int,
    page_started: str,
    page_timer: float,
    render_duration: float,
    cache_hit: bool,
    model_calls: List[Dict[str, Any]],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Call Qwen for footnote definitions on a single page; update raw_parts and model_calls."""
    call_timer = time.perf_counter()
    call_started = _now_iso()
    _log_debug("Qwen marker locator page {}: calling model for footnote definitions", page)
    try:
        footnote_raw = qwen_api._call_qwen_marker_locator(image_path, config, prompt=config.footnote_prompt)
    except Exception as exc:
        model_calls.append(
            {
                "kind": "footnote_defs",
                "started_at": call_started,
                "finished_at": _now_iso(),
                "duration_seconds": _duration(call_timer),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        _write_timing_event(
            config,
            {
                "event": "page_error",
                "pass": pass_name,
                "page": page,
                "stage": "footnote_defs",
                "started_at": page_started,
                "finished_at": _now_iso(),
                "duration_seconds": _duration(page_timer),
                "render_seconds": render_duration,
                "cache_hit": cache_hit,
                "image": str(image_path),
                "model_calls": model_calls,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    model_calls.append(
        {
            "kind": "footnote_defs",
            "started_at": call_started,
            "finished_at": _now_iso(),
            "duration_seconds": _duration(call_timer),
            "raw_item_count": len(footnote_raw.get("footnote_defs") or []) if isinstance(footnote_raw, dict) else 0,
        }
    )
    _log_debug(
        "Qwen marker locator page {}: footnote definitions returned {} item(s) in {}s",
        page,
        len(footnote_raw.get("footnote_defs") or []) if isinstance(footnote_raw, dict) else 0,
        _duration(call_timer),
    )
    raw_parts["footnote_defs"] = footnote_raw.get("footnote_defs") if isinstance(footnote_raw, dict) else []
    return raw_parts, model_calls


def _collect_body_refs_for_page(
    image_path: Path,
    pdf_page: Any,
    page: int,
    config: qwen_types.QwenMarkerLocatorConfig,
    raw_parts: Dict[str, Any],
    use_block_body_refs: bool,
    body_blocks_by_page: Dict[int, List[CanonicalBlock]],
    geometry: PageGeometry | None,
    expected_body_markers_by_page: Dict[int, List[str]],
    body_ref_source: str,
    pass_name: str,
    page_started: str,
    page_timer: float,
    render_duration: float,
    cache_hit: bool,
    model_calls: List[Dict[str, Any]],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Call Qwen for body refs on a single page (full-page or paragraph crops); update raw_parts and model_calls."""
    marker_items = qwen_api._clean_footnote_defs(raw_parts.get("footnote_defs"))
    markers = qwen_prompt._body_markers_for_prompt(marker_items, expected_body_markers_by_page.get(page, []))
    call_timer = time.perf_counter()
    call_started = _now_iso()
    call_finished: str | None = None
    call_duration: float | None = None
    retry_calls: List[Dict[str, Any]] = []
    body_refs: List[Dict[str, Any]] = []
    try:
        if use_block_body_refs:
            if geometry is None:
                raise RuntimeError("Qwen paragraph body-ref collection requires page geometry.")
            _log_debug(
                "Qwen marker locator page {}: scanning paragraph crops for body refs markers={}",
                page,
                markers,
            )
            body_raw = _collect_paragraph_body_refs(
                pdf_page,
                page,
                body_blocks_by_page.get(page, []),
                geometry,
                config,
                markers,
            )
        else:
            _log_debug(
                "Qwen marker locator page {}: calling model for full-page body refs markers={}",
                page,
                markers,
            )
            body_raw = qwen_api._call_qwen_marker_locator(image_path, config, prompt=qwen_prompt._body_prompt_for_markers(config.body_prompt, markers))
            call_finished = _now_iso()
            call_duration = _duration(call_timer)
            raw_body_refs = body_raw.get("body_refs") if isinstance(body_raw, dict) else []
            body_refs = raw_body_refs if isinstance(raw_body_refs, list) else []
            body_refs, retry_calls = _retry_missing_single_marker_body_refs(
                image_path,
                config,
                markers,
                body_refs,
            )
    except Exception as exc:
        model_calls.append(
            {
                "kind": "paragraph_body_refs" if use_block_body_refs else "body_refs",
                "started_at": call_started,
                "finished_at": _now_iso(),
                "duration_seconds": _duration(call_timer),
                "markers_for_prompt": markers,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        _write_timing_event(
            config,
            {
                "event": "page_error",
                "pass": pass_name,
                "page": page,
                "stage": "body_refs",
                "started_at": page_started,
                "finished_at": _now_iso(),
                "duration_seconds": _duration(page_timer),
                "render_seconds": render_duration,
                "cache_hit": cache_hit,
                "image": str(image_path),
                "model_calls": model_calls,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    model_calls.append(
        {
            "kind": "paragraph_body_refs" if use_block_body_refs else "body_refs",
            "started_at": call_started,
            "finished_at": call_finished or _now_iso(),
            "duration_seconds": call_duration if call_duration is not None else _duration(call_timer),
            "markers_for_prompt": markers,
            "raw_item_count": len(body_raw) if use_block_body_refs else (len(body_raw.get("body_refs") or []) if isinstance(body_raw, dict) else 0),
        }
    )
    _log_debug(
        "Qwen marker locator page {}: body refs returned {} item(s) in {}s",
        page,
        len(body_raw) if use_block_body_refs else (len(body_raw.get("body_refs") or []) if isinstance(body_raw, dict) else 0),
        call_duration if call_duration is not None else _duration(call_timer),
    )
    model_calls.extend(retry_calls)
    raw_parts["body_refs"] = body_raw if use_block_body_refs else body_refs
    raw_parts["body_ref_source"] = body_ref_source
    return raw_parts, model_calls


def _retry_missing_single_marker_body_refs(
    image_path: Path,
    config: qwen_types.QwenMarkerLocatorConfig,
    markers: Sequence[str],
    body_refs: Any,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    refs = list(body_refs) if isinstance(body_refs, list) else []
    found_markers = {item.get("marker") for item in qwen_api._clean_body_refs(refs)}
    missing_markers = [
        marker
        for marker in dict.fromkeys(str(marker) for marker in markers if marker)
        if marker not in found_markers
    ]
    model_calls: List[Dict[str, Any]] = []
    for marker in missing_markers:
        call_timer = time.perf_counter()
        call_started = _now_iso()
        _log_debug("Qwen marker locator retry: calling model for single marker {}", marker)
        single_raw = qwen_api._call_qwen_marker_locator(image_path, config, prompt=qwen_prompt._single_marker_body_prompt(marker))
        single_refs = single_raw.get("body_refs") if isinstance(single_raw, dict) else []
        refs = qwen_prompt._merge_body_ref_raw_items(refs, single_refs)
        model_calls.append(
            {
                "kind": "body_refs_single_marker_retry",
                "marker": marker,
                "started_at": call_started,
                "finished_at": _now_iso(),
                "duration_seconds": _duration(call_timer),
                "raw_item_count": len(single_refs) if isinstance(single_refs, list) else 0,
            }
        )
        _log_debug(
            "Qwen marker locator retry: marker {} returned {} item(s) in {}s",
            marker,
            len(single_refs) if isinstance(single_refs, list) else 0,
            _duration(call_timer),
        )
    return refs, model_calls


def _collect_paragraph_body_refs(
    pdf_page: Any,
    page: int,
    blocks: Sequence[CanonicalBlock],
    geometry: PageGeometry,
    config: qwen_types.QwenMarkerLocatorConfig,
    markers: Sequence[str],
) -> List[Dict[str, Any]]:
    markers = list(dict.fromkeys([marker for marker in markers if marker]))
    if not markers:
        return []
    out: List[Dict[str, Any]] = []
    for block in blocks:
        bbox = qwen_prompt._block_bbox_for_page(block, page)
        if bbox is None:
            continue
        refs = _collect_single_paragraph_body_refs(pdf_page, page, block, bbox, geometry, config, markers)
        out.extend(refs)
    return out


def _collect_single_paragraph_body_refs(
    pdf_page: Any,
    page: int,
    block: CanonicalBlock,
    bbox: List[float],
    geometry: PageGeometry,
    config: qwen_types.QwenMarkerLocatorConfig,
    markers: List[str],
) -> List[Dict[str, Any]]:
    """Render one paragraph crop, call Qwen, and return annotated body refs."""
    block_label = qwen_prompt._safe_filename_part(block_id(block) or "block")
    image_path = config.artifact_dir / f"page_{page:04d}_{block_label}_{config.dpi}dpi_qwen_body_block.png"
    block_started = _now_iso()
    block_timer = time.perf_counter()
    render_timer = time.perf_counter()
    try:
        crop_bbox_pdf = qwen_prompt._render_block_crop(pdf_page, image_path, page, bbox, geometry, config)
    except Exception as exc:
        _write_timing_event(
            config,
            {
                "event": "paragraph_body_block_error",
                "page": page,
                "block_id": block_id(block),
                "stage": "render",
                "started_at": block_started,
                "finished_at": _now_iso(),
                "duration_seconds": _duration(block_timer),
                "render_seconds": _duration(render_timer),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    render_seconds = _duration(render_timer)
    model_timer = time.perf_counter()
    model_started = _now_iso()
    _log_debug(
        "Qwen marker locator page {} block {}: calling model for paragraph crop markers={}",
        page,
        block_id(block),
        markers,
    )
    try:
        raw = qwen_api._call_qwen_marker_locator(image_path, config, prompt=qwen_prompt._paragraph_body_prompt_for_markers(markers, block))
    except Exception as exc:
        _write_timing_event(
            config,
            {
                "event": "paragraph_body_block_error",
                "page": page,
                "block_id": block_id(block),
                "stage": "model",
                "started_at": block_started,
                "model_started_at": model_started,
                "finished_at": _now_iso(),
                "duration_seconds": _duration(block_timer),
                "render_seconds": render_seconds,
                "model_seconds": _duration(model_timer),
                "image": str(image_path),
                "crop_bbox_pdf": crop_bbox_pdf,
                "markers_for_prompt": markers,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    cleaned_refs = qwen_api._clean_body_refs(raw.get("body_refs") if isinstance(raw, dict) else [])
    for ref in cleaned_refs:
        ref["block_id"] = block_id(block)
        ref["body_ref_source"] = "paragraph_crop"
        ref["crop_image"] = str(image_path)
        ref["crop_bbox_pdf"] = crop_bbox_pdf
    _write_timing_event(
        config,
        {
            "event": "paragraph_body_block_end",
            "page": page,
            "block_id": block_id(block),
            "started_at": block_started,
            "model_started_at": model_started,
            "finished_at": _now_iso(),
            "duration_seconds": _duration(block_timer),
            "render_seconds": render_seconds,
            "model_seconds": _duration(model_timer),
            "image": str(image_path),
            "image_bytes": image_path.stat().st_size if image_path.exists() else None,
            "crop_bbox_pdf": crop_bbox_pdf,
            "markers_for_prompt": markers,
            "raw_item_count": len(raw.get("body_refs") or []) if isinstance(raw, dict) else 0,
            "body_ref_count": len(cleaned_refs),
        },
    )
    block_duration = _duration(block_timer)
    _log_info(
        "Qwen marker locator page {} block {} done: started_at={} finished_at={} seconds={} render_seconds={} model_seconds={} body_refs={}",
        page,
        block_id(block),
        block_started,
        _now_iso(),
        block_duration,
        render_seconds,
        _duration(model_timer),
        len(cleaned_refs),
    )
    return cleaned_refs


def _page_footnote_markers_by_page(blocks: List[CanonicalBlock]) -> Dict[int, List[str]]:
    return qwen_page_plan._page_footnote_markers_by_page(blocks)


def _log_info(message: str, *args: Any) -> None:
    try:
        from loguru import logger  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    logger.info(message, *args)


def _log_debug(message: str, *args: Any) -> None:
    try:
        from loguru import logger  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    logger.debug(message, *args)


def _log_warning(message: str, *args: Any) -> None:
    try:
        from loguru import logger  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    logger.warning(message, *args)


def _new_collect_stats() -> Dict[str, Any]:
    return {
        "pages": 0,
        "cache_hits": 0,
        "model_calls": 0,
        "footnote_defs": 0,
        "body_refs": 0,
        "page_seconds": 0.0,
    }


def _update_collect_stats(
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


def _collect_summary(stats: Dict[str, Any], pass_seconds: float) -> Dict[str, Any]:
    return {
        "pages": stats["pages"],
        "cache_hits": stats["cache_hits"],
        "cache_misses": stats["pages"] - stats["cache_hits"],
        "model_calls": stats["model_calls"],
        "footnote_defs": stats["footnote_defs"],
        "body_refs": stats["body_refs"],
        "total_page_seconds": round(float(stats["page_seconds"]), 6),
        "avg_page_seconds": _avg_seconds(stats["page_seconds"], stats["pages"]),
        "pass_seconds": pass_seconds,
    }


def _avg_seconds(total: float, count: int) -> float:
    return round(total / count, 6) if count else 0.0


def _read_existing_evidence(path: Path) -> Dict[tuple[int, str], qwen_types.QwenMarkerPageEvidence]:
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
        out[key] = _merge_cached_qwen_evidence(existing, evidence) if existing is not None else evidence
    return out


def _merge_cached_qwen_evidence(left: qwen_types.QwenMarkerPageEvidence, right: qwen_types.QwenMarkerPageEvidence) -> qwen_types.QwenMarkerPageEvidence:
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


def _write_evidence(path: Path, evidence: Sequence[qwen_types.QwenMarkerPageEvidence]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"engine": "qwen_marker_locator", "pages": [item.to_json() for item in evidence]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _timing_log_path(config: qwen_types.QwenMarkerLocatorConfig) -> Path:
    return config.timing_log_path or (config.artifact_dir / "qwen_marker_timing.jsonl")


def _reset_timing_log(config: qwen_types.QwenMarkerLocatorConfig) -> None:
    path = _timing_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _write_timing_event(config: qwen_types.QwenMarkerLocatorConfig, event: Dict[str, Any]) -> None:
    path = _timing_log_path(config)
    payload = {
        "schema": "qwen_marker_timing.v1",
        **event,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        f.write("\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _duration(start: float) -> float:
    return round(time.perf_counter() - start, 6)
