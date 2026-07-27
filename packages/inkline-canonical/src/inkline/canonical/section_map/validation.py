from __future__ import annotations

from typing import Any, Mapping

from inkline.canonical.book_skeleton import validate_book_skeleton_against_observed
from inkline.canonical.observed import TEXT_UNIT_TYPES, validate_observed_document
from inkline.canonical.page_review import validate_resolved_page_review
from inkline.canonical.schema import ValidationError
from inkline.canonical.section_map.contract import (
    REQUIRED_METADATA_FIELDS,
    REQUIRED_PAGE_PLACEMENT_FIELDS,
    REQUIRED_SECTION_FIELDS,
    REQUIRED_TOP_LEVEL_FIELDS,
    SECTION_MAP_CONFIDENCES,
    SECTION_MAP_DECISION_SOURCES,
    SECTION_MAP_PLACEMENTS,
    SECTION_MAP_SCHEMA_NAME,
    SECTION_MAP_SCHEMA_VERSION,
)


def validate_section_map(section_map: dict[str, Any]) -> None:
    """Validate SectionMap structure without interpreting upstream sources."""

    _validate_required_fields(section_map, REQUIRED_TOP_LEVEL_FIELDS, "section_map")
    _validate_metadata(section_map["metadata"])
    sections_by_id = _validate_sections(section_map["sections"])
    _validate_section_range_relationships(sections_by_id)
    _validate_page_placements(section_map["page_placements"], sections_by_id)


def validate_section_map_against_sources(
    section_map: dict[str, Any],
    skeleton: dict[str, Any],
    text_units: list[dict[str, Any]],
    observed_document: dict[str, Any],
    page_review: dict[str, Any],
) -> None:
    """Validate SectionMap references against immutable upstream artifacts."""

    validate_section_map(section_map)
    validate_book_skeleton_against_observed(skeleton, observed_document)
    validate_observed_document(observed_document)
    validate_resolved_page_review(page_review)
    _validate_page_review_metadata(page_review)
    _validate_matching_doc_ids(section_map, skeleton, observed_document, page_review)

    sections_by_id = {section["section_id"]: section for section in section_map["sections"]}
    entries_by_index = {entry["entry_index"]: entry for entry in skeleton["toc_entries"]}
    units_by_id = _validate_text_units(text_units, observed_document)
    page_numbers = {page["page"] for page in observed_document["pages"]}
    review_pages = _page_review_pages(page_review, page_numbers)
    known_evidence = _known_evidence_ids(
        skeleton,
        {observation["observation_id"] for observation in observed_document["observations"]},
        set(units_by_id),
        review_pages,
    )
    for section in sections_by_id.values():
        _validate_section_against_sources(
            section,
            entries_by_index,
            units_by_id,
            page_numbers,
            review_pages,
            known_evidence,
        )
    _validate_placements_against_sources(
        section_map["page_placements"],
        sections_by_id,
        units_by_id,
        page_numbers,
        review_pages,
        known_evidence,
    )


def _validate_required_fields(
    value: Any,
    fields: Mapping[str, type[Any] | tuple[type[Any], ...]],
    path: str,
) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must be object")
    for field, expected_type in fields.items():
        if field not in value or not isinstance(value[field], expected_type):
            raise ValidationError(f"{path}.{field} is invalid")


def _validate_metadata(metadata: dict[str, Any]) -> None:
    _validate_required_fields(metadata, REQUIRED_METADATA_FIELDS, "metadata")
    if metadata["schema_name"] != SECTION_MAP_SCHEMA_NAME:
        raise ValidationError(f"metadata.schema_name must be {SECTION_MAP_SCHEMA_NAME}")
    if metadata["schema_version"] != SECTION_MAP_SCHEMA_VERSION:
        raise ValidationError(f"metadata.schema_version must be {SECTION_MAP_SCHEMA_VERSION}")
    if not metadata["doc_id"]:
        raise ValidationError("metadata.doc_id must be non-empty")


