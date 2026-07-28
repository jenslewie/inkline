from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from inkline.canonical.book_skeleton import validate_book_skeleton
from inkline.canonical.page_review import validate_resolved_page_review
from inkline.canonical.schema import ValidationError
from inkline.canonical.section_map.contract import (
    SECTION_MAP_EVIDENCE_SCHEMA_NAME,
    SECTION_MAP_EVIDENCE_SCHEMA_VERSION,
    SECTION_MAP_START_METHODS,
    SECTION_MAP_TEXT_FLOW_STATUSES,
)
from inkline.canonical.text_flow import validate_text_flow


def build_section_map_evidence(
    skeleton: dict[str, Any],
    page_review: dict[str, Any],
    text_flow: dict[str, Any],
) -> dict[str, Any]:
    """Normalize validated upstream structure without inferring membership or ranges."""

    validate_book_skeleton(skeleton)
    validate_resolved_page_review(page_review)
    validate_text_flow(text_flow)
    doc_id = _matching_doc_id(skeleton, page_review, text_flow)
    units = text_flow["text_units"]
    units_by_observations = _units_by_observation_group(units)
    review_pages = _normalized_review_pages(page_review, text_flow)
    review_by_page = {record["page"]: record for record in review_pages}
    sections = [
        _section_seed(entry, units_by_observations, review_by_page)
        for entry in skeleton["toc_entries"]
    ]
    evidence = {
        "metadata": {
            "schema_name": SECTION_MAP_EVIDENCE_SCHEMA_NAME,
            "schema_version": SECTION_MAP_EVIDENCE_SCHEMA_VERSION,
            "doc_id": doc_id,
        },
        "sections": sections,
        "text_flow_order": [str(unit["unit_id"]) for unit in units],
        "page_review_pages": review_pages,
    }
    validate_section_map_evidence(evidence)
    return evidence


def validate_section_map_evidence(evidence: dict[str, Any]) -> None:
    if set(evidence) != {
        "metadata",
        "sections",
        "text_flow_order",
        "page_review_pages",
    }:
        raise ValidationError("SectionMap evidence has invalid top-level fields")
    metadata = evidence.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("schema_name") != SECTION_MAP_EVIDENCE_SCHEMA_NAME
    ):
        raise ValidationError("SectionMap evidence metadata is invalid")
    if metadata.get("schema_version") != SECTION_MAP_EVIDENCE_SCHEMA_VERSION:
        raise ValidationError("SectionMap evidence schema version is invalid")
    if not isinstance(metadata.get("doc_id"), str) or not metadata["doc_id"]:
        raise ValidationError("SectionMap evidence doc_id is invalid")
    _validate_section_seeds(evidence.get("sections"))
    _validate_order(evidence.get("text_flow_order"), "text_flow_order")
    _validate_review_pages(evidence.get("page_review_pages"))


