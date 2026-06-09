"""Block merge logic. Contains _merge_block_pair() which joins two canonical blocks (text, source spans, bbox, note_refs, inline_runs, provenance), plus _merge_inline_runs() and _refresh_canonical_quote_attrs(). The core mutation point used by cross-page, display quote, and footnote merging."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..canonical.builders import union_bbox
from ..schema.patterns import CHINESE_RE

QUOTE_TYPES = {"blockquote", "epigraph"}
TERMINAL_PUNCT = set("。？！!?；;：:.”’\"'）】》」』")


def _merge_block_pair(
    left: Dict[str, Any],
    right: Dict[str, Any],
    reason: str,
    evidence: Dict[str, Any],
    interruptions: List[Dict[str, Any]],
    joiner: Optional[str] = None,
) -> None:
    original_left_text = left.get("text", "") or ""
    original_right_text = right.get("text", "") or ""
    if joiner == "newline" and original_left_text.strip() and original_right_text.strip():
        left["text"] = original_left_text.rstrip() + "\n" + original_right_text.lstrip()
    else:
        left["text"] = _join_text(original_left_text, original_right_text)
    left_was_quote = left.get("type") in QUOTE_TYPES
    right_was_quote = right.get("type") in QUOTE_TYPES
    if right_was_quote and not left_was_quote:
        left["type"] = right.get("type")
        for k, v in (right.get("attrs") or {}).items():
            if k in {"role", "content_form", "content_form_confidence", "content_form_scores", "classification_evidence", "quote_text", "attribution", "raw_types"}:
                left.setdefault("attrs", {})[k] = v
    lsrc = left.setdefault("source", {})
    rsrc = right.get("source", {})
    lpages = set(lsrc.get("pages") or ([lsrc.get("page")] if lsrc.get("page") is not None else []))
    for p in rsrc.get("pages") or ([rsrc.get("page")] if rsrc.get("page") is not None else []):
        if p is not None:
            lpages.add(p)
    if lpages:
        lsrc["pages"] = sorted(lpages)
    spans = lsrc.setdefault("spans", [])
    if not spans:
        spans.append({"page": lsrc.get("page"), "bbox": lsrc.get("bbox"), "block_id": left.get("block_id")})
    spans.append({"page": rsrc.get("page"), "bbox": rsrc.get("bbox"), "block_id": right.get("block_id")})
    if interruptions:
        ints = lsrc.setdefault("interruption_spans", [])
        ints.extend(interruptions)
    lsrc["bbox"] = union_bbox([lsrc.get("bbox"), rsrc.get("bbox")])
    attrs = left.setdefault("attrs", {})
    merged = attrs.setdefault("merged_from", [])
    if left.get("block_id") not in merged:
        merged.append(left.get("block_id"))
    right_merged = (right.get("attrs") or {}).get("merged_from") or []
    for rb in [right.get("block_id")] + list(right_merged):
        if rb is not None and rb not in merged:
            merged.append(rb)
    attrs["merge_reason"] = reason
    if evidence:
        attrs["merge_evidence"] = evidence
    if interruptions:
        attrs["interrupted_by"] = [x.get("block_id") for x in interruptions]
    refs = attrs.setdefault("note_refs", [])
    for ref in (right.get("attrs") or {}).get("note_refs", []):
        if ref not in refs:
            refs.append(ref)
    _merge_inline_runs(left, right, original_left_text, original_right_text)
    if left.get("type") in QUOTE_TYPES:
        _refresh_canonical_quote_attrs(left)


def _merge_inline_runs(
    left: Dict[str, Any],
    right: Dict[str, Any],
    original_left_text: str,
    original_right_text: str,
) -> None:
    left_attrs = left.setdefault("attrs", {})
    right_attrs = right.get("attrs") or {}
    left_runs = left_attrs.get("inline_runs")
    right_runs = right_attrs.get("inline_runs")
    if not isinstance(left_runs, list) and not isinstance(right_runs, list):
        return

    left_side = _runs_or_text(left_runs, original_left_text)
    right_side = _runs_or_text(right_runs, original_right_text)
    separator = _inline_join_separator(str(left.get("text") or ""), original_left_text, original_right_text)
    if left_side:
        _trim_last_text_run_right(left_side)
    if right_side:
        _trim_first_text_run_left(right_side)

    merged_runs: List[Dict[str, Any]] = []
    for run in left_side:
        _append_inline_run(merged_runs, run)
    if separator:
        _append_inline_run(merged_runs, {"type": "text", "text": separator})
    for run in right_side:
        _append_inline_run(merged_runs, run)
    if any(run.get("type") == "note_ref" for run in merged_runs):
        left_attrs["inline_runs"] = merged_runs


def _runs_or_text(runs: Any, fallback_text: str) -> List[Dict[str, Any]]:
    if isinstance(runs, list):
        return [dict(run) for run in runs if isinstance(run, dict)]
    return [{"type": "text", "text": fallback_text}] if fallback_text else []


def _append_inline_run(runs: List[Dict[str, Any]], run: Dict[str, Any]) -> None:
    if run.get("type") != "text":
        runs.append(run)
        return
    text = str(run.get("text", ""))
    if not text:
        return
    if runs and runs[-1].get("type") == "text":
        runs[-1]["text"] = str(runs[-1].get("text", "")) + text
    else:
        runs.append({"type": "text", "text": text})


def _inline_join_separator(joined_text: str, left_text: str, right_text: str) -> str:
    left = (left_text or "").rstrip()
    right = (right_text or "").lstrip()
    if joined_text == left + "\n" + right:
        return "\n"
    if joined_text == left + " " + right:
        return " "
    return ""


def _trim_last_text_run_right(runs: List[Dict[str, Any]]) -> None:
    for run in reversed(runs):
        if run.get("type") == "text":
            run["text"] = str(run.get("text", "")).rstrip()
            return


def _trim_first_text_run_left(runs: List[Dict[str, Any]]) -> None:
    for run in runs:
        if run.get("type") == "text":
            run["text"] = str(run.get("text", "")).lstrip()
            return


def _join_text(left: str, right: str) -> str:
    left = (left or "").rstrip()
    right = (right or "").lstrip()
    if not left:
        return right
    if not right:
        return left
    if CHINESE_RE.search(left[-1]) or CHINESE_RE.search(right[0]) or left[-1] in "，、；：（《“‘—-":
        return left + right
    return left + " " + right


def _refresh_canonical_quote_attrs(
    b: Dict[str, Any],
    prev_text: str = "",
    role: str = "inline_display_quote",
) -> None:
    lines = [ln.strip() for ln in str(b.get("text", "")).split("\n") if ln.strip()]
    attrs = b.setdefault("attrs", {})
    existing_note_refs = list(attrs.get("note_refs", []))
    existing_raw_types = attrs.get("raw_types")
    for k in ["content_form", "content_form_confidence", "content_form_scores", "classification_evidence", "attribution"]:
        attrs.pop(k, None)
    attrs.update({
        "role": attrs.get("role", role),
        "quote_text": "\n".join(lines).strip(),
    })
    if existing_note_refs:
        attrs["note_refs"] = existing_note_refs
    if existing_raw_types is not None:
        attrs["raw_types"] = existing_raw_types
    if b.get("type") not in QUOTE_TYPES:
        b["type"] = "blockquote"