def _validate_sections(sections: list[Any]) -> dict[str, dict[str, Any]]:
    sections_by_id: dict[str, dict[str, Any]] = {}
    text_unit_owners: dict[str, str] = {}
    visual_page_owners: dict[int, str] = {}
    for index, section in enumerate(sections):
        _validate_required_fields(section, REQUIRED_SECTION_FIELDS, f"sections[{index}]")
        _validate_section_shape(section, index)
        section_id = section["section_id"]
        if section_id in sections_by_id:
            raise ValidationError(f"duplicate section_id: {section_id}")
        sections_by_id[section_id] = section
        _validate_unique_assignment(
            section["text_unit_ids"], text_unit_owners, section_id, "TextUnit"
        )
        _validate_unique_assignment(
            section["attached_visual_pages"], visual_page_owners, section_id, "visual page"
        )

    for section in sections_by_id.values():
        _validate_parent_reference(section, sections_by_id)
    _validate_section_cycles(sections_by_id)
    for section in sections_by_id.values():
        _validate_parent_level(section, sections_by_id)
    return sections_by_id


def _validate_section_shape(section: dict[str, Any], index: int) -> None:
    section_id = section["section_id"]
    entry_index = section["skeleton_entry_index"]
    if not isinstance(entry_index, int) or isinstance(entry_index, bool) or entry_index < 0:
        raise ValidationError(f"sections[{index}].skeleton_entry_index must be non-negative")
    if section_id != f"s{entry_index:06d}":
        raise ValidationError(f"sections[{index}].section_id must equal canonical entry index")
    if not section["title"]:
        raise ValidationError(f"sections[{index}].title must be non-empty")
    level = section["level"]
    if not isinstance(level, int) or isinstance(level, bool) or level < 1:
        raise ValidationError(f"sections[{index}].level must be at least one")
    _validate_id_list(section["anchor_evidence_ids"], f"sections[{index}].anchor_evidence_ids")
    _validate_id_list(section["title_text_unit_ids"], f"sections[{index}].title_text_unit_ids")
    _validate_ranges(section["physical_ranges"], f"sections[{index}].physical_ranges")
    _validate_id_list(section["text_unit_ids"], f"sections[{index}].text_unit_ids")
    _validate_positive_unique_pages(
        section["attached_visual_pages"], f"sections[{index}].attached_visual_pages"
    )
    _validate_id_list(
        section["evidence_ids"], f"sections[{index}].evidence_ids", required=True
    )
    _validate_decision(section, f"sections[{index}]")


def _validate_id_list(values: list[Any], path: str, *, required: bool = False) -> None:
    if required and not values:
        raise ValidationError(f"{path} must be non-empty")
    if not all(isinstance(value, str) and value for value in values):
        raise ValidationError(f"{path} must contain non-empty string ids")
    if len(values) != len(set(values)):
        raise ValidationError(f"{path} must contain unique ids")


def _validate_positive_unique_pages(values: list[Any], path: str) -> None:
    if not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in values):
        raise ValidationError(f"{path} must contain positive pages")
    if len(values) != len(set(values)):
        raise ValidationError(f"{path} must contain unique pages")


def _validate_ranges(ranges: list[Any], path: str) -> None:
    previous_end = 0
    for index, page_range in enumerate(ranges):
        if (
            not isinstance(page_range, list)
            or len(page_range) != 2
            or not all(isinstance(page, int) and not isinstance(page, bool) for page in page_range)
        ):
            raise ValidationError(f"{path}[{index}] must be a two-page range")
        start_page, end_page = page_range
        if start_page <= 0 or end_page <= 0 or start_page > end_page:
            raise ValidationError(f"{path}[{index}] is invalid")
        if start_page <= previous_end:
            raise ValidationError(f"{path} must be sorted and non-overlapping")
        previous_end = end_page


def _validate_unique_assignment(
    values: list[Any], owners: dict[Any, str], section_id: str, noun: str
) -> None:
    for value in values:
        owner = owners.get(value)
        if owner is not None:
            raise ValidationError(f"{noun} {value} assigned to both {owner} and {section_id}")
        owners[value] = section_id