def _section_seed(
    entry: dict[str, Any],
    units_by_observations: dict[tuple[str, ...], list[dict[str, Any]]],
    review_by_page: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    entry_index = int(entry["entry_index"])
    parent_index = entry.get("parent_entry_index")
    return {
        "section_id": f"s{entry_index:06d}",
        "title": str(entry["display_title"]),
        "level": int(entry["level"]),
        "parent_section_id": (
            f"s{int(parent_index):06d}" if isinstance(parent_index, int) else None
        ),
        "skeleton_entry_index": entry_index,
        "role": str(entry["role"]),
        "start_evidence": _start_evidence(entry, units_by_observations, review_by_page),
    }


def _start_evidence(
    entry: dict[str, Any],
    units_by_observations: dict[tuple[str, ...], list[dict[str, Any]]],
    review_by_page: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    anchor = entry.get("selected_start_anchor")
    if not isinstance(anchor, Mapping):
        return {
            "method": "unlocated",
            "anchor_id": None,
            "page": None,
            "title_text_unit_id": None,
            "text_flow_status": "unlocated",
            "title_observation_ids": [],
            "toc_observation_ids": [],
            "supporting_anchor_ids": [],
            "printed_page_offset": None,
        }
    method = str(anchor["resolution_method"])
    title_observation_ids = tuple(str(value) for value in anchor["title_observation_ids"])
    title_unit_id = None
    text_flow_status = "not_applicable"
    if method == "observed_title_match":
        page = int(anchor["page"])
        review = review_by_page.get(page)
        if review is None:
            raise ValidationError(f"direct Skeleton anchor {anchor['anchor_id']} lacks PageReview")
        if review["text_flow_action"] == "include":
            matches = units_by_observations.get(title_observation_ids, [])
            if len(matches) != 1:
                raise ValidationError(
                    f"direct Skeleton anchor {anchor['anchor_id']} requires one exact TextFlow unit"
                )
            unit = matches[0]
            if unit["unit_type"] != "heading" or unit["pages"] != [page]:
                raise ValidationError(f"direct Skeleton anchor {anchor['anchor_id']} is off-page")
            title_unit_id = str(unit["unit_id"])
            text_flow_status = "mapped"
        else:
            text_flow_status = "excluded_by_page_review"
    elif title_observation_ids:
        raise ValidationError("printed-offset anchor must not fabricate title observations")
    return {
        "method": method,
        "anchor_id": str(anchor["anchor_id"]),
        "page": int(anchor["page"]),
        "title_text_unit_id": title_unit_id,
        "text_flow_status": text_flow_status,
        "title_observation_ids": list(title_observation_ids),
        "toc_observation_ids": list(anchor["toc_observation_ids"]),
        "supporting_anchor_ids": list(anchor["supporting_anchor_ids"]),
        "printed_page_offset": anchor["printed_page_offset"],
    }


def _units_by_observation_group(
    units: list[dict[str, Any]],
) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for unit in units:
        key = tuple(str(value) for value in unit["observation_ids"])
        grouped.setdefault(key, []).append(unit)
    return grouped


def _normalized_review_pages(
    page_review: dict[str, Any], text_flow: dict[str, Any]
) -> list[dict[str, Any]]:
    records = page_review["pages"]
    pages = [int(record["page"]) for record in records]
    included_pages = {
        int(record["page"]) for record in records if record["text_flow_action"] == "include"
    }
    expected_included = set(text_flow["provenance"]["included_pages"])
    expected_excluded = set(text_flow["provenance"]["excluded_pages"])
    expected_pages = sorted(expected_included | expected_excluded)
    if pages != expected_pages:
        raise ValidationError("PageReview coverage differs from TextFlow provenance")
    if included_pages != expected_included or set(pages) - included_pages != expected_excluded:
        raise ValidationError("PageReview actions differ from TextFlow provenance")
    return [
        {
            "page": int(record["page"]),
            "page_role": str(record["page_role"]),
            "book_block_position": str(record["book_block_position"]),
            "special_page_kind": record["special_page_kind"],
            "text_flow_action": str(record["text_flow_action"]),
            "visual_asset_action": str(record["visual_asset_action"]),
        }
        for record in records
    ]


def _matching_doc_id(*sources: dict[str, Any]) -> str:
    doc_ids = {source.get("metadata", {}).get("doc_id") for source in sources}
    if len(doc_ids) != 1 or None in doc_ids:
        raise ValidationError("SectionMap source doc_id values differ")
    return str(next(iter(doc_ids)))


def _validate_section_seeds(value: Any) -> None:
    if not isinstance(value, list):
        raise ValidationError("SectionMap evidence sections must be list")
    expected_fields = {
        "section_id",
        "title",
        "level",
        "parent_section_id",
        "skeleton_entry_index",
        "role",
        "start_evidence",
    }
    for index, section in enumerate(value):
        if not isinstance(section, dict) or set(section) != expected_fields:
            raise ValidationError(f"SectionMap evidence sections[{index}] is invalid")
        if section["section_id"] != f"s{section['skeleton_entry_index']:06d}":
            raise ValidationError(f"SectionMap evidence sections[{index}] id is invalid")
        start = section.get("start_evidence")
        if not isinstance(start, dict) or start.get("method") not in SECTION_MAP_START_METHODS:
            raise ValidationError(f"SectionMap evidence sections[{index}] start is invalid")
        _validate_start_evidence(start, index)


def _validate_start_evidence(start: dict[str, Any], section_index: int) -> None:
    fields = {
        "method",
        "anchor_id",
        "page",
        "title_text_unit_id",
        "text_flow_status",
        "title_observation_ids",
        "toc_observation_ids",
        "supporting_anchor_ids",
        "printed_page_offset",
    }
    if set(start) != fields or start["text_flow_status"] not in SECTION_MAP_TEXT_FLOW_STATUSES:
        raise ValidationError(f"SectionMap evidence sections[{section_index}] start is invalid")
    method = start["method"]
    status = start["text_flow_status"]
    title_unit_id = start["title_text_unit_id"]
    if method == "observed_title_match" and status == "mapped":
        if not isinstance(title_unit_id, str) or not title_unit_id:
            raise ValidationError("mapped direct anchor requires title TextUnit")
    elif title_unit_id is not None:
        raise ValidationError("non-mapped anchor cannot reference title TextUnit")
    if method == "printed_page_offset" and status != "not_applicable":
        raise ValidationError("printed-offset anchor TextFlow status is invalid")
    if method == "unlocated" and status != "unlocated":
        raise ValidationError("unlocated anchor TextFlow status is invalid")


def _validate_order(value: Any, path: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValidationError(f"SectionMap evidence {path} is invalid")
    if len(value) != len(set(value)):
        raise ValidationError(f"SectionMap evidence {path} contains duplicates")


def _validate_review_pages(value: Any) -> None:
    if not isinstance(value, list):
        raise ValidationError("SectionMap evidence page_review_pages must be list")
    if not all(
        isinstance(record, dict) and isinstance(record.get("page"), int) for record in value
    ):
        raise ValidationError("SectionMap evidence PageReview pages must be ordered unique")
    pages = [int(record["page"]) for record in value]
    if pages != sorted(set(pages)):
        raise ValidationError("SectionMap evidence PageReview pages must be ordered unique")
