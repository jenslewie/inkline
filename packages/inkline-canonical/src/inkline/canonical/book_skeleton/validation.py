from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from typing import Any

from inkline.canonical.book_skeleton.contract import (
    BOOK_SKELETON_ENTRY_ROLE_ORDER,
    BOOK_SKELETON_ENTRY_ROLES,
    BOOK_SKELETON_SCHEMA_NAME,
    BOOK_SKELETON_SCHEMA_VERSION,
    REQUIRED_BOUNDARY_FIELDS,
    REQUIRED_ENTRY_FIELDS,
    REQUIRED_METADATA_FIELDS,
    REQUIRED_TOP_LEVEL_FIELDS,
)
from inkline.canonical.schema import ValidationError

GLUED_TOC_ENTRY_PART_RE = re.compile(
    r"\s*(?P<title>.+?)\s+(?P<page>[ivxlcdmIVXLCDM\d]+)(?=\s+\S|$)"
)


def validate_book_skeleton(skeleton: dict[str, Any]) -> None:
    for field, expected_type in REQUIRED_TOP_LEVEL_FIELDS.items():
        value = skeleton.get(field)
        if not isinstance(value, expected_type):
            raise ValidationError(f"{field} must be {expected_type.__name__}")
    _validate_metadata(skeleton["metadata"])
    _validate_toc_pages(skeleton["toc_pages"])
    _validate_toc_entries(skeleton["toc_entries"])
    _validate_boundaries(skeleton["boundaries"], len(skeleton["toc_entries"]))
    _validate_llm(skeleton["llm"])


def audit_book_skeleton(skeleton: dict[str, Any]) -> dict[str, Any]:
    entries = [entry for entry in skeleton.get("toc_entries", []) if isinstance(entry, dict)]
    issues = _audit_toc_entry_issues(entries)
    role_counts = Counter(str(entry.get("role") or "") for entry in entries)
    located_count = sum(
        1 for entry in entries if isinstance(entry.get("selected_start_page"), int)
    )
    return {
        "summary": {
            "toc_entry_count": len(entries),
            "located_entry_count": located_count,
            "unlocated_entry_count": len(entries) - located_count,
            "issue_count": len(issues),
            "role_counts": dict(role_counts),
            "boundaries": deepcopy(skeleton.get("boundaries") or {}),
        },
        "issues": issues,
    }


def _validate_metadata(metadata: dict[str, Any]) -> None:
    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata:
            raise ValidationError(f"metadata.{field} is required")
    if metadata.get("schema_name") != BOOK_SKELETON_SCHEMA_NAME:
        raise ValidationError(f"metadata.schema_name must be {BOOK_SKELETON_SCHEMA_NAME}")
    if metadata.get("schema_version") != BOOK_SKELETON_SCHEMA_VERSION:
        raise ValidationError(f"metadata.schema_version must be {BOOK_SKELETON_SCHEMA_VERSION}")


def _validate_toc_pages(toc_pages: list[Any]) -> None:
    if not all(isinstance(page, int) for page in toc_pages):
        raise ValidationError("toc_pages must contain integers")


def _validate_toc_entries(entries: list[dict[str, Any]]) -> None:
    seen: set[int] = set()
    previous_known_role_rank = -1
    for index, entry in enumerate(entries):
        _validate_toc_entry_shape(entry, index, seen)
        _validate_toc_entry_pages(entry, index)
        previous_known_role_rank = _validate_toc_entry_role_order(
            entry, previous_known_role_rank
        )


def _validate_toc_entry_shape(
    entry: dict[str, Any], index: int, seen: set[int]
) -> None:
    if not isinstance(entry, dict):
        raise ValidationError(f"toc_entries[{index}] must be object")
    for field, expected_type in REQUIRED_ENTRY_FIELDS.items():
        value = entry.get(field)
        if not isinstance(value, expected_type):
            raise ValidationError(f"toc_entries[{index}].{field} is invalid")
    entry_index = entry["entry_index"]
    if entry_index in seen:
        raise ValidationError(f"duplicate toc entry index: {entry_index}")
    if entry_index != index:
        raise ValidationError(f"toc_entries[{index}].entry_index must equal list index")
    seen.add(entry_index)
    if entry["role"] not in BOOK_SKELETON_ENTRY_ROLES:
        raise ValidationError(f"toc_entries[{index}].role is invalid: {entry['role']}")
    if "candidate_pages" in entry:
        raise ValidationError(
            f"toc_entries[{index}].candidate_pages is ambiguous; use candidate_start_pages"
        )
    if "selected_page" in entry:
        raise ValidationError(
            f"toc_entries[{index}].selected_page is ambiguous; use selected_start_page"
        )
    if "printed_start_page" in entry:
        raise ValidationError(
            f"toc_entries[{index}].printed_start_page is internal TOC evidence"
        )