def _validate_parent_reference(
    section: dict[str, Any], sections_by_id: dict[str, dict[str, Any]]
) -> None:
    parent_id = section["parent_section_id"]
    if parent_id is None:
        return
    if parent_id not in sections_by_id:
        raise ValidationError(f"section {section['section_id']} has dangling parent")


def _validate_parent_level(
    section: dict[str, Any], sections_by_id: dict[str, dict[str, Any]]
) -> None:
    parent_id = section["parent_section_id"]
    if parent_id is None:
        return
    parent = sections_by_id[parent_id]
    if parent["level"] >= section["level"]:
        raise ValidationError(f"section {section['section_id']} parent level must be lower")


def _validate_section_cycles(sections_by_id: dict[str, dict[str, Any]]) -> None:
    for section_id in sections_by_id:
        visited: set[str] = set()
        current_id: str | None = section_id
        while current_id is not None:
            if current_id in visited:
                raise ValidationError("section parent graph must be acyclic")
            visited.add(current_id)
            current_id = sections_by_id[current_id]["parent_section_id"]


def _validate_section_range_relationships(sections_by_id: dict[str, dict[str, Any]]) -> None:
    sections = list(sections_by_id.values())
    for index, section in enumerate(sections):
        for other in sections[index + 1 :]:
            if _is_related(section["section_id"], other["section_id"], sections_by_id):
                continue
            if _ranges_overlap(section["physical_ranges"], other["physical_ranges"]):
                raise ValidationError("unrelated section physical ranges must not overlap")


def _is_related(first: str, second: str, sections_by_id: dict[str, dict[str, Any]]) -> bool:
    return _is_ancestor(first, second, sections_by_id) or _is_ancestor(
        second, first, sections_by_id
    )


def _is_ancestor(ancestor: str, descendant: str, sections_by_id: dict[str, dict[str, Any]]) -> bool:
    parent_id = sections_by_id[descendant]["parent_section_id"]
    while parent_id is not None:
        if parent_id == ancestor:
            return True
        parent_id = sections_by_id[parent_id]["parent_section_id"]
    return False


def _ranges_overlap(first: list[Any], second: list[Any]) -> bool:
    return any(start <= other_end and other_start <= end for start, end in first for other_start, other_end in second)


def _validate_page_placements(
    placements: list[Any], sections_by_id: dict[str, dict[str, Any]]
) -> None:
    pages: set[int] = set()
    for index, placement in enumerate(placements):
        path = f"page_placements[{index}]"
        _validate_required_fields(placement, REQUIRED_PAGE_PLACEMENT_FIELDS, path)
        page = placement["page"]
        if not isinstance(page, int) or isinstance(page, bool) or page <= 0:
            raise ValidationError(f"{path}.page must be positive")
        if page in pages:
            raise ValidationError(f"duplicate page placement: {page}")
        pages.add(page)
        _validate_placement(placement, sections_by_id, path)


def _validate_placement(
    placement: dict[str, Any], sections_by_id: dict[str, dict[str, Any]], path: str
) -> None:
    placement_kind = placement["placement"]
    if placement_kind not in SECTION_MAP_PLACEMENTS:
        raise ValidationError(f"{path}.placement is invalid")
    section_id = placement["section_id"]
    if placement_kind == "section_member":
        if section_id not in sections_by_id:
            raise ValidationError(f"{path}.section_id must reference a section")
        section = sections_by_id[section_id]
        if not _page_in_ranges(placement["page"], section["physical_ranges"]):
            raise ValidationError(f"{path}.page is outside section physical ranges")
        evidence_ids = set(placement["evidence_ids"])
        has_section_text_evidence = bool(evidence_ids & set(section["text_unit_ids"]))
        has_visual_evidence = (
            placement["page"] in section["attached_visual_pages"]
            and f"page_review:{placement['page']}" in evidence_ids
        )
        if not has_section_text_evidence and not has_visual_evidence:
            raise ValidationError(f"{path} cannot be supported by range containment alone")
    elif section_id is not None:
        raise ValidationError(f"{path}.section_id must be null for non-member placement")
    if not placement["reason"]:
        raise ValidationError(f"{path}.reason must be non-empty")
    _validate_id_list(placement["evidence_ids"], f"{path}.evidence_ids", required=True)
    _validate_decision(placement, path)


