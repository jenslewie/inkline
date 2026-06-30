"""Block merge logic for text-like canonical blocks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..normalize.builders import union_bbox
from ..schema.block_types import DISPLAY_BLOCK
from ..schema.patterns import CHINESE_RE

DISPLAY_BLOCK_TYPES = {DISPLAY_BLOCK}
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
    left["text"] = _merged_pair_text(original_left_text, original_right_text, joiner)
    _promote_display_attrs(left, right)
    _merge_pair_source(left, right, original_left_text, original_right_text, interruptions)
    attrs = _merge_pair_attrs(left, right, reason, evidence, interruptions)
    _merge_right_note_refs(attrs, right)
    _merge_inline_runs(left, right, original_left_text, original_right_text)
    if left.get("type") == DISPLAY_BLOCK:
        _refresh_display_block_attrs(left)


def _merged_pair_text(left_text: str, right_text: str, joiner: Optional[str]) -> str:
    if joiner == "newline" and left_text.strip() and right_text.strip():
        return left_text.rstrip() + "\n" + right_text.lstrip()
    return _join_text(left_text, right_text)


def _promote_display_attrs(left: Dict[str, Any], right: Dict[str, Any]) -> None:
    if right.get("type") not in DISPLAY_BLOCK_TYPES or left.get("type") in DISPLAY_BLOCK_TYPES:
        return
    left["type"] = DISPLAY_BLOCK
    left_attrs = left.setdefault("attrs", {})
    for key, value in (right.get("attrs") or {}).items():
        if key in _DISPLAY_ATTRS_TO_PROMOTE:
            left_attrs[key] = value


_DISPLAY_ATTRS_TO_PROMOTE = {
    "layout_role",
    "layout_form",
    "line_count",
    "has_attribution_line",
    "line_layouts",
    "raw_types",
}


def _merge_pair_source(
    left: Dict[str, Any],
    right: Dict[str, Any],
    original_left_text: str,
    original_right_text: str,
    interruptions: List[Dict[str, Any]],
) -> None:
    left_source = left.setdefault("source", {})
    right_source = right.get("source", {})
    _merge_source_pages(left_source, right_source)
    _merge_source_spans(
        left, right, left_source, right_source, original_left_text, original_right_text
    )
    if interruptions:
        left_source.setdefault("interruption_spans", []).extend(interruptions)
    left_source["bbox"] = union_bbox([left_source.get("bbox"), right_source.get("bbox")])


def _merge_source_pages(left_source: Dict[str, Any], right_source: Dict[str, Any]) -> None:
    pages = set(_source_pages(left_source))
    pages.update(_source_pages(right_source))
    if pages:
        left_source["pages"] = sorted(pages)


def _source_pages(source: Dict[str, Any]) -> List[Any]:
    pages = source.get("pages")
    if pages:
        return [page for page in pages if page is not None]
    page = source.get("page")
    return [page] if page is not None else []


def _merge_source_spans(
    left: Dict[str, Any],
    right: Dict[str, Any],
    left_source: Dict[str, Any],
    right_source: Dict[str, Any],
    original_left_text: str,
    original_right_text: str,
) -> None:
    spans = left_source.setdefault("spans", [])
    if not spans:
        spans.append(_source_span(left, left_source, original_left_text))
    right_spans = [span for span in right_source.get("spans") or [] if isinstance(span, dict)]
    if right_spans:
        spans.extend(dict(span) for span in right_spans)
        return
    spans.append(_source_span(right, right_source, original_right_text))


def _source_span(block: Dict[str, Any], source: Dict[str, Any], text: str) -> Dict[str, Any]:
    return {
        "page": source.get("page"),
        "bbox": source.get("bbox"),
        "block_id": block.get("block_id"),
        "text": text,
    }


def _merge_pair_attrs(
    left: Dict[str, Any],
    right: Dict[str, Any],
    reason: str,
    evidence: Dict[str, Any],
    interruptions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    attrs = left.setdefault("attrs", {})
    merged = attrs.setdefault("merged_from", [])
    _append_unique(merged, left.get("block_id"))
    right_merged = (right.get("attrs") or {}).get("merged_from") or []
    for block_id in [right.get("block_id"), *list(right_merged)]:
        _append_unique(merged, block_id)
    attrs["merge_reason"] = reason
    if evidence:
        attrs["merge_evidence"] = evidence
    if interruptions:
        attrs["interrupted_by"] = [item.get("block_id") for item in interruptions]
    return attrs


def _append_unique(values: List[Any], value: Any) -> None:
    if value is not None and value not in values:
        values.append(value)


def _merge_right_note_refs(attrs: Dict[str, Any], right: Dict[str, Any]) -> None:
    right_refs = (right.get("attrs") or {}).get("note_refs")
    if not isinstance(right_refs, list) or not right_refs:
        return
    refs = attrs.setdefault("note_refs", [])
    for ref in right_refs:
        _append_unique(refs, ref)


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
    separator = _inline_join_separator(
        str(left.get("text") or ""), original_left_text, original_right_text
    )
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


def _refresh_display_block_attrs(
    b: Dict[str, Any],
    prev_text: str = "",
    layout_role: str = "inline_display_block",
) -> None:
    lines = [ln.strip() for ln in str(b.get("text", "")).split("\n") if ln.strip()]
    attrs = b.setdefault("attrs", {})
    existing_note_refs = list(attrs.get("note_refs", []))
    existing_raw_types = attrs.get("raw_types")
    for k in [
        "role",
        "content_form",
        "content_form_confidence",
        "content_form_scores",
        "classification_evidence",
        "quote_text",
        "attribution",
    ]:
        attrs.pop(k, None)
    attrs["layout_role"] = attrs.get("layout_role", layout_role)
    attrs["line_count"] = len(lines)
    if existing_note_refs:
        attrs["note_refs"] = existing_note_refs
    if existing_raw_types is not None:
        attrs["raw_types"] = existing_raw_types
    if attrs.get("merge_reason") == "cross_page_paragraph_continuation_across_footnote":
        attrs["merge_reason"] = "display_block_continuation_across_footnotes"
        attrs["merge_evidence"] = {"footnote_interrupted_display_block": True}
    b["type"] = DISPLAY_BLOCK
