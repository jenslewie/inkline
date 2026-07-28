from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from inkline.canonical.book_skeleton.contract import (
    BOOK_SKELETON_ANCHOR_CONFIDENCES,
    BOOK_SKELETON_ANCHOR_METHODS,
    BOOK_SKELETON_ENTRY_ROLE_ORDER,
    BOOK_SKELETON_ENTRY_ROLES,
    BOOK_SKELETON_SCHEMA_NAME,
    BOOK_SKELETON_SCHEMA_VERSION,
    REQUIRED_BOUNDARY_FIELDS,
    REQUIRED_ENTRY_FIELDS,
    REQUIRED_METADATA_FIELDS,
    REQUIRED_START_ANCHOR_FIELDS,
    REQUIRED_TOP_LEVEL_FIELDS,
)
from inkline.canonical.book_skeleton.pages import (
    locate_toc_entry_anchors,
    matching_toc_observation_ids,
    page_records,
)
from inkline.canonical.observed.index import ObservedIndex, build_observed_index
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


def validate_book_skeleton_against_observed(
    skeleton: dict[str, Any], document: dict[str, Any]
) -> None:
    validate_book_skeleton_against_index(skeleton, build_observed_index(document))


def validate_book_skeleton_against_index(
    skeleton: dict[str, Any], observed_index: ObservedIndex
) -> None:
    validate_book_skeleton(skeleton)
    if skeleton["metadata"]["doc_id"] != observed_index.doc_id:
        raise ValidationError("BookSkeleton and ObservedDocument doc_id values differ")
    observations = observed_index.observations_by_id
    records = page_records(observed_index)
    toc_page_numbers = skeleton["toc_pages"]
    toc_pages = set(toc_page_numbers)
    entries_by_anchor_id = {
        entry["selected_start_anchor"]["anchor_id"]: (index, entry)
        for index, entry in enumerate(skeleton["toc_entries"])
        if entry["selected_start_anchor"] is not None
    }
    for index, entry in enumerate(skeleton["toc_entries"]):
        anchor = entry["selected_start_anchor"]
        if anchor is None:
            continue
        for observation_id in anchor["title_observation_ids"]:
            observation = _required_anchor_observation(observations, observation_id)
            if observation["page"] != anchor["page"]:
                raise ValidationError(f"toc_entries[{index}] title evidence is not on anchor page")
        for observation_id in anchor["toc_observation_ids"]:
            observation = _required_anchor_observation(observations, observation_id)
            if observation["page"] not in toc_pages or observation["role_hint"] != "toc_text":
                raise ValidationError(f"toc_entries[{index}] TOC evidence is not on a TOC page")
        _validate_anchor_evidence_semantics(
            observed_index,
            records,
            toc_page_numbers,
            entry,
            index,
        )
        if anchor["resolution_method"] != "printed_page_offset":
            continue
        support = []
        for supporting_anchor_id in anchor["supporting_anchor_ids"]:
            supporting_entry = entries_by_anchor_id.get(supporting_anchor_id)
            if supporting_entry is None:
                raise ValidationError(f"toc_entries[{index}] references unknown supporting anchor")
            support.append(supporting_entry)
        support_indexes = [value[0] for value in support]
        support_anchors = [value[1]["selected_start_anchor"] for value in support]
        if not (min(support_indexes) < index < max(support_indexes)):
            raise ValidationError(f"toc_entries[{index}] offset supports must straddle the entry")
        expected_offset = anchor["printed_page_offset"]
        if any(
            value["resolution_method"] != "observed_title_match"
            or value["printed_page_offset"] != expected_offset
            for value in support_anchors
        ):
            raise ValidationError(f"toc_entries[{index}] offset supports do not agree")


def _required_anchor_observation(
    observations: Mapping[str, Mapping[str, Any]], observation_id: str
) -> Mapping[str, Any]:
    observation = observations.get(observation_id)
    if observation is None:
        raise ValidationError(f"anchor references unknown observation: {observation_id}")
    return observation


def _validate_anchor_evidence_semantics(
    observed_index: ObservedIndex,
    records: list[dict[str, Any]],
    toc_pages: list[int],
    entry: dict[str, Any],
    index: int,
) -> None:
    anchor = entry["selected_start_anchor"]
    if anchor["resolution_method"] == "observed_title_match":
        direct_candidate = next(
            (
                candidate
                for candidate in locate_toc_entry_anchors(
                    records,
                    entry,
                    exclude_pages=toc_pages,
                )
                if candidate["page"] == anchor["page"]
            ),
            None,
        )
        if (
            direct_candidate is None
            or direct_candidate["exact_title_observation_ids"] is None
            or anchor["title_observation_ids"] != direct_candidate["exact_title_observation_ids"]
        ):
            raise ValidationError(
                f"toc_entries[{index}] title evidence does not match direct candidate"
            )
    expected_toc_observation_ids = matching_toc_observation_ids(
        observed_index,
        entry,
        toc_pages=toc_pages,
    )
    if anchor["toc_observation_ids"] != expected_toc_observation_ids:
        raise ValidationError(f"toc_entries[{index}] TOC evidence does not match entry title")