def _page_in_ranges(page: int, ranges: list[Any]) -> bool:
    return any(start <= page <= end for start, end in ranges)


def _validate_decision(value: dict[str, Any], path: str) -> None:
    if value["decision_source"] not in SECTION_MAP_DECISION_SOURCES:
        raise ValidationError(f"{path}.decision_source is invalid")
    if value["confidence"] not in SECTION_MAP_CONFIDENCES:
        raise ValidationError(f"{path}.confidence is invalid")


def _validate_matching_doc_ids(
    section_map: dict[str, Any],
    skeleton: dict[str, Any],
    document: dict[str, Any],
    page_review: dict[str, Any],
) -> None:
    review_metadata = page_review.get("metadata")
    review_doc_id = review_metadata.get("doc_id") if isinstance(review_metadata, dict) else None
    doc_ids = {
        section_map["metadata"]["doc_id"],
        skeleton["metadata"]["doc_id"],
        document["metadata"]["doc_id"],
        review_doc_id,
    }
    if None in doc_ids or len(doc_ids) != 1:
        raise ValidationError("SectionMap source doc_id values differ")


def _validate_page_review_metadata(page_review: dict[str, Any]) -> None:
    metadata = page_review.get("metadata")
    if not isinstance(metadata, dict):
        raise ValidationError("page_review metadata must be object")
    if metadata.get("schema_name") != "inkline_page_review":
        raise ValidationError("page_review metadata schema_name is invalid")
    if metadata.get("schema_version") != "1.4-shadow":
        raise ValidationError("page_review metadata schema_version is invalid")


