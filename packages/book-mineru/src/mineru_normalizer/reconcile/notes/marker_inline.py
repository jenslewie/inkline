"""Inline note marker insertion position. Defines _InlineMarkerLocation and helpers for determining where in a block's text an inline note marker should be inserted, based on marker offsets and existing reference positions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ...extraction.text import normalize_note_marker
from .marker_patterns import _marker_int


@dataclass(frozen=True)
class _InlineMarkerLocation:
    char_index: int
    source: str
    confidence: str
    evidence: Dict[str, Any]


def _append_note_ref(
    block: Dict[str, Any],
    marker: str,
    *,
    source: str,
    confidence: str,
    recovery_reason: str,
    raw_marker: str,
    source_page: Optional[int] = None,
    evidence: Optional[Dict[str, Any]] = None,
    inline_location: Optional[_InlineMarkerLocation] = None,
) -> None:
    attrs = block.setdefault("attrs", {})
    refs = list(attrs.get("note_refs") or [])
    ref: Dict[str, Any] = {
        "marker": marker,
        "position": "after_text",
        "source": source,
        "source_page": source_page if source_page is not None else _last_page(block),
        "confidence": confidence,
        "recovery_reason": recovery_reason,
    }
    if raw_marker:
        ref["raw_marker"] = raw_marker
    else:
        ref["inferred"] = True
        ref["inline_position"] = "unknown"
    if inline_location:
        ref["inline_position"] = "exact"
        ref["inline_position_source"] = inline_location.source
        ref["inline_position_confidence"] = inline_location.confidence
        ref["inline_offset"] = inline_location.char_index
    if evidence:
        ref["evidence"] = evidence
    refs.append(ref)
    attrs["note_refs"] = refs
    if inline_location:
        _insert_inline_note_run(block, ref, inline_location.char_index)


def _rebuild_inline_note_runs_from_exact_refs(block: Dict[str, Any]) -> None:
    text = str(block.get("text") or "")
    attrs = block.setdefault("attrs", {})
    refs = [ref for ref in attrs.get("note_refs") or [] if isinstance(ref, dict)]
    exact_refs = [
        ref
        for ref in refs
        if _ref_requires_inline_run(ref)
        and isinstance(ref.get("inline_offset"), int)
        and 0 <= int(ref.get("inline_offset")) <= len(text)
    ]
    if not exact_refs:
        attrs.pop("inline_runs", None)
        return
    exact_refs.sort(
        key=lambda ref: (
            int(ref.get("inline_offset")),
            int(ref.get("source_page")) if isinstance(ref.get("source_page"), int) else 10**9,
            _inline_marker_sort_value(ref.get("marker")),
            str(ref.get("marker") or ""),
        )
    )
    runs: List[Dict[str, Any]] = []
    cursor = 0
    for ref in exact_refs:
        offset = int(ref.get("inline_offset"))
        if offset < cursor:
            continue
        if offset > cursor:
            runs.append({"type": "text", "text": text[cursor:offset]})
        runs.append(_inline_note_run_from_ref(ref))
        cursor = offset
    if cursor < len(text):
        runs.append({"type": "text", "text": text[cursor:]})
    attrs["inline_runs"] = _coalesce_text_runs(runs)


def _inline_note_run_from_ref(ref: Dict[str, Any]) -> Dict[str, Any]:
    """Create an inline note_run dict from a note_ref dict.

    Copies only keys that actually exist in *ref* (using the key-tuple
    iteration pattern from the former resolver.py implementation — cleaner
    than the old dict comprehension, which copied all keys including
    irrelevant ones).  Applies ``_fallback_raw_marker`` for missing
    ``raw_marker`` values (richer logic with superscript/equation handling).
    **Preserves the write-back side effect**: ``ref.setdefault("raw_marker",
    raw_marker)`` — resolver.py callers rely on ``raw_marker`` being
    populated in the ref dict after this call.
    """
    run: Dict[str, Any] = {}
    for key in (
        "marker",
        "position",
        "source",
        "source_page",
        "raw_marker",
        "confidence",
        "recovery_reason",
        "inline_position",
        "inline_position_source",
        "inline_position_confidence",
        "inline_offset",
        "target_block_id",
        "target_note_id",
        "note_strategy",
        "resolution_confidence",
    ):
        if key in ref:
            run[key] = ref[key]
    if not run.get("raw_marker"):
        raw_marker = _fallback_raw_marker(run)
        if raw_marker:
            run["raw_marker"] = raw_marker
            ref.setdefault("raw_marker", raw_marker)
    run["type"] = "note_ref"
    return run


def _ref_requires_inline_run(ref: Dict[str, Any]) -> bool:
    source = str(ref.get("source") or "")
    if source in {"equation_inline", "equation_interline", "trailing_text"}:
        return True
    return ref.get("inline_position") == "exact"


def _insert_inline_note_run(block: Dict[str, Any], ref: Dict[str, Any], char_index: int) -> None:
    text = str(block.get("text") or "")
    if char_index < 0 or char_index > len(text):
        return
    attrs = block.setdefault("attrs", {})
    runs = attrs.get("inline_runs")
    if not _inline_runs_reconstruct_text(runs, text):
        runs = [{"type": "text", "text": text}]
    assert isinstance(runs, list)
    note_run = _inline_note_run_from_ref(ref)

    out: List[Dict[str, Any]] = []
    consumed = 0
    inserted = False
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("type") != "text":
            out.append(dict(run))
            continue
        run_text = str(run.get("text") or "")
        next_consumed = consumed + len(run_text)
        if not inserted and consumed <= char_index <= next_consumed:
            split_at = char_index - consumed
            if split_at > 0:
                left = dict(run)
                left["text"] = run_text[:split_at]
                out.append(left)
            out.append(note_run)
            if split_at < len(run_text):
                right = dict(run)
                right["text"] = run_text[split_at:]
                out.append(right)
            inserted = True
        else:
            out.append(dict(run))
        consumed = next_consumed
    if not inserted:
        out.append(note_run)
    attrs["inline_runs"] = _coalesce_text_runs(out)


def _inline_runs_reconstruct_text(runs: Any, text: str) -> bool:
    if not isinstance(runs, list):
        return False
    reconstructed = "".join(
        str(run.get("text") or "")
        for run in runs
        if isinstance(run, dict) and run.get("type") == "text"
    )
    return reconstructed == text


def _coalesce_text_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for run in runs:
        if run.get("type") == "text" and not run.get("text"):
            continue
        if out and out[-1].get("type") == "text" and run.get("type") == "text":
            out[-1]["text"] = str(out[-1].get("text") or "") + str(run.get("text") or "")
        else:
            out.append(run)
    return _order_same_offset_note_runs(out)


def _order_same_offset_note_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    index = 0
    while index < len(runs):
        run = runs[index]
        if run.get("type") != "note_ref" or "inline_offset" not in run:
            out.append(run)
            index += 1
            continue
        group = [run]
        index += 1
        while (
            index < len(runs)
            and runs[index].get("type") == "note_ref"
            and runs[index].get("inline_offset") == group[0].get("inline_offset")
            and runs[index].get("source_page") == group[0].get("source_page")
        ):
            group.append(runs[index])
            index += 1
        out.extend(sorted(group, key=lambda item: (_inline_marker_sort_value(item.get("marker")), str(item.get("marker") or ""))))
    return out


def _inline_marker_sort_value(marker: Any) -> int:
    text = normalize_note_marker(marker)
    if text.startswith("*"):
        return -1
    marker_int = _marker_int(text)
    return marker_int if marker_int is not None else 10**9


def _fallback_raw_marker(ref: Dict[str, Any]) -> Optional[str]:
    """Determine the raw_marker for a note ref.

    Returns the marker itself for star markers (``*``-family).  For numeric
    markers, returns ``^{marker}`` only when the source is an equation type
    (``equation_inline``, ``equation_interline``, ``trailing_text``) or
    ``inline_position`` is ``"exact"``.  Otherwise returns ``None`` —
    meaning no raw_marker should be emitted.
    """
    marker = normalize_note_marker(ref.get("marker", ""))
    if not marker:
        return None
    if marker.startswith("*"):
        return marker
    source = str(ref.get("source") or "")
    if source in {"equation_inline", "equation_interline", "trailing_text"} or ref.get("inline_position") == "exact":
        return f"^{{{marker}}}"
    return None


def _note_refs(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs = (block.get("attrs") or {}).get("note_refs")
    return [ref for ref in refs if isinstance(ref, dict)] if isinstance(refs, list) else []


def _existing_ref_markers(block: Dict[str, Any]) -> set[str]:
    return {normalize_note_marker(ref.get("marker", "")) for ref in _note_refs(block)}


def _last_page(block: Dict[str, Any]) -> Optional[int]:
    source = block.get("source") or {}
    pages = source.get("pages")
    if isinstance(pages, list) and pages:
        page = pages[-1]
        return int(page) if isinstance(page, int) else None
    page = source.get("page")
    return int(page) if isinstance(page, int) else None
