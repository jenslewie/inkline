"""Note reference gap detection report. Counts footnote/endnote definitions in canonical output that lack a corresponding body note_ref, listing them per page. Used to identify where PDF image/OCR-based inline marker recovery is needed."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from ..extraction.text import normalize_note_marker, normalize_ws

__all__ = ["build_note_ref_gap_report", "note_ref_gap_report_path", "write_note_ref_gap_report"]


def note_ref_gap_report_path(canonical_path: Path) -> Path:
    stem = canonical_path.stem
    if "_canonical_" in stem:
        report_stem = stem.replace("_canonical_", "_note_ref_gaps_", 1)
    elif stem.endswith("_canonical"):
        report_stem = stem[: -len("_canonical")] + "_note_ref_gaps"
    else:
        report_stem = stem + "_note_ref_gaps"
    return canonical_path.with_name(report_stem + ".json")


def build_note_ref_gap_report(document: Dict[str, Any], *, canonical_path: Optional[Path] = None) -> Dict[str, Any]:
    blocks = [block for block in document.get("blocks") or [] if isinstance(block, dict)]
    referenced_note_ids = _referenced_note_ids(blocks)
    missing_notes = [
        _missing_note_entry(block)
        for block in blocks
        if _is_independent_note_without_body_ref(block, referenced_note_ids)
    ]
    missing_notes = [entry for entry in missing_notes if entry is not None]
    unresolved_refs = _unresolved_body_note_refs(blocks)
    independent_notes = [block for block in blocks if _is_independent_note(block)]
    referenced_notes = [block for block in independent_notes if _has_body_ref(block, referenced_note_ids)]

    metadata = _dict_value(document.get("metadata"))
    report: Dict[str, Any] = {
        "canonical": canonical_path.name if canonical_path else None,
        "doc_id": metadata.get("doc_id"),
        "title": metadata.get("title"),
        "summary": {
            "footnote_blocks": sum(1 for block in blocks if block.get("type") == "footnote"),
            "note_definition_blocks": len(independent_notes),
            "independent_notes": len(independent_notes),
            "referenced_notes": len(referenced_notes),
            "missing_body_ref_notes": len(missing_notes),
            "missing_body_ref_notes_with_marker": sum(1 for item in missing_notes if item.get("note_marker")),
            "missing_body_ref_notes_without_marker": sum(1 for item in missing_notes if not item.get("note_marker")),
            "unresolved_body_note_refs": len(unresolved_refs),
        },
        "missing_by_page": _missing_by_page(missing_notes),
        "missing_body_ref_notes": missing_notes,
        "unresolved_body_note_refs": unresolved_refs,
    }
    return report


def write_note_ref_gap_report(document: Dict[str, Any], canonical_path: Path) -> tuple[Path, Dict[str, Any]]:
    report_path = note_ref_gap_report_path(canonical_path)
    report = build_note_ref_gap_report(document, canonical_path=canonical_path)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report_path, report


def _is_independent_note(block: Dict[str, Any]) -> bool:
    attrs = _dict_value(block.get("attrs"))
    return bool(attrs.get("note_id"))


def _referenced_by(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    attrs = _dict_value(block.get("attrs"))
    refs = attrs.get("referenced_by")
    return refs if isinstance(refs, list) else []


def _is_independent_note_without_body_ref(block: Dict[str, Any], referenced_note_ids: set[str]) -> bool:
    return _is_independent_note(block) and not _has_body_ref(block, referenced_note_ids)


def _has_body_ref(block: Dict[str, Any], referenced_note_ids: set[str]) -> bool:
    attrs = _dict_value(block.get("attrs"))
    note_id = str(attrs.get("note_id") or "")
    return bool(_referenced_by(block)) or bool(note_id and note_id in referenced_note_ids)


def _referenced_note_ids(blocks: List[Dict[str, Any]]) -> set[str]:
    note_ids: set[str] = set()
    for block in blocks:
        if _is_independent_note(block):
            continue
        for ref in _body_note_refs(block):
            if isinstance(ref, dict) and ref.get("target_note_id"):
                note_ids.add(str(ref["target_note_id"]))
    return note_ids


def _missing_note_entry(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    attrs = _dict_value(block.get("attrs"))
    source = _dict_value(block.get("source"))
    note_id = attrs.get("note_id")
    if not note_id:
        return None
    text = str(block.get("text") or "")
    return {
        "block_id": block.get("block_id"),
        "type": block.get("type"),
        "page": source.get("page"),
        "pages": source.get("pages"),
        "bbox": source.get("bbox"),
        "note_id": note_id,
        "note_marker": attrs.get("note_marker"),
        "note_strategy": attrs.get("note_strategy"),
        "role": attrs.get("role"),
        "raw_type": attrs.get("raw_type"),
        "text_preview": _preview(text),
        "text": text,
    }


def _missing_by_page(missing_notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Counter[str] = Counter()
    with_marker: Counter[str] = Counter()
    without_marker: Counter[str] = Counter()
    for item in missing_notes:
        page_key = str(item.get("page") if item.get("page") is not None else "unknown")
        counts[page_key] += 1
        if item.get("note_marker"):
            with_marker[page_key] += 1
        else:
            without_marker[page_key] += 1

    def sort_key(page: str) -> tuple[int, str]:
        try:
            return (0, f"{int(page):08d}")
        except ValueError:
            return (1, page)

    return [
        {
            "page": int(page) if page.isdigit() else page,
            "missing_body_ref_notes": counts[page],
            "with_marker": with_marker[page],
            "without_marker": without_marker[page],
        }
        for page in sorted(counts, key=sort_key)
    ]


def _unresolved_body_note_refs(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for block in blocks:
        if _is_independent_note(block):
            continue
        for ref in _body_note_refs(block):
            if not isinstance(ref, dict) or ref.get("target_note_id"):
                continue
            out.append(_body_ref_entry(block, ref))
    return out


def _body_note_refs(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    attrs = _dict_value(block.get("attrs"))
    runs = attrs.get("inline_runs")
    inline_refs = [
        run
        for run in runs
        if isinstance(run, dict) and run.get("type") == "note_ref"
    ] if isinstance(runs, list) else []
    if inline_refs:
        return inline_refs
    refs = attrs.get("note_refs")
    return [ref for ref in refs if isinstance(ref, dict)] if isinstance(refs, list) else []


def _body_ref_entry(block: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    source = _dict_value(block.get("source"))
    text = str(block.get("text") or "")
    return {
        "ref_block_id": block.get("block_id"),
        "page": source.get("page"),
        "pages": source.get("pages"),
        "marker": normalize_note_marker(str(ref.get("marker") or "")),
        "source": ref.get("source"),
        "source_page": ref.get("source_page"),
        "target_note_id": ref.get("target_note_id"),
        "target_block_id": ref.get("target_block_id"),
        "text_preview": _preview(text),
    }


def _preview(text: str, limit: int = 180) -> str:
    text = normalize_ws(text)
    return text if len(text) <= limit else text[:limit] + "..."


def _dict_value(value: Any) -> Dict[str, Any]:
    return cast(Dict[str, Any], value) if isinstance(value, dict) else {}
