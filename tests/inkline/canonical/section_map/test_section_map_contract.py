from __future__ import annotations

from copy import deepcopy

import pytest

from inkline.canonical import (
    ValidationError,
    build_book_skeleton_from_observed,
    build_text_units,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.section_map import (
    validate_section_map,
    validate_section_map_against_sources,
    validate_section_map_evidence,
)


def test_validate_section_map_evidence_rejects_membership_fields() -> None:
    evidence = {
        "metadata": {
            "schema_name": "inkline_section_map_evidence",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "sections": [],
        "text_flow_order": [],
        "page_review_pages": [],
        "text_unit_ids": [],
    }

    with pytest.raises(ValidationError, match="top-level fields"):
        validate_section_map_evidence(evidence)


def _section_map() -> dict:
    return {
        "metadata": {
            "schema_name": "inkline_section_map",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "sections": [
            {
                "section_id": "s000000",
                "title": "第一章",
                "level": 1,
                "parent_section_id": None,
                "skeleton_entry_index": 0,
                "anchor_evidence_ids": ["sa000000", "obs000001", "obs000002"],
                "title_text_unit_ids": ["tu000001"],
                "physical_ranges": [[3, 4]],
                "text_unit_ids": ["tu000001", "tu000002"],
                "table_ids": [],
                "visual_group_ids": [],
                "note_group_ids": [],
                "attached_visual_pages": [],
                "evidence_ids": ["sa000000", "tu000001", "tu000002"],
                "decision_source": "structural_rule",
                "confidence": "high",
            }
        ],
        "page_placements": [
            {
                "page": 3,
                "placement": "section_member",
                "section_id": "s000000",
                "reason": "confirmed_text_flow",
                "evidence_ids": ["tu000001"],
                "decision_source": "structural_rule",
                "confidence": "high",
            }
        ],
        "resource_placements": [],
    }


def test_validate_section_map_accepts_confirmed_direct_section() -> None:
    validate_section_map(_section_map())


def test_validate_section_map_rejects_invalid_section_tree() -> None:
    cases = []

    malformed_id = _section_map()
    malformed_id["sections"][0]["section_id"] = "section-0"
    cases.append(malformed_id)

    duplicate_id = _section_map()
    duplicate_id["sections"].append(deepcopy(duplicate_id["sections"][0]))
    cases.append(duplicate_id)

    dangling_parent = _section_map()
    dangling_parent["sections"][0]["parent_section_id"] = "s000001"
    cases.append(dangling_parent)

    wrong_canonical_id = _section_map()
    wrong_canonical_id["sections"][0]["section_id"] = "s000001"
    cases.append(wrong_canonical_id)

    for section_map in cases:
        with pytest.raises(ValidationError):
            validate_section_map(section_map)

    cycle = _section_map()
    cycle["sections"].append(
        {
            **deepcopy(cycle["sections"][0]),
            "section_id": "s000001",
            "skeleton_entry_index": 1,
            "parent_section_id": "s000000",
            "level": 2,
            "title_text_unit_ids": [],
            "text_unit_ids": [],
            "table_ids": [],
            "visual_group_ids": [],
            "note_group_ids": [],
            "attached_visual_pages": [],
        }
    )
    cycle["sections"][0]["parent_section_id"] = "s000001"
    with pytest.raises(ValidationError, match="section parent graph must be acyclic"):
        validate_section_map(cycle)

    invalid_parent_level = _section_map()
    invalid_parent_level["sections"].append(
        {
            **deepcopy(invalid_parent_level["sections"][0]),
            "section_id": "s000001",
            "skeleton_entry_index": 1,
            "parent_section_id": "s000000",
            "level": 1,
            "title_text_unit_ids": [],
            "text_unit_ids": [],
            "table_ids": [],
            "visual_group_ids": [],
            "note_group_ids": [],
            "attached_visual_pages": [],
        }
    )
    with pytest.raises(ValidationError, match="parent level must be lower"):
        validate_section_map(invalid_parent_level)


def test_validate_section_map_rejects_invalid_physical_ranges() -> None:
    for ranges in ([[0, 1]], [[4, 3]], [[3, 4], [4, 5]], [[5, 6], [3, 4]]):
        section_map = _section_map()
        section_map["sections"][0]["physical_ranges"] = ranges
        with pytest.raises(ValidationError):
            validate_section_map(section_map)


def test_validate_section_map_rejects_conflicting_page_placements() -> None:
    cases = []

    duplicate_page = _section_map()
    duplicate_page["page_placements"].append(deepcopy(duplicate_page["page_placements"][0]))
    cases.append(duplicate_page)

    dangling_section = _section_map()
    dangling_section["page_placements"][0]["section_id"] = "s000001"
    cases.append(dangling_section)

    non_member_has_section = _section_map()
    non_member_has_section["page_placements"][0]["placement"] = "standalone"
    cases.append(non_member_has_section)

    member_without_section = _section_map()
    member_without_section["page_placements"][0]["section_id"] = None
    cases.append(member_without_section)

    member_outside_range = _section_map()
    member_outside_range["page_placements"][0]["page"] = 5
    cases.append(member_outside_range)

    range_only_member = _section_map()
    range_only_member["page_placements"][0]["evidence_ids"] = ["sa000000"]
    cases.append(range_only_member)

    for section_map in cases:
        with pytest.raises(ValidationError):
            validate_section_map(section_map)


def test_validate_section_map_rejects_evidence_free_decision() -> None:
    cases = []
    for field, value in (
        ("evidence_ids", []),
        ("evidence_ids", ["tu000001", "tu000001"]),
        ("evidence_ids", [1]),
        ("decision_source", "guessed"),
        ("confidence", "certain"),
    ):
        section_map = _section_map()
        section_map["sections"][0][field] = value
        cases.append(section_map)

    missing_reason = _section_map()
    missing_reason["page_placements"][0]["reason"] = ""
    cases.append(missing_reason)

    for section_map in cases:
        with pytest.raises(ValidationError):
            validate_section_map(section_map)


def _direct_sources() -> tuple[dict, list[dict], dict, dict]:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "test-parser",
            "parser_mode": "structured",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 4)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\nChapter One 1",
                page=1,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Chapter One",
                page=2,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Confirmed body text.",
                page=3,
                role_hint="body_text",
            ),
        ],
    )
    skeleton = build_book_skeleton_from_observed(document)
    text_units, _ignored = build_text_units(document)
    return skeleton, text_units, document, _page_review("sample", [1, 2, 3])


