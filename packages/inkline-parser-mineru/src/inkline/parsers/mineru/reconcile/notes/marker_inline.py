"""Inline note marker insertion position. Defines _InlineMarkerLocation and helpers for determining where in a block's text an inline note marker should be inserted, based on marker offsets and existing reference positions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from ...extraction.text import normalize_note_marker, normalize_ws
from ...schema.models import CanonicalBlock
from .marker_patterns import _marker_int


@dataclass(frozen=True)
class _InlineMarkerLocation:
    char_index: int
    source: str
    confidence: str
    evidence: Dict[str, Any]


def _append_note_ref(
    block: CanonicalBlock,
    marker: str,
    *,
    source: str,
    confidence: str,
    recovery_reason: str,
    raw_marker: str,
    source_page: Optional[int] = None,
    evidence: Optional[Dict[str, Any]] = None,
    inline_location: _InlineMarkerLocation,
) -> None:
    ref: Dict[str, Any] = {
        "marker": marker,
        "source": source,
        "source_page": source_page if source_page is not None else _last_page(block),
        "confidence": confidence,
        "recovery_reason": recovery_reason,
    }
    if raw_marker:
        ref["raw_marker"] = raw_marker
    else:
        ref["inferred"] = True
    if evidence:
        ref["evidence"] = evidence
    _insert_inline_note_run(block, ref, inline_location.char_index)


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
        "source",
        "source_page",
        "raw_marker",
        "confidence",
        "recovery_reason",
        "target_block_id",
        "target_note_id",
        "note_strategy",
        "resolution_confidence",
        "evidence",
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


def _insert_inline_note_run(block: CanonicalBlock, ref: Dict[str, Any], char_index: int) -> None:
    text = str(block.get("text") or "")
    if char_index < 0 or char_index > len(text):
        return
    attrs = block.setdefault("attrs", {})
    runs = attrs.get("inline_runs")
    run_char_index = char_index
    if isinstance(runs, list):
        reconstructed = _inline_runs_text(runs)
        if reconstructed != text:
            run_char_index = _raw_index_for_normalized_text(reconstructed, text, char_index)
    if not isinstance(runs, list) or run_char_index is None:
        runs = [{"type": "text", "text": text}]
        run_char_index = char_index
    assert isinstance(runs, list)
    runs = [
        dict(run)
        for run in runs
        if isinstance(run, dict)
        and not (run.get("type") == "note_ref" and _same_inline_note_ref(run, ref))
    ]
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
        if not inserted and consumed <= run_char_index <= next_consumed:
            split_at = run_char_index - consumed
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


def _same_inline_note_ref(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return (
        normalize_note_marker(left.get("marker", ""))
        == normalize_note_marker(right.get("marker", ""))
        and str(left.get("source") or "") == str(right.get("source") or "")
        and left.get("source_page") == right.get("source_page")
    )


def _inline_note_run_char_index(block: CanonicalBlock, ref: Dict[str, Any]) -> Optional[int]:
    runs = (block.get("attrs") or {}).get("inline_runs")
    if not isinstance(runs, list):
        return None
    raw_prefix = ""
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("type") == "text":
            raw_prefix += str(run.get("text") or "")
        elif run.get("type") == "note_ref" and _same_inline_note_ref(run, ref):
            return len(normalize_ws(raw_prefix))
    return None


def _inline_runs_text(runs: List[Any]) -> str:
    return "".join(
        str(run.get("text") or "")
        for run in runs
        if isinstance(run, dict) and run.get("type") == "text"
    )


def _raw_index_for_normalized_text(raw_text: str, text: str, char_index: int) -> Optional[int]:
    if normalize_ws(raw_text) != normalize_ws(text):
        return None
    target_prefix = normalize_ws(text[:char_index])
    candidates = [
        raw_index
        for raw_index in range(len(raw_text) + 1)
        if normalize_ws(raw_text[:raw_index]) == target_prefix
    ]
    return max(candidates) if candidates else None


def _coalesce_text_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for run in runs:
        if run.get("type") == "text" and not run.get("text"):
            continue
        if out and out[-1].get("type") == "text" and run.get("type") == "text":
            out[-1]["text"] = str(out[-1].get("text") or "") + str(run.get("text") or "")
        else:
            out.append(run)
    return _order_adjacent_note_runs(out)


def _order_adjacent_note_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    index = 0
    while index < len(runs):
        run = runs[index]
        if run.get("type") != "note_ref":
            out.append(run)
            index += 1
            continue
        group = [run]
        index += 1
        while (
            index < len(runs)
            and runs[index].get("type") == "note_ref"
            and runs[index].get("source_page") == group[0].get("source_page")
        ):
            group.append(runs[index])
            index += 1
        out.extend(
            sorted(
                group,
                key=lambda item: (
                    _inline_marker_sort_value(item.get("marker")),
                    str(item.get("marker") or ""),
                ),
            )
        )
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
    (``equation_inline``, ``equation_interline``, ``trailing_text``).
    Otherwise returns ``None``.
    """
    marker = normalize_note_marker(ref.get("marker", ""))
    if not marker:
        return None
    if marker.startswith("*"):
        return marker
    source = str(ref.get("source") or "")
    if source in {"equation_inline", "equation_interline", "trailing_text"}:
        return f"^{{{marker}}}"
    return None


def _note_refs(block: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Return writable inline refs plus unmatched legacy compatibility refs."""
    raw_attrs = block.get("attrs")
    attrs: Mapping[str, Any] = raw_attrs if isinstance(raw_attrs, dict) else {}
    runs = attrs.get("inline_runs")
    inline_refs = (
        [run for run in runs if isinstance(run, dict) and run.get("type") == "note_ref"]
        if isinstance(runs, list)
        else []
    )
    refs = attrs.get("note_refs")
    legacy_refs = [ref for ref in refs if isinstance(ref, dict)] if isinstance(refs, list) else []
    if not inline_refs:
        return legacy_refs
    if not legacy_refs:
        return inline_refs

    unmatched_legacy = list(legacy_refs)
    for inline_ref in inline_refs:
        match_index = next(
            (
                index
                for index, legacy_ref in enumerate(unmatched_legacy)
                if _same_inline_note_ref(inline_ref, legacy_ref)
            ),
            None,
        )
        if match_index is None:
            continue
        legacy_ref = unmatched_legacy.pop(match_index)
        for key, value in legacy_ref.items():
            if key != "type":
                inline_ref.setdefault(key, value)
    return inline_refs + unmatched_legacy


def _existing_ref_markers(block: CanonicalBlock) -> set[str]:
    return {normalize_note_marker(ref.get("marker", "")) for ref in _note_refs(block)}


def _last_page(block: CanonicalBlock) -> Optional[int]:
    source = block.get("source") or {}
    pages = source.get("pages")
    if isinstance(pages, list) and pages:
        page = pages[-1]
        return int(page) if isinstance(page, int) else None
    page = source.get("page")
    return int(page) if isinstance(page, int) else None