def _validate_toc_entry_pages(entry: dict[str, Any], index: int) -> None:
    candidate_start_pages = entry["candidate_start_pages"]
    if not all(isinstance(page, int) for page in candidate_start_pages):
        raise ValidationError(f"toc_entries[{index}].candidate_start_pages must contain integers")
    selected_start_page = entry["selected_start_page"]
    if selected_start_page is not None and selected_start_page not in candidate_start_pages:
        raise ValidationError(
            f"toc_entries[{index}].selected_start_page must be one of candidate_start_pages"
        )
    if not candidate_start_pages and _looks_like_glued_toc_title(entry["display_title"]):
        raise ValidationError(
            f"toc_entries[{index}].display_title looks like glued TOC entries"
        )


def _validate_toc_entry_role_order(
    entry: dict[str, Any], previous_known_role_rank: int
) -> int:
    role_rank = BOOK_SKELETON_ENTRY_ROLE_ORDER.get(entry["role"])
    if role_rank is None:
        return previous_known_role_rank
    if role_rank < previous_known_role_rank:
        raise ValidationError("toc_entries roles must be contiguous")
    return role_rank


def _looks_like_glued_toc_title(title: str) -> bool:
    return len(title) >= 40 and len(list(GLUED_TOC_ENTRY_PART_RE.finditer(title))) >= 2


def _audit_toc_entry_issues(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    previous_selected_start_page: int | None = None
    previous_known_role_rank = -1
    for index, entry in enumerate(entries):
        entry_index = entry.get("entry_index", index)
        title = str(entry.get("display_title") or "")
        candidate_start_pages = entry.get("candidate_start_pages")
        if not isinstance(candidate_start_pages, list):
            candidate_start_pages = []
        selected_start_page = entry.get("selected_start_page")
        if not candidate_start_pages:
            issues.append(
                _toc_entry_issue(
                    "unlocated_entry",
                    entry_index=entry_index,
                    title=title,
                    message="TOC entry has no located physical start page.",
                )
            )
        if selected_start_page is not None and selected_start_page not in candidate_start_pages:
            issues.append(
                _toc_entry_issue(
                    "selected_start_page_not_in_candidates",
                    entry_index=entry_index,
                    title=title,
                    message="selected_start_page is not present in candidate_start_pages.",
                )
            )
        if (
            isinstance(selected_start_page, int)
            and previous_selected_start_page is not None
            and selected_start_page < previous_selected_start_page
        ):
            issues.append(
                _toc_entry_issue(
                    "non_monotonic_selected_start_page",
                    entry_index=entry_index,
                    title=title,
                    message="selected_start_page moves backwards from the previous located TOC entry.",
                )
            )
        if isinstance(selected_start_page, int):
            previous_selected_start_page = selected_start_page
        role_rank = BOOK_SKELETON_ENTRY_ROLE_ORDER.get(str(entry.get("role") or ""))
        if role_rank is not None:
            if role_rank < previous_known_role_rank:
                issues.append(
                    _toc_entry_issue(
                        "roles_not_contiguous",
                        entry_index=entry_index,
                        title=title,
                        message="Known TOC roles must progress front_matter -> body -> back_matter.",
                    )
                )
            previous_known_role_rank = role_rank
    return issues


def _toc_entry_issue(
    issue_type: str, *, entry_index: Any, title: str, message: str, severity: str = "warning"
) -> dict[str, Any]:
    return {
        "severity": severity,
        "issue_type": issue_type,
        "entry_index": entry_index,
        "title": title,
        "message": message,
    }


def _validate_boundaries(boundaries: dict[str, Any], entry_count: int) -> None:
    for field in REQUIRED_BOUNDARY_FIELDS:
        if field not in boundaries:
            raise ValidationError(f"boundaries.{field} is required")
        value = boundaries[field]
        if value is not None and not isinstance(value, int):
            raise ValidationError(f"boundaries.{field} must be integer or null")
        if field.endswith("_entry_index") and isinstance(value, int) and not 0 <= value < entry_count:
            raise ValidationError(f"boundaries.{field} points to missing toc entry")


def _validate_llm(llm: dict[str, Any]) -> None:
    if not isinstance(llm.get("used"), bool):
        raise ValidationError("llm.used must be boolean")
    if llm.get("model") is not None and not isinstance(llm.get("model"), str):
        raise ValidationError("llm.model must be string or null")
    if llm.get("source") is not None and not isinstance(llm.get("source"), str):
        raise ValidationError("llm.source must be string or null")
    if not isinstance(llm.get("uncertain_entries"), list):
        raise ValidationError("llm.uncertain_entries must be list")