def _offset_sources() -> tuple[dict, list[dict], dict, dict]:
    document = make_observed_document(
        {
            "doc_id": "offset-sample",
            "title": "Offset Sample",
            "language": "en",
            "source_file": "offset-sample.pdf",
            "parser_name": "test-parser",
            "parser_mode": "structured",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 50)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="目录\nArthur 3\nCathedral Guide 15\nCharlemagne 31",
                page=1,
                role_hint="toc_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Arthur",
                page=15,
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Charlemagne",
                page=43,
                role_hint="title_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="Cathedral guide opening body.",
                page=27,
                role_hint="body_text",
            ),
        ],
    )
    skeleton = build_book_skeleton_from_observed(document)
    text_units, _ignored = build_text_units(document)
    return skeleton, text_units, document, _page_review("offset-sample", list(range(1, 50)))


def _page_review(doc_id: str, pages: list[int]) -> dict:
    return {
        "metadata": {
            "schema_name": "inkline_page_review",
            "schema_version": "1.4-shadow",
            "doc_id": doc_id,
        },
        "candidate_pages": [],
        "pages": [
            {
                "page": page,
                "page_role": "text_flow_page",
                "book_block_position": "body",
                "special_page_kind": None,
                "text_flow_action": "include",
                "visual_asset_action": "not_needed",
                "decision_source": "layout_and_skeleton",
                "llm_review_status": "not_selected",
                "signals": [],
            }
            for page in pages
        ],
    }


def _map_for_entry(skeleton: dict, text_units: list[dict], entry_index: int = 0) -> dict:
    entry = skeleton["toc_entries"][entry_index]
    anchor = entry["selected_start_anchor"]
    assert anchor is not None
    title_unit = next(
        unit for unit in text_units if unit["observation_ids"] == anchor["title_observation_ids"]
    )
    return {
        "metadata": {
            "schema_name": "inkline_section_map",
            "schema_version": "0.1-shadow",
            "doc_id": skeleton["metadata"]["doc_id"],
        },
        "sections": [
            {
                "section_id": f"s{entry_index:06d}",
                "title": entry["display_title"],
                "level": entry["level"],
                "parent_section_id": None,
                "skeleton_entry_index": entry_index,
                "anchor_evidence_ids": [
                    anchor["anchor_id"],
                    *anchor["title_observation_ids"],
                    *anchor["toc_observation_ids"],
                ],
                "title_text_unit_ids": [title_unit["unit_id"]],
                "physical_ranges": [[anchor["page"], anchor["page"] + 1]],
                "text_unit_ids": [title_unit["unit_id"]],
                "table_ids": [],
                "visual_group_ids": [],
                "note_group_ids": [],
                "attached_visual_pages": [],
                "evidence_ids": [anchor["anchor_id"], title_unit["unit_id"]],
                "decision_source": "structural_rule",
                "confidence": "high",
            }
        ],
        "page_placements": [
            {
                "page": anchor["page"],
                "placement": "section_member",
                "section_id": f"s{entry_index:06d}",
                "reason": "confirmed_text_flow",
                "evidence_ids": [title_unit["unit_id"]],
                "decision_source": "structural_rule",
                "confidence": "high",
            }
        ],
        "resource_placements": [],
    }


