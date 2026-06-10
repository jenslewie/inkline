"""Qwen visual marker locator — orchestration entry point.

MinerU remains the primary parser. This module renders selected full pages,
asks a local Ollama-hosted Qwen visual model for structured marker evidence,
and applies only footnote-definition marker fixes before note ref recovery.

The implementation has been split into sub-modules:
  - ``qwen_types``: config + evidence dataclasses + constants
  - ``qwen_api``: Ollama API call + JSON extraction + response cleaning
  - ``qwen_prompt``: prompt generation + rendering + footnote matching
  - ``qwen_evidence``: evidence collection + caching + I/O + timing
  - ``qwen_page_plan``: problem-page planning + body candidate selection

This module retains the public entry point ``run_qwen_marker_locator_repairs``
and ``apply_qwen_footnote_markers``, plus convenience aliases
``QwenMarkerLocatorConfig`` and ``QwenMarkerPageEvidence`` from
``qwen_types``.  Uses module-level imports from sub-modules so that
monkeypatching the definition module namespace works correctly.
"""

from __future__ import annotations

from copy import deepcopy
import time
from dataclasses import replace
from typing import Any, Callable, Dict, List, Sequence, cast

from . import qwen_api
from . import qwen_evidence
from . import qwen_page_plan
from . import qwen_prompt
from . import qwen_types
from ...extraction.text import normalize_ws
from ...schema.models import CanonicalBlock



QwenMarkerLocatorConfig = qwen_types.QwenMarkerLocatorConfig
QwenMarkerPageEvidence = qwen_types.QwenMarkerPageEvidence


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_qwen_marker_locator_repairs(
    blocks: List[Dict[str, Any]],
    config: qwen_types.QwenMarkerLocatorConfig,
    *,
    missing_body_ref_pages_after_page: Callable[[List[qwen_types.QwenMarkerPageEvidence]], Sequence[int]] | None = None,
) -> List[qwen_types.QwenMarkerPageEvidence]:
    """Collect Qwen marker evidence and apply footnote-definition marker fixes.

    ``blocks`` arrives from the canonical pipeline as ``List[Dict[str, Any]]``.
    Internally the note subsystem uses ``List[CanonicalBlock]`` for type
    precision.  The cast bridges the two until the full pipeline migration.
    """
    typed_blocks = cast(List[CanonicalBlock], blocks)

    plan = qwen_page_plan._problem_page_plan(typed_blocks)
    pages = set(plan.footnote_pages) | set(plan.body_ref_pages)
    if not pages:
        return []

    # Init run: create artifact dir, start timing, log run_start
    run_started, run_timer = _init_marker_locator_run(config, typed_blocks, pages, plan)

    # Initial evidence pass (page DPI or single block pass)
    initial_config = _body_pass_config(config, "page" if config.body_mode == "page_then_block" else config.body_mode)
    evidence = qwen_evidence._collect_qwen_marker_evidence(
        typed_blocks,
        sorted(pages),
        initial_config,
        pass_name="initial",
        footnote_pages=plan.footnote_pages,
        body_ref_pages=plan.body_ref_pages,
        expected_body_markers_by_page=qwen_evidence._page_footnote_markers_by_page(typed_blocks),
    )
    apply_qwen_footnote_markers(typed_blocks, evidence)

    # Retry pass for pages still missing body refs
    missing_pages = _missing_body_ref_pages(config, typed_blocks, plan, evidence, missing_body_ref_pages_after_page)
    if missing_pages:
        retry_config = _body_pass_config(config, "block" if config.body_mode == "page_then_block" else config.body_mode)
        evidence.extend(
            qwen_evidence._collect_qwen_marker_evidence(
                typed_blocks,
                missing_pages,
                retry_config,
                pass_name="body_ref_retry",
                footnote_pages=set(),
                body_ref_pages=set(missing_pages),
                expected_body_markers_by_page=qwen_evidence._page_footnote_markers_by_page(typed_blocks),
            )
        )

    # Write evidence and log run_end
    _finish_marker_locator_run(config, evidence, run_started, run_timer)
    return evidence


