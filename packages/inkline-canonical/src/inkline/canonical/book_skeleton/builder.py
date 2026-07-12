from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.book_skeleton.contract import BOOK_SKELETON_ENTRY_ROLES
from inkline.canonical.book_skeleton.pages import (
    add_printed_page_offset_candidates,
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
    normalize_title,
    parse_toc_entries,
)
from inkline.canonical.book_skeleton.toc_llm import normalize_llm_toc_entries
from inkline.canonical.book_skeleton.validation import validate_book_skeleton
from inkline.canonical.observed.schema import validate_observed_document


def build_book_skeleton_from_observed(
    document: dict[str, Any],
    *,
    llm_toc_entries: list[dict[str, Any]] | None = None,
    llm_classification: dict[str, Any] | None = None,
    llm_uncertain_entries: list[dict[str, Any]] | None = None,
    llm_model: str | None = None,
    llm_source: str | None = None,
) -> dict[str, Any]:
    validate_observed_document(document)
    records = page_records(document)
    toc_pages = detect_toc_pages(records)
    toc_text = "\n".join(observed_page_text(document, page) for page in toc_pages)
    parsed_entries = parse_toc_entries(toc_text)
    entries_from_llm_toc = llm_toc_entries is not None
    if entries_from_llm_toc:
        entries = normalize_llm_toc_entries(llm_toc_entries)
        _attach_printed_start_pages(entries, parsed_entries)
    else:
        entries = parsed_entries
        infer_toc_levels(entries)
        assign_toc_hierarchy(entries)
    for entry in entries:
        candidates = locate_toc_entry_pages(records, entry, exclude_pages=toc_pages)
        entry["candidate_start_pages"] = candidates
        entry["selected_start_page"] = None
    if entries_from_llm_toc:
        llm_summary = _llm_toc_summary(
            llm_model=llm_model,
            llm_source=llm_source,
            uncertain_entries=llm_uncertain_entries,
        )
    else:
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
    add_printed_page_offset_candidates(entries, page_count=len(records))
    select_monotonic_start_pages(entries)
    prune_candidate_start_pages_to_toc_intervals(entries)
    public_entries = [_public_toc_entry(entry) for entry in entries]
    skeleton = {
        "metadata": metadata(document),
        "toc_pages": toc_pages,
        "toc_entries": public_entries,
        "boundaries": boundaries(public_entries),
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
                "display_title": entry["display_title"],
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
            "toc_entries": [
                {
                    "entry_index": 0,
                    "display_title": "",
                    "level": 1,
                    "parent_entry_index": None,
                    "role": "front_matter|body|back_matter|unknown",
                }
            ],
            "uncertain_entries": [{"entry_index": 0, "display_title": "", "reason": ""}],
        },
    }


def _public_toc_entry(entry: dict[str, Any]) -> dict[str, Any]:
    attrs = deepcopy(entry.get("attrs") or {})
    attrs.pop("label_correction", None)
    return {
        "entry_index": entry["entry_index"],
        "display_title": entry["display_title"],
        "level": entry["level"],
        "parent_entry_index": entry["parent_entry_index"],
        "role": entry["role"],
        "candidate_start_pages": entry["candidate_start_pages"],
        "selected_start_page": entry["selected_start_page"],
        "attrs": attrs,
    }


def _attach_printed_start_pages(
    llm_entries: list[dict[str, Any]], parsed_entries: list[dict[str, Any]]
) -> None:
    remaining_by_title: dict[str, list[dict[str, Any]]] = {}
    for entry in parsed_entries:
        key = normalize_title(str(entry.get("display_title") or ""))
        if key:
            remaining_by_title.setdefault(key, []).append(entry)

    positional_alignment = len(llm_entries) == len(parsed_entries)
    for index, entry in enumerate(llm_entries):
        source = _matching_parsed_entry(
            entry,
            index,
            parsed_entries,
            remaining_by_title,
            allow_positional_fallback=positional_alignment,
        )
        printed_start_page = source.get("printed_start_page") if source else None
        if isinstance(printed_start_page, int):
            entry["printed_start_page"] = printed_start_page


def _matching_parsed_entry(
    entry: dict[str, Any],
    index: int,
    parsed_entries: list[dict[str, Any]],
    remaining_by_title: dict[str, list[dict[str, Any]]],
    *,
    allow_positional_fallback: bool,
) -> dict[str, Any] | None:
    title_key = normalize_title(str(entry.get("display_title") or ""))
    if index < len(parsed_entries):
        indexed = parsed_entries[index]
        if title_key == normalize_title(str(indexed.get("display_title") or "")):
            candidates = remaining_by_title.get(title_key) or []
            if indexed in candidates:
                candidates.remove(indexed)
            return indexed
        if allow_positional_fallback:
            return indexed
    candidates = remaining_by_title.get(title_key) or []
    return candidates.pop(0) if candidates else None


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


def _llm_toc_summary(
    *,
    llm_model: str | None,
    llm_source: str | None,
    uncertain_entries: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    return {
        "used": True,
        "model": llm_model,
        "source": llm_source,
        "uncertain_entries": deepcopy(uncertain_entries or []),
    }


def _first_matching_entry_index(entries: list[dict[str, Any]], predicate) -> int | None:
    for entry in entries:
        if predicate(entry):
            return int(entry["entry_index"])
    return None
