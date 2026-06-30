"""Inline run and note-ref partition helpers for display/body splits."""

from __future__ import annotations

from typing import Any, Dict, List

from ..notes.keys import note_ref_key as _note_ref_key


def set_partitioned_inline_attrs(
    attrs: Dict[str, Any],
    runs: List[Dict[str, Any]],
    refs: List[Dict[str, Any]] | None,
) -> None:
    if runs:
        attrs["inline_runs"] = runs
    else:
        attrs.pop("inline_runs", None)
    if refs is not None:
        if refs:
            attrs["note_refs"] = refs
        else:
            attrs.pop("note_refs", None)


def split_inline_runs_at_offset(
    runs: Any, split_offset: int
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split inline runs at a character offset in the block text."""
    if not isinstance(runs, list):
        return [], []
    text_char_offset = 0
    split_run_index = -1
    split_char_index = 0
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or run.get("type") != "text":
            continue
        text = str(run.get("text", ""))
        next_offset = text_char_offset + len(text)
        if text_char_offset <= split_offset <= next_offset:
            split_run_index = index
            split_char_index = split_offset - text_char_offset
            break
        text_char_offset = next_offset

    if split_run_index < 0:
        return [], []

    display_runs: List[Dict[str, Any]] = []
    body_runs: List[Dict[str, Any]] = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        copied = dict(run)
        if index < split_run_index:
            display_runs.append(copied)
        elif index > split_run_index:
            body_runs.append(copied)
        else:
            text = str(copied.get("text", ""))
            before = text[:split_char_index].rstrip()
            after = text[split_char_index:].lstrip()
            if before:
                display_runs.append({"type": "text", "text": before})
            if after:
                body_runs.append({"type": "text", "text": after})
    return display_runs, body_runs


def split_note_refs_by_runs(
    refs: Any,
    display_block_runs: List[Dict[str, Any]],
    body_runs: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]] | None, List[Dict[str, Any]] | None]:
    """Partition note refs to match the side they belong to."""
    if not isinstance(refs, list):
        return None, None
    buckets: Dict[tuple[str, str, int | None], List[Dict[str, Any]]] = {}
    for ref in refs:
        if isinstance(ref, dict):
            buckets.setdefault(_note_ref_key(ref), []).append(ref)
    return _refs_for_runs(display_block_runs, buckets), _refs_for_runs(body_runs, buckets)


def _refs_for_runs(
    runs: List[Dict[str, Any]],
    buckets: Dict[tuple[str, str, int | None], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for run in runs:
        if run.get("type") != "note_ref":
            continue
        matches = buckets.get(_note_ref_key(run)) or []
        if matches:
            out.append(matches.pop(0))
    return out