def _offset_map(skeleton: dict, text_units: list[dict]) -> dict:
    entry_index = 1
    entry = skeleton["toc_entries"][entry_index]
    anchor = entry["selected_start_anchor"]
    assert anchor is not None
    assert anchor["resolution_method"] == "printed_page_offset"
    body_unit = next(unit for unit in text_units if unit["page"] == anchor["page"])
    return {
        "metadata": {
            "schema_name": "inkline_section_map",
            "schema_version": "0.1-shadow",
            "doc_id": skeleton["metadata"]["doc_id"],
        },
        "sections": [
            {
                "section_id": "s000001",
                "title": entry["display_title"],
                "level": entry["level"],
                "parent_section_id": None,
                "skeleton_entry_index": 1,
                "anchor_evidence_ids": [
                    anchor["anchor_id"],
                    *anchor["toc_observation_ids"],
                    *anchor["supporting_anchor_ids"],
                ],
                "title_text_unit_ids": [],
                "physical_ranges": [[anchor["page"], anchor["page"]]],
                "text_unit_ids": [body_unit["unit_id"]],
                "table_ids": [],
                "visual_group_ids": [],
                "note_group_ids": [],
                "attached_visual_pages": [],
                "evidence_ids": [anchor["anchor_id"], body_unit["unit_id"]],
                "decision_source": "structural_rule",
                "confidence": "medium",
            }
        ],
        "page_placements": [
            {
                "page": anchor["page"],
                "placement": "section_member",
                "section_id": "s000001",
                "reason": "confirmed_text_flow",
                "evidence_ids": [body_unit["unit_id"]],
                "decision_source": "structural_rule",
                "confidence": "medium",
            }
        ],
        "resource_placements": [],
    }


def test_validate_section_map_against_sources_accepts_direct_anchor_mapping() -> None:
    skeleton, text_units, document, page_review = _direct_sources()

    validate_section_map_against_sources(
        _map_for_entry(skeleton, text_units), skeleton, text_units, document, page_review
    )


