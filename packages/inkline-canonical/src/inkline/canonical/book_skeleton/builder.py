from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from inkline.canonical.book_skeleton.contract import BOOK_SKELETON_ENTRY_ROLES
from inkline.canonical.book_skeleton.pages import (
    boundaries,
    detect_toc_pages,
    locate_toc_entry_pages,
    metadata,
    observed_page_text,
    page_records,
    prune_candidate_start_pages_to_toc_intervals,
    select_monotonic_start_pages,
)
from inkline.canonical.book_skeleton.toc import (
    apply_role_level_guardrails,
    apply_structural_role_guardrails,
    assign_toc_hierarchy,
    infer_toc_levels,
    looks_like_body_toc_entry,
    parse_toc_entries,
)
from inkline.canonical.book_skeleton.validation import validate_book_skeleton
from inkline.canonical.observed.schema import validate_observed_document


def build_book_skeleton_from_observed(
    document: dict[str, Any],
    *,
    llm_classification: dict[str, Any] | None = None,
    llm_model: str | None = None,
    llm_source: str | None = None,
) -> dict[str, Any]:
    validate_observed_document(document)
    records = page_records(document)
    toc_pages = detect_toc_pages(records)
    toc_text = "\n".join(observed_page_text(document, page) for page in toc_pages)
    entries = parse_toc_entries(toc_text)
    infer_toc_levels(entries)
    assign_toc_hierarchy(entries)
    for entry in entries:
        candidates = locate_toc_entry_pages(records, entry, exclude_pages=toc_pages)
        entry["candidate_start_pages"] = candidates
        entry["selected_start_page"] = None
    _apply_structural_roles(entries)
    llm_summary = _apply_llm_classification(
        entries,
        llm_classification=llm_classification,
        llm_model=llm_model,
        llm_source=llm_source,
    )
    apply_role_level_guardrails(entries)
    assign_toc_hierarchy(entries)
    select_monotonic_start_pages(entries)
    prune_candidate_start_pages_to_toc_intervals(entries)
    skeleton = {
        "metadata": metadata(document),
        "toc_pages": toc_pages,
        "toc_entries": entries,
        "boundaries": boundaries(entries),
        "llm": llm_summary,
    }
    validate_book_skeleton(skeleton)
    return skeleton


def build_book_skeleton_toc_llm_input(document: dict[str, Any]) -> dict[str, Any]:
    validate_observed_document(document)
    records = page_records(document)
    toc_pages = detect_toc_pages(records)
    toc_text = "\n".join(observed_page_text(document, page) for page in toc_pages)
    entries = parse_toc_entries(toc_text)
    infer_toc_levels(entries)
    assign_toc_hierarchy(entries)
    toc_entries = []
    for entry in entries:
        toc_entries.append(
            {
                "entry_index": entry["entry_index"],
                "title": entry["title"],
                "display_title": entry["display_title"],
                "raw_label": entry["raw_label"],
                "label": entry["label"],
                "level": entry["level"],
                "parent_entry_index": entry["parent_entry_index"],
                "candidate_start_pages": locate_toc_entry_pages(
                    records, entry, exclude_pages=toc_pages
                )[:5],
            }
        )
    return {
        "mode": "toc_llm",
        "metadata": metadata(document),
        "page_count": len(document["pages"]),
        "toc_pages": toc_pages,
        "toc_entries": toc_entries,
        "expected_output": {
            "entry_roles": [
                {"entry_index": 0, "role": "front_matter|body|back_matter|unknown"}
            ],
            "first_body_entry_index": 0,
            "last_body_entry_index": 0,
            "first_back_matter_entry_index": None,
            "uncertain_entries": [{"entry_index": 0, "title": "", "reason": ""}],
        },
    }


def book_skeleton_toc_llm_prompt(input_data: dict[str, Any]) -> str:
    return (
        "You classify a book skeleton from table-of-contents entries.\n"
        "Use entry_index, display_title, label, level, and title to decide entry roles. "
        "Do not infer or output physical "
        "PDF page numbers; candidate_start_pages are rule-layer evidence only.\n\n"
        "Definitions:\n"
        "- front_matter: content before the main body, such as foreword, preface, acknowledgements, "
        "dedication, editorial notes, or introductory front matter.\n"
        "- body: the main chapters and conclusion of the book.\n"
        "- back_matter: content after the main body, including appendix, notes, bibliography, "
        "references, further reading, chronology, index, publisher afterword, and copyright pages.\n\n"
        "Return strict JSON matching expected_output. Every toc_entries item should have one "
        "entry_roles item. Use null when there is no back matter.\n\n"
        f"Input JSON:\n{_json_dumps(input_data)}"
    )


def _apply_structural_roles(entries: list[dict[str, Any]]) -> None:
    first_body_index = _first_matching_entry_index(
        entries, looks_like_body_toc_entry
    )
    if first_body_index is None:
        return
    for entry in entries[:first_body_index]:
        entry["role"] = "front_matter"
    for entry in entries[first_body_index:]:
        entry["role"] = "body"


def _apply_llm_classification(
    entries: list[dict[str, Any]],
    *,
    llm_classification: dict[str, Any] | None,
    llm_model: str | None,
    llm_source: str | None,
) -> dict[str, Any]:
    if llm_classification is None:
        return {"used": False, "model": None, "source": None, "uncertain_entries": []}
    entries_by_index = {entry["entry_index"]: entry for entry in entries}
    for item in llm_classification.get("entry_roles") or []:
        if not isinstance(item, dict):
            continue
        index = item.get("entry_index")
        role = item.get("role")
        if not isinstance(index, int) or role not in BOOK_SKELETON_ENTRY_ROLES:
            continue
        if index in entries_by_index:
            entries_by_index[index]["role"] = role
    apply_structural_role_guardrails(entries)
    return {
        "used": True,
        "model": llm_model,
        "source": llm_source,
        "uncertain_entries": deepcopy(llm_classification.get("uncertain_entries") or []),
    }


def _first_matching_entry_index(entries: list[dict[str, Any]], predicate) -> int | None:
    for entry in entries:
        if predicate(entry):
            return int(entry["entry_index"])
    return None


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