def audit_book_skeleton(skeleton: dict[str, Any]) -> dict[str, Any]:
    entries = [entry for entry in skeleton.get("toc_entries", []) if isinstance(entry, dict)]
    issues = _audit_toc_entry_issues(entries)
    role_counts = Counter(str(entry.get("role") or "") for entry in entries)
    located_count = sum(1 for entry in entries if isinstance(entry.get("selected_start_page"), int))
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
    seen_anchor_ids: set[str] = set()
    previous_known_role_rank = -1
    previous_selected_start_page: int | None = None
    for index, entry in enumerate(entries):
        _validate_toc_entry_shape(entry, index, seen)
        _validate_toc_entry_pages(entry, index)
        _validate_start_anchor(entry, index, seen_anchor_ids)
        selected_start_page = entry["selected_start_page"]
        if (
            isinstance(selected_start_page, int)
            and previous_selected_start_page is not None
            and selected_start_page < previous_selected_start_page
        ):
            raise ValidationError("toc_entries selected_start_page values must be monotonic")
        if isinstance(selected_start_page, int):
            previous_selected_start_page = selected_start_page
        previous_known_role_rank = _validate_toc_entry_role_order(entry, previous_known_role_rank)


def _validate_toc_entry_shape(entry: dict[str, Any], index: int, seen: set[int]) -> None:
    if not isinstance(entry, dict):
        raise ValidationError(f"toc_entries[{index}] must be object")
    for field, expected_type in REQUIRED_ENTRY_FIELDS.items():
        if field not in entry:
            raise ValidationError(f"toc_entries[{index}].{field} is invalid")
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
        raise ValidationError(f"toc_entries[{index}].printed_start_page is internal TOC evidence")


def _validate_start_anchor(entry: dict[str, Any], index: int, seen_anchor_ids: set[str]) -> None:
    anchor = entry["selected_start_anchor"]
    selected_start_page = entry["selected_start_page"]
    if (anchor is None) != (selected_start_page is None):
        raise ValidationError(
            f"toc_entries[{index}].selected_start_anchor must be null iff "
            "selected_start_page is null"
        )
    if anchor is None:
        return
    for field, expected_type in REQUIRED_START_ANCHOR_FIELDS.items():
        if field not in anchor or not isinstance(anchor[field], expected_type):
            raise ValidationError(f"toc_entries[{index}].selected_start_anchor.{field} is invalid")
    expected_anchor_id = f"sa{int(entry['entry_index']):06d}"
    anchor_id = anchor["anchor_id"]
    if anchor_id != expected_anchor_id:
        raise ValidationError(
            f"toc_entries[{index}].selected_start_anchor.anchor_id must be {expected_anchor_id}"
        )
    if anchor_id in seen_anchor_ids:
        raise ValidationError(f"duplicate selected start anchor id: {anchor_id}")
    seen_anchor_ids.add(anchor_id)
    if anchor["page"] != selected_start_page:
        raise ValidationError(f"toc_entries[{index}] anchor page must equal selected_start_page")
    method = anchor["resolution_method"]
    if method not in BOOK_SKELETON_ANCHOR_METHODS:
        raise ValidationError(
            f"toc_entries[{index}].selected_start_anchor.resolution_method is invalid"
        )
    confidence = anchor["confidence"]
    if confidence not in BOOK_SKELETON_ANCHOR_CONFIDENCES:
        raise ValidationError(f"toc_entries[{index}].selected_start_anchor.confidence is invalid")
    for field in (
        "title_observation_ids",
        "toc_observation_ids",
        "supporting_anchor_ids",
    ):
        _validate_anchor_ids(anchor[field], index=index, field=field)
    _validate_anchor_observation_namespaces(anchor, index)
    if method == "observed_title_match":
        _validate_direct_anchor(anchor, index)
    else:
        _validate_printed_offset_anchor(anchor, index)


def _validate_anchor_ids(values: list[Any], *, index: int, field: str) -> None:
    if not all(isinstance(value, str) for value in values):
        raise ValidationError(
            f"toc_entries[{index}].selected_start_anchor.{field} must contain strings"
        )
    if len(values) != len(set(values)):
        raise ValidationError(
            f"toc_entries[{index}].selected_start_anchor.{field} must contain unique ids"
        )


def _validate_anchor_observation_namespaces(anchor: dict[str, Any], index: int) -> None:
    if set(anchor["title_observation_ids"]) & set(anchor["toc_observation_ids"]):
        raise ValidationError(
            f"toc_entries[{index}] title and TOC observation evidence must not overlap"
        )


def _validate_direct_anchor(anchor: dict[str, Any], index: int) -> None:
    if anchor["confidence"] != "high":
        raise ValidationError(f"toc_entries[{index}] direct anchor confidence must be high")
    if not anchor["title_observation_ids"]:
        raise ValidationError(
            f"toc_entries[{index}] direct anchor requires title observation evidence"
        )
    if anchor["supporting_anchor_ids"]:
        raise ValidationError(f"toc_entries[{index}] direct anchor cannot have supporting anchors")


def _validate_printed_offset_anchor(anchor: dict[str, Any], index: int) -> None:
    if anchor["confidence"] != "medium":
        raise ValidationError(
            f"toc_entries[{index}] printed offset anchor confidence must be medium"
        )
    if anchor["title_observation_ids"]:
        raise ValidationError(
            f"toc_entries[{index}] printed offset anchor cannot have title evidence"
        )
    if not isinstance(anchor["printed_page_offset"], int):
        raise ValidationError(
            f"toc_entries[{index}] printed offset anchor requires printed_page_offset"
        )
    if len(anchor["supporting_anchor_ids"]) != 2:
        raise ValidationError(
            f"toc_entries[{index}] printed offset anchor requires exactly two supports"
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
        raise ValidationError(f"toc_entries[{index}].display_title looks like glued TOC entries")


def _validate_toc_entry_role_order(entry: dict[str, Any], previous_known_role_rank: int) -> int:
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
        if (
            field.endswith("_entry_index")
            and isinstance(value, int)
            and not 0 <= value < entry_count
        ):
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