def test_validate_section_map_against_sources_rejects_wrong_page_review_schema_name() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    page_review["metadata"]["schema_name"] = "legacy_page_review"

    with pytest.raises(ValidationError, match="page_review metadata schema_name"):
        validate_section_map_against_sources(
            _map_for_entry(skeleton, text_units), skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_wrong_page_review_schema_version() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    page_review["metadata"]["schema_version"] = "0.1-shadow"

    with pytest.raises(ValidationError, match="page_review metadata schema_version"):
        validate_section_map_against_sources(
            _map_for_entry(skeleton, text_units), skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_dangling_skeleton_entry() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    section_map = _map_for_entry(skeleton, text_units)
    section_map["sections"][0]["section_id"] = "s000001"
    section_map["sections"][0]["skeleton_entry_index"] = 1
    section_map["page_placements"][0]["section_id"] = "s000001"

    with pytest.raises(ValidationError):
        validate_section_map_against_sources(
            section_map, skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_unknown_text_unit() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    section_map = _map_for_entry(skeleton, text_units)
    section_map["sections"][0]["title_text_unit_ids"] = ["tu999999"]
    section_map["sections"][0]["text_unit_ids"] = ["tu999999"]
    section_map["sections"][0]["evidence_ids"] = ["sa000000", "tu999999"]
    section_map["page_placements"][0]["evidence_ids"] = ["tu999999"]

    with pytest.raises(ValidationError):
        validate_section_map_against_sources(
            section_map, skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_unknown_evidence() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    section_map = _map_for_entry(skeleton, text_units)
    section_map["sections"][0]["evidence_ids"].append("unknown-evidence")

    with pytest.raises(ValidationError):
        validate_section_map_against_sources(
            section_map, skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_fabricated_direct_title_unit() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    section_map = _map_for_entry(skeleton, text_units)
    body_unit = next(unit for unit in text_units if unit["page"] == 3)
    section_map["sections"][0]["title_text_unit_ids"] = [body_unit["unit_id"]]
    section_map["sections"][0]["text_unit_ids"].append(body_unit["unit_id"])

    with pytest.raises(ValidationError):
        validate_section_map_against_sources(
            section_map, skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_accepts_offset_anchor_without_title_unit() -> None:
    skeleton, text_units, document, page_review = _offset_sources()

    validate_section_map_against_sources(
        _offset_map(skeleton, text_units), skeleton, text_units, document, page_review
    )


def test_validate_section_map_against_sources_rejects_offset_anchor_title_unit() -> None:
    skeleton, text_units, document, page_review = _offset_sources()
    section_map = _offset_map(skeleton, text_units)
    body_unit = section_map["sections"][0]["text_unit_ids"][0]
    section_map["sections"][0]["title_text_unit_ids"] = [body_unit]

    with pytest.raises(ValidationError):
        validate_section_map_against_sources(
            section_map, skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_range_only_membership() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    section_map = _map_for_entry(skeleton, text_units)
    section_map["page_placements"][0]["page"] = 3

    with pytest.raises(ValidationError):
        validate_section_map_against_sources(
            section_map, skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_wrong_page_text_unit_evidence() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    section_map = _map_for_entry(skeleton, text_units)
    body_unit = next(unit for unit in text_units if unit["page"] == 3)
    section_map["sections"][0]["text_unit_ids"].append(body_unit["unit_id"])
    section_map["page_placements"][0]["evidence_ids"] = [body_unit["unit_id"]]

    with pytest.raises(ValidationError, match="page-local TextUnit evidence"):
        validate_section_map_against_sources(
            section_map, skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_unrelated_visual_evidence() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    section_map = _map_for_entry(skeleton, text_units)
    section_map["sections"][0]["attached_visual_pages"] = [3]
    section_map["page_placements"] = [
        {
            "page": 3,
            "placement": "section_member",
            "section_id": "s000000",
            "reason": "confirmed_visual_page",
            "evidence_ids": ["obs000003"],
            "decision_source": "structural_rule",
            "confidence": "high",
        }
    ]

    with pytest.raises(ValidationError, match="range containment alone"):
        validate_section_map_against_sources(
            section_map, skeleton, text_units, document, page_review
        )


@pytest.mark.parametrize("invalid_page", [None, "3", True])
def test_validate_section_map_against_sources_rejects_invalid_page_review_page(
    invalid_page: object,
) -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    page_review["pages"][0]["page"] = invalid_page

    with pytest.raises(ValidationError, match=r"page_review.pages\[0\].page"):
        validate_section_map_against_sources(
            _map_for_entry(skeleton, text_units), skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_duplicate_page_review_page() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    page_review["pages"].append(deepcopy(page_review["pages"][0]))

    with pytest.raises(ValidationError, match="duplicate page_review page"):
        validate_section_map_against_sources(
            _map_for_entry(skeleton, text_units), skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_out_of_document_page_review_page() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    page_review["pages"].append({**deepcopy(page_review["pages"][0]), "page": 999})
    section_map = _map_for_entry(skeleton, text_units)
    section_map["sections"][0]["evidence_ids"].append("page_review:999")

    with pytest.raises(ValidationError, match="page_review page is outside ObservedDocument"):
        validate_section_map_against_sources(
            section_map, skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_unknown_text_unit_type() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    text_units[0]["unit_type"] = "unrecognized_unit_type"

    with pytest.raises(ValidationError, match=r"text_units\[0\].unit_type"):
        validate_section_map_against_sources(
            _map_for_entry(skeleton, text_units), skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_rejects_unhashable_text_unit_type() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    text_units[0]["unit_type"] = []

    with pytest.raises(ValidationError, match=r"text_units\[0\].unit_type"):
        validate_section_map_against_sources(
            _map_for_entry(skeleton, text_units), skeleton, text_units, document, page_review
        )


def test_validate_section_map_against_sources_allows_standalone_exception_inside_range() -> None:
    skeleton, text_units, document, page_review = _direct_sources()
    section_map = _map_for_entry(skeleton, text_units)
    section_map["page_placements"].append(
        {
            "page": 3,
            "placement": "standalone",
            "section_id": None,
            "reason": "explicit_special_page",
            "evidence_ids": ["page_review:3"],
            "decision_source": "structural_rule",
            "confidence": "high",
        }
    )

    validate_section_map_against_sources(section_map, skeleton, text_units, document, page_review)
