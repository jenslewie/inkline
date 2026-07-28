from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from inkline.canonical.book_skeleton import validate_book_skeleton_against_index
from inkline.canonical.observed.index import ObservedIndex
from inkline.canonical.page_review import validate_resolved_page_review
from inkline.canonical.schema import ValidationError
from inkline.canonical.text_flow import validate_text_flow


@dataclass(frozen=True)
class SectionMapSources:
    doc_id: str
    entries_by_index: Mapping[int, Mapping[str, Any]]
    units_by_id: Mapping[str, Mapping[str, Any]]
    review_by_page: Mapping[int, Mapping[str, Any]]
    observations_by_id: Mapping[str, Mapping[str, Any]]


def validate_section_map_sources(
    skeleton: dict[str, Any],
    page_review: dict[str, Any],
    text_flow: dict[str, Any],
    observed_index: ObservedIndex,
) -> SectionMapSources:
    """Audit SectionMap inputs against raw observed identities without exposing them to builders."""

    validate_book_skeleton_against_index(skeleton, observed_index)
    validate_resolved_page_review(page_review)
    validate_text_flow(text_flow)
    _validate_doc_ids(skeleton, page_review, text_flow, observed_index.doc_id)
    review_by_page = _review_by_page(page_review, observed_index.page_numbers)
    units_by_id = _units_by_id(text_flow, observed_index, review_by_page)
    _validate_text_flow_page_sets(text_flow, review_by_page)
    _validate_direct_anchor_units(skeleton, units_by_id, review_by_page)
    return SectionMapSources(
        doc_id=observed_index.doc_id,
        entries_by_index=MappingProxyType(
            {int(entry["entry_index"]): entry for entry in skeleton["toc_entries"]}
        ),
        units_by_id=MappingProxyType(units_by_id),
        review_by_page=MappingProxyType(review_by_page),
        observations_by_id=observed_index.observations_by_id,
    )


def _validate_doc_ids(
    skeleton: dict[str, Any],
    page_review: dict[str, Any],
    text_flow: dict[str, Any],
    doc_id: str,
) -> None:
    values = {
        skeleton.get("metadata", {}).get("doc_id"),
        page_review.get("metadata", {}).get("doc_id"),
        text_flow.get("metadata", {}).get("doc_id"),
        doc_id,
    }
    if values != {doc_id}:
        raise ValidationError("SectionMap source doc_id values differ")


def _review_by_page(
    page_review: dict[str, Any], page_numbers: tuple[int, ...]
) -> dict[int, Mapping[str, Any]]:
    records: dict[int, Mapping[str, Any]] = {}
    for record in page_review["pages"]:
        page = int(record["page"])
        if page in records:
            raise ValidationError(f"duplicate PageReview page: {page}")
        records[page] = record
    if tuple(records) != page_numbers:
        raise ValidationError("PageReview must cover every observed page exactly once in order")
    return records


def _units_by_id(
    text_flow: dict[str, Any],
    observed_index: ObservedIndex,
    review_by_page: dict[int, Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    units: dict[str, Mapping[str, Any]] = {}
    for unit in text_flow["text_units"]:
        observation_ids = unit["observation_ids"]
        observations = []
        for observation_id in observation_ids:
            observation = observed_index.observations_by_id.get(observation_id)
            if observation is None:
                raise ValidationError(f"TextFlow references unknown observation: {observation_id}")
            observations.append(observation)
        pages = list(dict.fromkeys(int(observation["page"]) for observation in observations))
        if unit["pages"] != pages:
            raise ValidationError(f"TextFlow unit {unit['unit_id']} has off-page provenance")
        if any(review_by_page[page]["text_flow_action"] != "include" for page in pages):
            raise ValidationError(f"TextFlow unit {unit['unit_id']} is on a non-included page")
        units[str(unit["unit_id"])] = unit
    return units


def _validate_text_flow_page_sets(
    text_flow: dict[str, Any], review_by_page: dict[int, Mapping[str, Any]]
) -> None:
    included = {
        page for page, record in review_by_page.items() if record["text_flow_action"] == "include"
    }
    expected_included = set(text_flow["provenance"]["included_pages"])
    expected_excluded = set(text_flow["provenance"]["excluded_pages"])
    if included != expected_included or set(review_by_page) - included != expected_excluded:
        raise ValidationError("PageReview actions differ from TextFlow provenance")


def _validate_direct_anchor_units(
    skeleton: dict[str, Any],
    units_by_id: dict[str, Mapping[str, Any]],
    review_by_page: dict[int, Mapping[str, Any]],
) -> None:
    units_by_group: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
    for unit in units_by_id.values():
        group = tuple(str(value) for value in unit["observation_ids"])
        units_by_group.setdefault(group, []).append(unit)
    for entry in skeleton["toc_entries"]:
        anchor = entry.get("selected_start_anchor")
        if (
            not isinstance(anchor, Mapping)
            or anchor.get("resolution_method") != "observed_title_match"
        ):
            continue
        page = int(anchor["page"])
        if review_by_page[page]["text_flow_action"] != "include":
            continue
        group = tuple(str(value) for value in anchor["title_observation_ids"])
        matches = units_by_group.get(group, [])
        if (
            len(matches) != 1
            or matches[0]["unit_type"] != "heading"
            or matches[0]["pages"] != [page]
        ):
            raise ValidationError(
                f"direct Skeleton anchor {anchor['anchor_id']} lacks exact TextFlow mapping"
            )
