"""Select only page-role candidates that need semantic visual review."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.observed.schema import validate_observed_document
from inkline.canonical.page_review.resolution import PAGE_REVIEW_SCHEMA_VERSION

_DETERMINISTIC_SPECIAL_PAGE_ACTIONS = {
    "blank_page": ("exclude", "not_needed"),
    "toc_page": ("metadata_only", "not_needed"),
}
_VISUAL_OBSERVATION_KINDS = {"image_region", "table_region"}
_VISUAL_LAYOUT_ROLES = {
    "blank_page",
    "cover_page",
    "front_visual_page",
    "visual_page",
    "back_cover_candidate",
    "title_like_page",
}
_LAYOUT_SPECIAL_PAGE_KINDS = {
    "blank_page": "blank_page",
    "cover_page": "cover_page",
}
_RASTER_VISUAL_SIGNALS = {"raster_dark_visual_layout"}


def build_page_review_plan(
    document: dict[str, Any],
    skeleton: dict[str, Any],
    page_role_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an internal review plan without using page text semantics."""

    validate_observed_document(document)
    first_body_page = _first_body_page(skeleton)
    first_back_matter_page = _first_back_matter_page(skeleton)
    first_front_matter_page = _first_front_matter_page(skeleton, first_body_page)
    body_section_starts = _body_section_start_pages(skeleton)
    toc_pages = _toc_pages(skeleton)
    visual_kinds_by_page = _visual_observation_kinds(document)
    roles_by_page = {int(record["page"]): record for record in page_role_records}
    records = []
    for page in sorted(int(item["page"]) for item in document["pages"]):
        role_record = roles_by_page.get(page, {})
        record = _page_review_record(
            page,
            role_record,
            first_front_matter_page,
            first_body_page,
            first_back_matter_page,
            page in body_section_starts,
            page in toc_pages,
            visual_kinds_by_page.get(page, []),
        )
        records.append(record)
    _defer_non_pre_body_reviews(records)
    candidate_pages = [
        int(record["page"])
        for record in records
        if record["llm_review_status"] == "pending"
    ]
    return {
        "metadata": {
            "schema_name": "inkline_page_review",
            "schema_version": PAGE_REVIEW_SCHEMA_VERSION,
            "doc_id": str(document["metadata"].get("doc_id") or ""),
            "title": str(document["metadata"].get("title") or ""),
        },
        "first_body_page": first_body_page,
        "candidate_pages": candidate_pages,
        "pages": records,
    }


def _defer_non_pre_body_reviews(records: list[dict[str, Any]]) -> None:
    """Keep body and back-matter layout ambiguity out of the Phase 4A LLM scope."""

    for record in records:
        context = record.get("skeleton_context")
        matter = context.get("matter") if isinstance(context, dict) else None
        if matter == "pre_body" or record.get("llm_review_status") != "pending":
            continue
        record["text_flow_action"], record["visual_asset_action"] = _layout_actions(
            str(record["page_role"])
        )
        record["decision_source"] = "layout_and_skeleton"
        record["llm_review_status"] = "not_selected"


def _layout_actions(page_role: str) -> tuple[str, str]:
    if page_role == "visual_page":
        return ("exclude", "retain")
    return ("include", "not_needed")


def _first_body_page(skeleton: dict[str, Any]) -> int | None:
    return _boundary_page(skeleton, "first_body_page")


def _first_back_matter_page(skeleton: dict[str, Any]) -> int | None:
    return _boundary_page(skeleton, "first_back_matter_page")


def _first_front_matter_page(
    skeleton: dict[str, Any], first_body_page: int | None
) -> int | None:
    """Return the earliest localized front-matter section before the body."""

    if first_body_page is None:
        return None
    pages = [
        int(entry["selected_start_page"])
        for entry in skeleton.get("toc_entries") or []
        if isinstance(entry, dict)
        and entry.get("role") == "front_matter"
        and isinstance(entry.get("selected_start_page"), int)
        and 0 < entry["selected_start_page"] < first_body_page
    ]
    return min(pages) if pages else None


def _boundary_page(skeleton: dict[str, Any], key: str) -> int | None:
    boundaries = skeleton.get("boundaries")
    if not isinstance(boundaries, dict):
        return None
    value = boundaries.get(key)
    return value if isinstance(value, int) and value > 0 else None


def _toc_pages(skeleton: dict[str, Any]) -> set[int]:
    return {
        page
        for page in skeleton.get("toc_pages") or []
        if isinstance(page, int) and page > 0
    }