def _validate_text_units(
    text_units: list[dict[str, Any]], document: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    if not isinstance(text_units, list):
        raise ValidationError("text_units must be a list")
    known_observations = {observation["observation_id"] for observation in document["observations"]}
    known_pages = {page["page"] for page in document["pages"]}
    units_by_id: dict[str, dict[str, Any]] = {}
    for index, unit in enumerate(text_units):
        path = f"text_units[{index}]"
        if not isinstance(unit, dict):
            raise ValidationError(f"{path} must be object")
        unit_id = unit.get("unit_id")
        unit_type = unit.get("unit_type")
        pages = unit.get("pages")
        observation_ids = unit.get("observation_ids")
        if not isinstance(unit_id, str) or not unit_id:
            raise ValidationError(f"{path}.unit_id is invalid")
        if unit_id in units_by_id:
            raise ValidationError(f"duplicate TextUnit id: {unit_id}")
        if unit_type not in TEXT_UNIT_TYPES:
            raise ValidationError(f"{path}.unit_type is invalid")
        if (
            not isinstance(pages, list)
            or not pages
            or not all(
                isinstance(page, int) and not isinstance(page, bool) and page in known_pages
                for page in pages
            )
        ):
            raise ValidationError(f"{path}.pages are invalid")
        if not isinstance(observation_ids, list):
            raise ValidationError(f"{path}.observation_ids are invalid")
        _validate_id_list(observation_ids, f"{path}.observation_ids", required=True)
        if not set(observation_ids) <= known_observations:
            raise ValidationError(f"{path}.observation_ids include unknown evidence")
        units_by_id[unit_id] = unit
    return units_by_id


def _page_review_pages(review: dict[str, Any], document_pages: set[int]) -> set[int]:
    records = review.get("pages")
    if not isinstance(records, list):
        raise ValidationError("page_review.pages must be a list")
    review_pages: set[int] = set()
    for index, record in enumerate(records):
        page = record.get("page") if isinstance(record, dict) else None
        if not isinstance(page, int) or isinstance(page, bool) or page <= 0:
            raise ValidationError(f"page_review.pages[{index}].page must be a positive integer")
        if page in review_pages:
            raise ValidationError(f"duplicate page_review page: {page}")
        if page not in document_pages:
            raise ValidationError(f"page_review page is outside ObservedDocument: {page}")
        review_pages.add(page)
    return review_pages


def _known_evidence_ids(
    skeleton: dict[str, Any],
    observation_ids: set[str],
    text_unit_ids: set[str],
    review_pages: set[int],
) -> set[str]:
    anchor_ids = {
        entry["selected_start_anchor"]["anchor_id"]
        for entry in skeleton["toc_entries"]
        if entry["selected_start_anchor"] is not None
    }
    return anchor_ids | observation_ids | text_unit_ids | {
        f"page_review:{page}" for page in review_pages
    }


def _validate_section_against_sources(
    section: dict[str, Any],
    entries_by_index: dict[int, dict[str, Any]],
    units_by_id: dict[str, dict[str, Any]],
    page_numbers: set[int],
    review_pages: set[int],
    known_evidence: set[str],
) -> None:
    entry = entries_by_index.get(section["skeleton_entry_index"])
    if entry is None:
        raise ValidationError(f"section {section['section_id']} has unknown Skeleton entry")
    expected_parent = _section_id_for_entry(entry["parent_entry_index"])
    if (
        section["title"] != entry["display_title"]
        or section["level"] != entry["level"]
        or section["parent_section_id"] != expected_parent
    ):
        raise ValidationError(f"section {section['section_id']} does not match Skeleton entry")
    _validate_section_pages(section, page_numbers, review_pages)
    _validate_section_text_unit_references(section, units_by_id)
    _validate_known_evidence(section["evidence_ids"], known_evidence, "section evidence")
    _validate_known_evidence(section["anchor_evidence_ids"], known_evidence, "anchor evidence")
    _validate_anchor_mapping(section, entry, units_by_id)


def _section_id_for_entry(entry_index: int | None) -> str | None:
    return None if entry_index is None else f"s{entry_index:06d}"


def _validate_section_pages(
    section: dict[str, Any], page_numbers: set[int], review_pages: set[int]
) -> None:
    for start_page, end_page in section["physical_ranges"]:
        range_pages = set(range(start_page, end_page + 1))
        if not range_pages <= page_numbers & review_pages:
            raise ValidationError(f"section {section['section_id']} references unknown physical page")
    if not set(section["attached_visual_pages"]) <= page_numbers & review_pages:
        raise ValidationError(f"section {section['section_id']} references unknown visual page")


def _validate_section_text_unit_references(
    section: dict[str, Any], units_by_id: dict[str, dict[str, Any]]
) -> None:
    unit_ids = set(section["text_unit_ids"])
    title_unit_ids = set(section["title_text_unit_ids"])
    if not unit_ids <= set(units_by_id):
        raise ValidationError(f"section {section['section_id']} references unknown TextUnit")
    if not title_unit_ids <= unit_ids:
        raise ValidationError(f"section {section['section_id']} title TextUnit is not a section member")


def _validate_known_evidence(values: list[str], known: set[str], path: str) -> None:
    if not set(values) <= known:
        raise ValidationError(f"{path} includes unknown evidence")


def _validate_anchor_mapping(
    section: dict[str, Any], entry: dict[str, Any], units_by_id: dict[str, dict[str, Any]]
) -> None:
    anchor = entry["selected_start_anchor"]
    if anchor is None:
        if section["anchor_evidence_ids"] or section["title_text_unit_ids"]:
            raise ValidationError(f"section {section['section_id']} has evidence for unlocated anchor")
        return
    if anchor["resolution_method"] == "observed_title_match":
        expected_ids = [
            anchor["anchor_id"],
            *anchor["title_observation_ids"],
            *anchor["toc_observation_ids"],
        ]
        if section["anchor_evidence_ids"] != expected_ids:
            raise ValidationError(f"section {section['section_id']} direct anchor evidence is invalid")
        _validate_direct_title_units(section, anchor, units_by_id)
        return
    expected_ids = [
        anchor["anchor_id"],
        *anchor["toc_observation_ids"],
        *anchor["supporting_anchor_ids"],
    ]
    if section["anchor_evidence_ids"] != expected_ids:
        raise ValidationError(f"section {section['section_id']} offset anchor evidence is invalid")
    if section["title_text_unit_ids"]:
        raise ValidationError(f"section {section['section_id']} offset anchor cannot have title TextUnit")
    ranges = section["physical_ranges"]
    if ranges and ranges[0][0] != anchor["page"]:
        raise ValidationError(f"section {section['section_id']} offset range must start on anchor page")


def _validate_direct_title_units(
    section: dict[str, Any], anchor: dict[str, Any], units_by_id: dict[str, dict[str, Any]]
) -> None:
    title_unit_ids = section["title_text_unit_ids"]
    if not title_unit_ids:
        raise ValidationError(f"section {section['section_id']} direct anchor requires title TextUnit")
    title_units = [units_by_id[unit_id] for unit_id in title_unit_ids]
    if any(
        anchor["page"] not in unit["pages"]
        for unit in title_units
    ):
        raise ValidationError(f"section {section['section_id']} title TextUnit is not on anchor page")
    observation_ids = [
        observation_id for unit in title_units for observation_id in unit["observation_ids"]
    ]
    if observation_ids != anchor["title_observation_ids"]:
        raise ValidationError(f"section {section['section_id']} title TextUnits do not cover anchor evidence")


def _validate_placements_against_sources(
    placements: list[dict[str, Any]],
    sections_by_id: dict[str, dict[str, Any]],
    units_by_id: dict[str, dict[str, Any]],
    page_numbers: set[int],
    review_pages: set[int],
    known_evidence: set[str],
) -> None:
    unit_pages_by_section = {
        section_id: {
            page
            for unit_id in section["text_unit_ids"]
            for page in units_by_id[unit_id]["pages"]
        }
        for section_id, section in sections_by_id.items()
    }
    page_local_unit_ids_by_section = {
        section_id: {
            page: {
                unit_id
                for unit_id in section["text_unit_ids"]
                if page in units_by_id[unit_id]["pages"]
            }
            for page in unit_pages_by_section[section_id]
        }
        for section_id, section in sections_by_id.items()
    }
    assigned_pages = set().union(*unit_pages_by_section.values()) if sections_by_id else set()
    assigned_pages.update(
        page for section in sections_by_id.values() for page in section["attached_visual_pages"]
    )
    for placement in placements:
        page = placement["page"]
        if page not in page_numbers or page not in review_pages:
            raise ValidationError(f"page placement references unknown physical page: {page}")
        _validate_known_evidence(placement["evidence_ids"], known_evidence, "placement evidence")
        if placement["placement"] == "section_member":
            section = sections_by_id[placement["section_id"]]
            page_local_unit_ids = page_local_unit_ids_by_section[section["section_id"]].get(
                page, set()
            )
            evidence_ids = set(placement["evidence_ids"])
            if evidence_ids & page_local_unit_ids:
                continue
            if page in section["attached_visual_pages"]:
                if f"page_review:{page}" in evidence_ids:
                    continue
                raise ValidationError(f"section member placement lacks page-local visual evidence: {page}")
            if page_local_unit_ids:
                raise ValidationError(f"section member placement lacks page-local TextUnit evidence: {page}")
            if page not in unit_pages_by_section[section["section_id"]]:
                raise ValidationError(f"section member placement has no page-local support: {page}")
            raise ValidationError(f"section member placement lacks page-local TextUnit evidence: {page}")
        elif page in assigned_pages:
            raise ValidationError(
                f"standalone or unresolved placement conflicts with section assignment: {page}"
            )
