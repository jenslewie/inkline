"""Select only page-role candidates that need semantic visual review."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.observed.schema import validate_observed_document

_DETERMINISTIC_FRONT_ACTIONS = {
    "blank_page": ("exclude", "not_needed"),
    "toc_page": ("metadata_only", "not_needed"),
}
_VISUAL_REVIEW_ROLES = {"visual_page", "back_cover_candidate"}
_VISUAL_OBSERVATION_KINDS = {"image_region", "table_region"}


def build_page_review_plan(
    document: dict[str, Any],
    skeleton: dict[str, Any],
    page_role_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an internal review plan without using page text semantics."""

    validate_observed_document(document)
    first_body_page = _first_body_page(skeleton)
    toc_pages = _toc_pages(skeleton)
    visual_pages = _visual_observation_pages(document)
    roles_by_page = {int(record["page"]): record for record in page_role_records}
    records = []
    for page in sorted(int(item["page"]) for item in document["pages"]):
        role_record = roles_by_page.get(page, {})
        record = _page_review_record(
            page,
            role_record,
            first_body_page,
            page in toc_pages,
            page in visual_pages,
        )
        records.append(record)
    _promote_front_section_continuations(records, skeleton, first_body_page)
    candidate_pages = [
        int(record["page"])
        for record in records
        if record["llm_review_status"] == "pending"
    ]
    return {
        "metadata": {
            "schema_name": "inkline_page_review",
            "schema_version": "0.1-shadow",
            "doc_id": str(document["metadata"].get("doc_id") or ""),
            "title": str(document["metadata"].get("title") or ""),
        },
        "first_body_page": first_body_page,
        "candidate_pages": candidate_pages,
        "pages": records,
    }


def _first_body_page(skeleton: dict[str, Any]) -> int | None:
    boundaries = skeleton.get("boundaries")
    if not isinstance(boundaries, dict):
        return None
    value = boundaries.get("first_body_page")
    return value if isinstance(value, int) and value > 0 else None


def _toc_pages(skeleton: dict[str, Any]) -> set[int]:
    return {
        page
        for page in skeleton.get("toc_pages") or []
        if isinstance(page, int) and page > 0
    }


def _visual_observation_pages(document: dict[str, Any]) -> set[int]:
    return {
        int(observation["page"])
        for observation in document.get("observations") or []
        if isinstance(observation, dict)
        and observation.get("kind") in _VISUAL_OBSERVATION_KINDS
        and isinstance(observation.get("page"), int)
    }


def _page_review_record(
    page: int,
    role_record: dict[str, Any],
    first_body_page: int | None,
    is_toc_page: bool,
    has_visual_observation: bool,
) -> dict[str, Any]:
    page_role = str(role_record.get("page_role") or "unknown")
    signals = list(role_record.get("signals") or [])
    is_front_matter = first_body_page is not None and page < first_body_page
    if is_toc_page:
        page_role = "toc_page"
        actions = _DETERMINISTIC_FRONT_ACTIONS["toc_page"]
        status = "deterministic"
    else:
        actions = _deterministic_actions(page_role, signals, is_front_matter)
        if has_visual_observation or actions is None:
            actions = ("needs_review", "needs_review")
            status = "pending"
        else:
            status = "deterministic" if page_role == "blank_page" else "not_selected"
    source = "layout_and_skeleton" if status != "pending" else "llm_page_review"
    return {
        "page": page,
        "page_role": page_role,
        "text_flow_action": actions[0],
        "visual_asset_action": actions[1],
        "decision_source": source,
        "llm_review_status": status,
        "is_front_matter_candidate": is_front_matter,
        "signals": deepcopy(signals),
    }


def _deterministic_actions(
    page_role: str,
    signals: list[Any],
    is_front_matter: bool,
) -> tuple[str, str] | None:
    if is_front_matter and page_role in _DETERMINISTIC_FRONT_ACTIONS:
        return _DETERMINISTIC_FRONT_ACTIONS[page_role]
    if is_front_matter and page_role == "text_flow_page" and "visual_verifier_candidate" not in signals:
        return ("include", "not_needed")
    if not is_front_matter and page_role == "text_flow_page" and "visual_verifier_candidate" not in signals:
        return ("include", "not_needed")
    if not is_front_matter and page_role not in _VISUAL_REVIEW_ROLES:
        return ("include", "not_needed")
    return None


def _promote_front_section_continuations(
    records: list[dict[str, Any]],
    skeleton: dict[str, Any],
    first_body_page: int | None,
) -> None:
    if first_body_page is None:
        return
    records_by_page = {int(record["page"]): record for record in records}
    section_starts = _section_starts(skeleton)
    for index, (start_page, role) in enumerate(section_starts):
        if role != "front_matter" or start_page >= first_body_page:
            continue
        end_page = (
            section_starts[index + 1][0] - 1
            if index + 1 < len(section_starts)
            else first_body_page - 1
        )
        section_records = [
            records_by_page[page]
            for page in range(start_page, min(end_page, first_body_page - 1) + 1)
            if page in records_by_page
        ]
        if not any(record["llm_review_status"] == "pending" for record in section_records):
            continue
        for record in section_records:
            if record["llm_review_status"] != "not_selected":
                continue
            record["text_flow_action"] = "needs_review"
            record["visual_asset_action"] = "needs_review"
            record["decision_source"] = "llm_page_review"
            record["llm_review_status"] = "pending"
            record["signals"].append("section_visual_continuity")


def _section_starts(skeleton: dict[str, Any]) -> list[tuple[int, str]]:
    starts = []
    for entry in skeleton.get("toc_entries") or []:
        if not isinstance(entry, dict):
            continue
        page = entry.get("selected_start_page")
        role = entry.get("role")
        if isinstance(page, int) and page > 0 and isinstance(role, str):
            starts.append((page, role))
    return sorted(starts)