def _visual_observation_kinds(document: dict[str, Any]) -> dict[int, list[str]]:
    kinds_by_page: dict[int, set[str]] = {}
    for observation in document.get("observations") or []:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") not in _VISUAL_OBSERVATION_KINDS
            or not isinstance(observation.get("page"), int)
        ):
            continue
        page = int(observation["page"])
        kinds_by_page.setdefault(page, set()).add(str(observation["kind"]))
    return {page: sorted(kinds) for page, kinds in kinds_by_page.items()}


def _body_section_start_pages(skeleton: dict[str, Any]) -> set[int]:
    return {
        int(entry["selected_start_page"])
        for entry in skeleton.get("toc_entries") or []
        if isinstance(entry, dict)
        and entry.get("role") == "body"
        and isinstance(entry.get("selected_start_page"), int)
        and entry["selected_start_page"] > 0
    }


def _page_review_record(
    page: int,
    role_record: dict[str, Any],
    first_front_matter_page: int | None,
    first_body_page: int | None,
    first_back_matter_page: int | None,
    is_body_section_start: bool,
    is_toc_page: bool,
    visual_kinds: list[str],
) -> dict[str, Any]:
    layout_page_role = str(role_record.get("page_role") or "unknown")
    page_role = _flow_page_role(layout_page_role)
    special_page_kind = _LAYOUT_SPECIAL_PAGE_KINDS.get(layout_page_role)
    signals = list(role_record.get("signals") or [])
    if is_toc_page:
        page_role = "visual_page"
        special_page_kind = "toc_page"
        actions = _DETERMINISTIC_SPECIAL_PAGE_ACTIONS["toc_page"]
        status = "deterministic"
    else:
        actions = _deterministic_actions(page_role, special_page_kind, signals)
        # A pre-body text layout is only provisional. Before
        # the first body page, it cannot establish whether a page is prose,
        # a title leaf, copyright material, or a visual page on its own.
        if bool(visual_kinds) or actions is None or _RASTER_VISUAL_SIGNALS.intersection(signals):
            actions = ("needs_review", "needs_review")
            status = "pending"
        else:
            status = "deterministic" if special_page_kind == "blank_page" else "not_selected"
    source = "layout_and_skeleton" if status != "pending" else "llm_page_review"
    return {
        "page": page,
        "page_role": page_role,
        "book_block_position": _book_block_position(
            page,
            first_front_matter_page,
            first_body_page,
            first_back_matter_page,
            is_toc_page=is_toc_page,
        ),
        "special_page_kind": special_page_kind,
        "text_flow_action": actions[0],
        "visual_asset_action": actions[1],
        "decision_source": source,
        "llm_review_status": status,
        "skeleton_context": {
            "matter": _matter_for_page(page, first_body_page, first_back_matter_page),
            "is_body_section_start": is_body_section_start,
        },
        "visual_kinds": list(visual_kinds),
        "signals": deepcopy(signals),
    }


def _deterministic_actions(
    page_role: str,
    special_page_kind: str | None,
    signals: list[Any],
) -> tuple[str, str] | None:
    if special_page_kind in _DETERMINISTIC_SPECIAL_PAGE_ACTIONS:
        return _DETERMINISTIC_SPECIAL_PAGE_ACTIONS[special_page_kind]
    if page_role == "text_flow_page" and "visual_verifier_candidate" not in signals:
        return ("include", "not_needed")
    return None


def _flow_page_role(layout_page_role: str) -> str:
    if layout_page_role in _VISUAL_LAYOUT_ROLES:
        return "visual_page"
    return "text_flow_page"


def _matter_for_page(
    page: int,
    first_body_page: int | None,
    first_back_matter_page: int | None,
) -> str:
    if first_body_page is not None and page < first_body_page:
        return "pre_body"
    if first_back_matter_page is not None and page >= first_back_matter_page:
        return "back_matter"
    return "body"


def _book_block_position(
    page: int,
    first_front_matter_page: int | None,
    first_body_page: int | None,
    first_back_matter_page: int | None,
    *,
    is_toc_page: bool,
) -> str:
    """Use Skeleton only where it establishes a book-internal position."""

    if is_toc_page or (
        first_front_matter_page is not None
        and first_body_page is not None
        and first_front_matter_page <= page < first_body_page
    ):
        return "front_matter"
    if first_body_page is not None and page < first_body_page:
        return "unknown"
    if first_back_matter_page is not None and page >= first_back_matter_page:
        return "back_matter"
    return "body"
