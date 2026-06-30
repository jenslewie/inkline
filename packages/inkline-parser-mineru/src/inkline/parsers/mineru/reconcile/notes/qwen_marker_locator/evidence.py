"""Qwen marker evidence collection, caching, I/O, and timing.

Contains the main evidence collection loop, paragraph body-ref collection,
single-marker retry, evidence read/write, and timing helpers.  Uses module-
level imports from sibling modules so that monkeypatching works
correctly (patch the definition module namespace).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, cast

from ....analysis.page_geometry import PageGeometry
from ....schema.models import CanonicalBlock
from ...block_access import block_id
from . import api as qwen_api
from . import evidence_store
from . import page_plan as qwen_page_plan
from . import prompt as qwen_prompt
from . import types as qwen_types

_avg_seconds = evidence_store.avg_seconds
_collect_summary = evidence_store.collect_summary
_duration = evidence_store.duration
_log_debug = evidence_store.log_debug
_log_info = evidence_store.log_info
_log_warning = evidence_store.log_warning
_new_collect_stats = evidence_store.new_collect_stats
_now_iso = evidence_store.now_iso
_read_existing_evidence = evidence_store.read_existing_evidence
_reset_timing_log = evidence_store.reset_timing_log
_update_collect_stats = evidence_store.update_collect_stats
_write_evidence = evidence_store.write_evidence
_write_timing_event = evidence_store.write_timing_event


@dataclass
class _QwenCollectPass:
    page_list: List[int]
    footnote_pages: set[int]
    body_ref_pages: set[int]
    expected_body_markers_by_page: Dict[int, List[str]]
    cache: Dict[tuple[int, str], qwen_types.QwenMarkerPageEvidence]
    use_block_body_refs: bool
    geometry: PageGeometry | None
    body_blocks_by_page: Dict[int, List[CanonicalBlock]]
    body_ref_source: str
    started_at: str
    timer: float
    stats: Dict[str, Any]


@dataclass(frozen=True)
class _QwenPageRender:
    pdf_page: Any
    image_path: Path
    started_at: str
    timer: float
    render_duration: float


@dataclass
class _QwenPageCacheState:
    cached_item: qwen_types.QwenMarkerPageEvidence | None
    cache_hit: bool
    raw_parts: Dict[str, Any]
    footnote_cached: bool
    body_cached: bool
    model_calls: List[Dict[str, Any]]


@dataclass(frozen=True)
class _QwenPageResult:
    item: qwen_types.QwenMarkerPageEvidence
    cache_hit: bool
    model_calls: List[Dict[str, Any]]
    page_started: str
    page_duration: float
    render_duration: float
    image_path: Path


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
    fitz = _import_fitz()
    collect_pass = _start_qwen_collect_pass(
        blocks,
        pages,
        config,
        pass_name,
        footnote_pages,
        body_ref_pages,
        expected_body_markers_by_page,
    )
    evidence: List[qwen_types.QwenMarkerPageEvidence] = []
    with fitz.open(config.source_pdf) as doc:
        for page_index, page in enumerate(collect_pass.page_list, start=1):
            result = _collect_qwen_page_result(
                doc, page_index, page, config, pass_name, collect_pass
            )
            if result is None:
                continue
            evidence.append(result.item)
            _record_qwen_page_result(result, page_index, page, config, pass_name, collect_pass)
    _finish_qwen_collect_pass(evidence, config, pass_name, collect_pass)
    return evidence


def _import_fitz() -> Any:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("Qwen marker locator page rendering requires PyMuPDF (`fitz`).") from exc
    return fitz


def _start_qwen_collect_pass(
    blocks: Sequence[CanonicalBlock],
    pages: Sequence[int],
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    footnote_pages: set[int] | None,
    body_ref_pages: set[int] | None,
    expected_body_markers_by_page: Dict[int, List[str]] | None,
) -> _QwenCollectPass:
    cache = (
        _read_existing_evidence(config.artifact_dir / "qwen_marker_evidence.json")
        if config.reuse_evidence
        else {}
    )
    use_block_body_refs = config.body_mode == "block"
    geometry = (
        PageGeometry.from_canonical_blocks(cast(Sequence[Dict[str, Any]], blocks))
        if use_block_body_refs
        else None
    )
    body_blocks_by_page = qwen_prompt._body_blocks_by_page(blocks) if use_block_body_refs else {}
    body_ref_source = "paragraph_crops" if use_block_body_refs else "full_page"
    resolved_footnote_pages = set() if footnote_pages is None else footnote_pages
    resolved_body_ref_pages = set(pages) if body_ref_pages is None else body_ref_pages
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
        len(resolved_footnote_pages),
        len(resolved_body_ref_pages),
    )
    _write_timing_event(
        config,
        {
            "event": "collect_pass_start",
            "pass": pass_name,
            "started_at": pass_started,
            "pages": page_list,
            "footnote_pages": sorted(resolved_footnote_pages),
            "body_ref_pages": sorted(resolved_body_ref_pages),
        },
    )
    return _QwenCollectPass(
        page_list=page_list,
        footnote_pages=resolved_footnote_pages,
        body_ref_pages=resolved_body_ref_pages,
        expected_body_markers_by_page=expected_body_markers_by_page or {},
        cache=cache,
        use_block_body_refs=use_block_body_refs,
        geometry=geometry,
        body_blocks_by_page=body_blocks_by_page,
        body_ref_source=body_ref_source,
        started_at=pass_started,
        timer=pass_timer,
        stats=pass_stats,
    )


def _collect_qwen_page_result(
    doc: Any,
    page_index: int,
    page: int,
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> _QwenPageResult | None:
    if page < 1 or page > doc.page_count:
        _record_skipped_qwen_page(page_index, page, doc.page_count, config, pass_name, collect_pass)
        return None
    render = _render_qwen_page(doc, page_index, page, config, pass_name, collect_pass)
    state = _qwen_page_cache_state(page, render.image_path, collect_pass)
    item = _qwen_page_evidence_item(page, render, state, config, pass_name, collect_pass)
    return _QwenPageResult(
        item=item,
        cache_hit=state.cache_hit,
        model_calls=state.model_calls,
        page_started=render.started_at,
        page_duration=_duration(render.timer),
        render_duration=render.render_duration,
        image_path=render.image_path,
    )


def _record_skipped_qwen_page(
    page_index: int,
    page: int,
    page_count: int,
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> None:
    _log_warning(
        "Qwen marker locator pass `{}` page {}/{} skipped: page {} outside PDF page_count={}",
        pass_name,
        page_index,
        len(collect_pass.page_list),
        page,
        page_count,
    )
    _write_timing_event(
        config,
        {
            "event": "page_skipped",
            "pass": pass_name,
            "page": page,
            "reason": "outside_pdf_page_range",
            "page_count": page_count,
            "finished_at": _now_iso(),
        },
    )


def _render_qwen_page(
    doc: Any,
    page_index: int,
    page: int,
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> _QwenPageRender:
    page_started = _now_iso()
    page_timer = time.perf_counter()
    render_timer = time.perf_counter()
    pdf_page = doc[page - 1]
    image_path = config.artifact_dir / f"page_{page:04d}_{config.dpi}dpi_qwen_full_page.png"
    _log_qwen_page_start(page_index, page, config, pass_name, collect_pass)
    try:
        qwen_prompt._render_full_page(pdf_page, image_path, config)
    except Exception as exc:
        _record_qwen_page_render_error(
            config, pass_name, page, page_started, page_timer, render_timer, exc
        )
        raise
    return _QwenPageRender(
        pdf_page=pdf_page,
        image_path=image_path,
        started_at=page_started,
        timer=page_timer,
        render_duration=_duration(render_timer),
    )


def _log_qwen_page_start(
    page_index: int,
    page: int,
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> None:
    _log_debug(
        "Qwen marker locator pass `{}` page {}/{} (pdf page {}): footnote_defs={} body_refs={} mode={}",
        pass_name,
        page_index,
        len(collect_pass.page_list),
        page,
        page in collect_pass.footnote_pages,
        page in collect_pass.body_ref_pages,
        config.body_mode,
    )


def _record_qwen_page_render_error(
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    page: int,
    page_started: str,
    page_timer: float,
    render_timer: float,
    exc: Exception,
) -> None:
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


def _qwen_page_cache_state(
    page: int, image_path: Path, collect_pass: _QwenCollectPass
) -> _QwenPageCacheState:
    cached_item = collect_pass.cache.get((page, image_path.name))
    raw_parts = dict(cached_item.raw_json) if cached_item is not None else {}
    return _QwenPageCacheState(
        cached_item=cached_item,
        cache_hit=cached_item is not None,
        raw_parts=raw_parts,
        footnote_cached=cached_item is not None and "footnote_defs" in raw_parts,
        body_cached=(
            cached_item is not None
            and raw_parts.get("body_ref_source") == collect_pass.body_ref_source
        ),
        model_calls=[],
    )


def _qwen_page_evidence_item(
    page: int,
    render: _QwenPageRender,
    state: _QwenPageCacheState,
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> qwen_types.QwenMarkerPageEvidence:
    if not _qwen_page_needs_collection(page, state, collect_pass):
        assert state.cached_item is not None
        return state.cached_item
    _collect_missing_qwen_page_parts(page, render, state, config, pass_name, collect_pass)
    return qwen_types.QwenMarkerPageEvidence(
        page=page,
        image=str(render.image_path),
        crop_bbox_pdf=[
            float(render.pdf_page.rect.x0),
            float(render.pdf_page.rect.y0),
            float(render.pdf_page.rect.x1),
            float(render.pdf_page.rect.y1),
        ],
        dpi=config.dpi,
        raw_json=state.raw_parts,
        body_refs=qwen_api._clean_body_refs(state.raw_parts.get("body_refs")),
        footnote_defs=qwen_api._clean_footnote_defs(state.raw_parts.get("footnote_defs")),
    )


def _qwen_page_needs_collection(
    page: int, state: _QwenPageCacheState, collect_pass: _QwenCollectPass
) -> bool:
    return (
        state.cached_item is None
        or (page in collect_pass.footnote_pages and not state.footnote_cached)
        or (page in collect_pass.body_ref_pages and not state.body_cached)
    )


def _collect_missing_qwen_page_parts(
    page: int,
    render: _QwenPageRender,
    state: _QwenPageCacheState,
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> None:
    if page in collect_pass.footnote_pages and not state.footnote_cached:
        state.raw_parts, state.model_calls = _collect_footnote_defs_for_page(
            render.image_path,
            config,
            state.raw_parts,
            pass_name,
            page,
            render.started_at,
            render.timer,
            render.render_duration,
            state.cache_hit,
            state.model_calls,
        )
    if page in collect_pass.body_ref_pages and not state.body_cached:
        state.raw_parts, state.model_calls = _collect_body_refs_for_page(
            render.image_path,
            render.pdf_page,
            page,
            config,
            state.raw_parts,
            collect_pass.use_block_body_refs,
            collect_pass.body_blocks_by_page,
            collect_pass.geometry,
            collect_pass.expected_body_markers_by_page,
            collect_pass.body_ref_source,
            pass_name,
            render.started_at,
            render.timer,
            render.render_duration,
            state.cache_hit,
            state.model_calls,
        )


def _record_qwen_page_result(
    result: _QwenPageResult,
    page_index: int,
    page: int,
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> None:
    _update_collect_stats(
        collect_pass.stats,
        result.cache_hit,
        result.model_calls,
        len(result.item.footnote_defs),
        len(result.item.body_refs),
        result.page_duration,
    )
    _log_qwen_page_end(result, page_index, page, pass_name, collect_pass)
    _write_qwen_page_end_event(result, page, config, pass_name, collect_pass)


def _log_qwen_page_end(
    result: _QwenPageResult,
    page_index: int,
    page: int,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> None:
    _log_info(
        "Qwen marker locator pass `{}` page {}/{} done: page={} started_at={} finished_at={} seconds={} render_seconds={} cache_hit={} model_calls={} footnote_defs={} body_refs={}",
        pass_name,
        page_index,
        len(collect_pass.page_list),
        page,
        result.page_started,
        _now_iso(),
        result.page_duration,
        result.render_duration,
        result.cache_hit,
        len(result.model_calls),
        len(result.item.footnote_defs),
        len(result.item.body_refs),
    )


def _write_qwen_page_end_event(
    result: _QwenPageResult,
    page: int,
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> None:
    _write_timing_event(
        config,
        {
            "event": "page_end",
            "pass": pass_name,
            "page": page,
            "started_at": result.page_started,
            "finished_at": _now_iso(),
            "duration_seconds": result.page_duration,
            "render_seconds": result.render_duration,
            "cache_hit": result.cache_hit,
            "image": str(result.image_path),
            "image_bytes": result.image_path.stat().st_size if result.image_path.exists() else None,
            "requested_footnote_defs": page in collect_pass.footnote_pages,
            "requested_body_refs": page in collect_pass.body_ref_pages,
            "model_calls": result.model_calls,
            "footnote_def_count": len(result.item.footnote_defs),
            "body_ref_count": len(result.item.body_refs),
        },
    )


def _finish_qwen_collect_pass(
    evidence: List[qwen_types.QwenMarkerPageEvidence],
    config: qwen_types.QwenMarkerLocatorConfig,
    pass_name: str,
    collect_pass: _QwenCollectPass,
) -> None:
    pass_duration = _duration(collect_pass.timer)
    _write_timing_event(
        config,
        {
            "event": "collect_pass_end",
            "pass": pass_name,
            "started_at": collect_pass.started_at,
            "finished_at": _now_iso(),
            "duration_seconds": pass_duration,
            "evidence_items": len(evidence),
            "summary": _collect_summary(collect_pass.stats, pass_duration),
        },
    )
    _log_info(
        "Qwen marker locator pass `{}` finished: started_at={} finished_at={} pages={} evidence_items={} cache_hits={} model_calls={} footnote_defs={} body_refs={} seconds={} avg_page_seconds={}",
        pass_name,
        collect_pass.started_at,
        _now_iso(),
        len(collect_pass.page_list),
        len(evidence),
        collect_pass.stats["cache_hits"],
        collect_pass.stats["model_calls"],
        collect_pass.stats["footnote_defs"],
        collect_pass.stats["body_refs"],
        pass_duration,
        _avg_seconds(collect_pass.stats["page_seconds"], collect_pass.stats["pages"]),
    )


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
        footnote_raw = qwen_api._call_qwen_marker_locator(
            image_path, config, prompt=config.footnote_prompt
        )
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
            "raw_item_count": len(footnote_raw.get("footnote_defs") or [])
            if isinstance(footnote_raw, dict)
            else 0,
        }
    )
    _log_debug(
        "Qwen marker locator page {}: footnote definitions returned {} item(s) in {}s",
        page,
        len(footnote_raw.get("footnote_defs") or []) if isinstance(footnote_raw, dict) else 0,
        _duration(call_timer),
    )
    raw_parts["footnote_defs"] = (
        footnote_raw.get("footnote_defs") if isinstance(footnote_raw, dict) else []
    )
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
    markers = qwen_prompt._body_markers_for_prompt(
        marker_items, expected_body_markers_by_page.get(page, [])
    )
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
            body_raw = qwen_api._call_qwen_marker_locator(
                image_path,
                config,
                prompt=qwen_prompt._body_prompt_for_markers(config.body_prompt, markers),
            )
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
            "duration_seconds": call_duration
            if call_duration is not None
            else _duration(call_timer),
            "markers_for_prompt": markers,
            "raw_item_count": len(body_raw)
            if use_block_body_refs
            else (len(body_raw.get("body_refs") or []) if isinstance(body_raw, dict) else 0),
        }
    )
    _log_debug(
        "Qwen marker locator page {}: body refs returned {} item(s) in {}s",
        page,
        len(body_raw)
        if use_block_body_refs
        else (len(body_raw.get("body_refs") or []) if isinstance(body_raw, dict) else 0),
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
        single_raw = qwen_api._call_qwen_marker_locator(
            image_path, config, prompt=qwen_prompt._single_marker_body_prompt(marker)
        )
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
        refs = _collect_single_paragraph_body_refs(
            pdf_page, page, block, bbox, geometry, config, markers
        )
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
    image_path = (
        config.artifact_dir / f"page_{page:04d}_{block_label}_{config.dpi}dpi_qwen_body_block.png"
    )
    block_started = _now_iso()
    block_timer = time.perf_counter()
    render_timer = time.perf_counter()
    try:
        crop_bbox_pdf = qwen_prompt._render_block_crop(
            pdf_page, image_path, page, bbox, geometry, config
        )
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
        raw = qwen_api._call_qwen_marker_locator(
            image_path,
            config,
            prompt=qwen_prompt._paragraph_body_prompt_for_markers(markers, block),
        )
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