def _init_marker_locator_run(
    config: qwen_types.QwenMarkerLocatorConfig,
    blocks: List[CanonicalBlock],
    pages: set[int],
    plan: Any,
) -> tuple[str, float]:
    """Create artifact dir, reset timing log, and emit run_start event."""
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    qwen_evidence._reset_timing_log(config)
    run_started = qwen_evidence._now_iso()
    run_timer = time.perf_counter()
    qwen_evidence._write_timing_event(
        config,
        {
            "event": "run_start",
            "started_at": run_started,
            "model": config.model,
            "dpi": config.dpi,
            "page_dpi": config.page_dpi,
            "block_dpi": config.block_dpi,
            "body_mode": config.body_mode,
            "reuse_evidence": config.reuse_evidence,
            "source_pdf": str(config.source_pdf),
            "artifact_dir": str(config.artifact_dir),
            "planned_pages": sorted(pages),
            "footnote_pages": sorted(plan.footnote_pages),
            "body_ref_pages": sorted(plan.body_ref_pages),
        },
    )
    return run_started, run_timer


def _missing_body_ref_pages(
    config: qwen_types.QwenMarkerLocatorConfig,
    blocks: List[CanonicalBlock],
    plan: Any,
    evidence: List[qwen_types.QwenMarkerPageEvidence],
    missing_body_ref_pages_after_page: Callable[[List[qwen_types.QwenMarkerPageEvidence]], Sequence[int]] | None,
) -> List[int]:
    """Determine which pages need a retry pass for body refs."""
    if config.body_mode == "page_then_block":
        return (
            sorted({int(page) for page in missing_body_ref_pages_after_page(evidence)})
            if missing_body_ref_pages_after_page is not None
            else []
        )
    body_plan = qwen_page_plan._problem_page_plan(blocks)
    return sorted(set(body_plan.body_ref_pages) - set(plan.body_ref_pages))


def _finish_marker_locator_run(
    config: qwen_types.QwenMarkerLocatorConfig,
    evidence: List[qwen_types.QwenMarkerPageEvidence],
    run_started: str,
    run_timer: float,
) -> None:
    """Write evidence JSON and emit run_end timing event."""
    qwen_evidence._write_evidence(config.artifact_dir / "qwen_marker_evidence.json", evidence)
    qwen_evidence._write_timing_event(
        config,
        {
            "event": "run_end",
            "started_at": run_started,
            "finished_at": qwen_evidence._now_iso(),
            "duration_seconds": qwen_evidence._duration(run_timer),
            "evidence_items": len(evidence),
            "unique_pages": sorted({item.page for item in evidence}),
            "evidence_path": str(config.artifact_dir / "qwen_marker_evidence.json"),
        },
    )


def _body_pass_config(config: qwen_types.QwenMarkerLocatorConfig, body_mode: str) -> qwen_types.QwenMarkerLocatorConfig:
    if body_mode == "page":
        return replace(config, body_mode="page", dpi=config.page_dpi)
    if body_mode == "block":
        return replace(config, body_mode="block", dpi=config.block_dpi)
    return config


def apply_qwen_footnote_markers(blocks: List[CanonicalBlock], evidence_pages: Sequence[qwen_types.QwenMarkerPageEvidence]) -> None:
    evidence_by_page: Dict[int, qwen_types.QwenMarkerPageEvidence] = {}
    for item in evidence_pages:
        existing = evidence_by_page.get(item.page)
        if existing is None or len(item.footnote_defs) > len(existing.footnote_defs):
            evidence_by_page[item.page] = item
    for page, page_blocks in qwen_page_plan._page_footnotes_by_page(blocks).items():
        evidence = evidence_by_page.get(page)
        if evidence is None:
            continue
        defs = [qwen_api._clean_footnote_def(item) for item in evidence.footnote_defs]
        defs = [item for item in defs if item is not None]
        if not defs:
            continue
        if len(defs) > len(page_blocks):
            _split_merged_footnote_blocks(blocks, page, defs)
            page_blocks = qwen_page_plan._page_footnotes_by_page(blocks).get(page, [])
        if len(defs) == len(page_blocks) and qwen_prompt._footnote_defs_match_blocks(defs, page_blocks):
            for block, item in zip(page_blocks, defs):
                qwen_prompt._apply_qwen_footnote_marker(block, item["marker"], page, evidence=evidence)
            continue
        qwen_prompt._apply_unique_near_text_matches(page_blocks, defs, page, evidence)


def _split_merged_footnote_blocks(
    blocks: List[CanonicalBlock],
    page: int,
    defs: Sequence[Dict[str, Any]],
) -> None:
    page_blocks = qwen_page_plan._page_footnotes_by_page(blocks).get(page, [])
    deficit = len(defs) - len(page_blocks)
    if deficit <= 0:
        return

    for block in page_blocks:
        parts = _footnote_parts_from_qwen_hints(str(block.get("text") or ""), defs, deficit + 1)
        if len(parts) <= 1:
            continue
        block_index = next((index for index, item in enumerate(blocks) if item is block), None)
        if block_index is None:
            continue
        split_blocks = _make_qwen_split_blocks(block, parts, blocks)
        blocks[block_index : block_index + 1] = split_blocks
        deficit -= len(split_blocks) - 1
        if deficit <= 0:
            return


def _footnote_parts_from_qwen_hints(
    text: str,
    defs: Sequence[Dict[str, Any]],
    max_parts: int,
) -> List[str]:
    lines = [normalize_ws(line) for line in text.splitlines() if normalize_ws(line)]
    if len(lines) <= 1 or max_parts <= 1:
        return [text]

    boundaries: List[int] = []
    for line_index, line in enumerate(lines[1:], 1):
        if any(_near_text_starts_line(item.get("near_text"), line) for item in defs[1:]):
            boundaries.append(line_index)
    if not boundaries and max_parts == len(lines):
        boundaries = list(range(1, len(lines)))
    if not boundaries:
        return [text]

    boundaries = boundaries[: max_parts - 1]
    cuts = [0, *boundaries, len(lines)]
    return [
        "\n".join(lines[cuts[index] : cuts[index + 1]])
        for index in range(len(cuts) - 1)
        if cuts[index] < cuts[index + 1]
    ]


def _near_text_starts_line(near_text: Any, line: str) -> bool:
    needle = _compact_match_text(str(near_text or ""))
    haystack = _compact_match_text(line)
    if not needle or not haystack:
        return False
    prefix = needle[: min(16, len(needle))]
    return len(prefix) >= 4 and prefix in haystack[: max(32, len(prefix) + 8)]


def _compact_match_text(text: str) -> str:
    return "".join(normalize_ws(text).lstrip("*＊0123456789.．。、)） ").split()).lower()


def _make_qwen_split_blocks(
    block: CanonicalBlock,
    parts: Sequence[str],
    all_blocks: Sequence[CanonicalBlock],
) -> List[CanonicalBlock]:
    source = block.get("source") or {}
    bbox = source.get("bbox")
    boxes = _split_bbox_vertically(bbox, len(parts))
    split_from = str(block.get("block_id") or "")
    existing_ids = {str(item.get("block_id") or "") for item in all_blocks}
    out: List[CanonicalBlock] = []
    for index, part in enumerate(parts):
        item = deepcopy(block)
        if index:
            item["block_id"] = _unique_split_block_id(split_from, index + 1, existing_ids)
            existing_ids.add(str(item["block_id"]))
        item["text"] = part
        item["source"]["bbox"] = boxes[index]
        attrs = item.setdefault("attrs", {})
        attrs.pop("note_id", None)
        attrs.pop("referenced_by", None)
        attrs.pop("note_marker", None)
        attrs.pop("note_marker_source", None)
        attrs["split_from"] = split_from
        attrs["split_index"] = index + 1
        attrs["split_count"] = len(parts)
        attrs["split_reason"] = "qwen_footnote_definition_count"
        out.append(item)
    return out


def _unique_split_block_id(base: str, suffix: int, existing_ids: set[str]) -> str:
    candidate = f"{base}_{suffix}"
    serial = suffix
    while candidate in existing_ids:
        serial += 1
        candidate = f"{base}_{serial}"
    return candidate


def _split_bbox_vertically(bbox: Sequence[float] | None, count: int) -> List[List[float] | None]:
    if not bbox or len(bbox) < 4:
        return [None] * count
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    step = max(1.0, y1 - y0) / count
    return [
        [x0, y0 + step * index, x1, y1 if index == count - 1 else y0 + step * (index + 1)]
        for index in range(count)
    ]
