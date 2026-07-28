from __future__ import annotations

from typing import Any

from inkline.canonical.schema import ValidationError
from inkline.canonical.section_map.evidence import validate_section_map_evidence

STANDALONE_SPECIAL_PAGE_KINDS = {
    "front_exterior_page",
    "back_exterior_page",
    "cover_flap",
    "dust_jacket_spread",
    "half_title_page",
    "title_page",
    "decorative_preliminary_page",
    "decorative_title_page",
    "epigraph_page",
    "dedication_page",
    "copyright_page",
    "toc_page",
    "blank_page",
}
PLACEMENT_FIELDS = {
    "page",
    "placement",
    "section_id",
    "reason",
    "evidence_ids",
    "decision_source",
    "confidence",
}


def build_section_map_placements(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Place pages using explicit identities and local starts, never inferred ranges."""

    validate_section_map_evidence(evidence)
    starts_by_page = _mapped_starts_by_page(evidence["sections"])
    placements = [
        _place_page(record, starts_by_page.get(int(record["page"]), []))
        for record in evidence["page_review_pages"]
    ]
    validate_section_map_placements(placements, evidence)
    return placements


def validate_section_map_placements(
    placements: list[dict[str, Any]], evidence: dict[str, Any]
) -> None:
    validate_section_map_evidence(evidence)
    if not isinstance(placements, list):
        raise ValidationError("SectionMap placements must be list")
    expected_pages = [record["page"] for record in evidence["page_review_pages"]]
    if [record.get("page") for record in placements] != expected_pages:
        raise ValidationError("SectionMap placements must cover every reviewed page in order")
    sections = {section["section_id"]: section for section in evidence["sections"]}
    text_flow_order = set(evidence["text_flow_order"])
    for index, placement in enumerate(placements):
        _validate_placement(placement, index, sections, text_flow_order)


def _mapped_starts_by_page(sections: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    starts: dict[int, list[dict[str, Any]]] = {}
    for section in sections:
        start = section["start_evidence"]
        if start["text_flow_status"] != "mapped":
            continue
        starts.setdefault(int(start["page"]), []).append(section)
    return starts


def _place_page(record: dict[str, Any], starts: list[dict[str, Any]]) -> dict[str, Any]:
    page = int(record["page"])
    page_evidence = f"page_review:{page}"
    if _confirmed_standalone(record):
        return _placement(
            page,
            "standalone",
            None,
            "confirmed_special_page_identity",
            [page_evidence],
            "high",
        )
    if len(starts) == 1:
        section = starts[0]
        title_unit_id = section["start_evidence"]["title_text_unit_id"]
        return _placement(
            page,
            "section_member",
            section["section_id"],
            "single_local_direct_section_start",
            [title_unit_id, page_evidence],
            "high",
        )
    reason = (
        "conflicting_local_section_starts" if len(starts) > 1 else "no_local_membership_evidence"
    )
    return _placement(page, "unresolved", None, reason, [page_evidence], "low")


def _confirmed_standalone(record: dict[str, Any]) -> bool:
    return record["book_block_position"] == "external_wrap" or (
        record["special_page_kind"] in STANDALONE_SPECIAL_PAGE_KINDS
    )


def _placement(
    page: int,
    placement: str,
    section_id: str | None,
    reason: str,
    evidence_ids: list[str],
    confidence: str,
) -> dict[str, Any]:
    return {
        "page": page,
        "placement": placement,
        "section_id": section_id,
        "reason": reason,
        "evidence_ids": evidence_ids,
        "decision_source": "structural_rule",
        "confidence": confidence,
    }


def _validate_placement(
    placement: dict[str, Any],
    index: int,
    sections: dict[str, dict[str, Any]],
    text_flow_order: set[str],
) -> None:
    if not isinstance(placement, dict) or set(placement) != PLACEMENT_FIELDS:
        raise ValidationError(f"SectionMap placements[{index}] has invalid fields")
    kind = placement["placement"]
    section_id = placement["section_id"]
    evidence_ids = placement["evidence_ids"]
    if kind not in {"section_member", "standalone", "unresolved"}:
        raise ValidationError(f"SectionMap placements[{index}] kind is invalid")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise ValidationError(f"SectionMap placements[{index}] requires evidence")
    if kind == "section_member":
        section = sections.get(section_id)
        if section is None:
            raise ValidationError(f"SectionMap placements[{index}] section is invalid")
        title_unit_id = section["start_evidence"]["title_text_unit_id"]
        if title_unit_id not in evidence_ids or title_unit_id not in text_flow_order:
            raise ValidationError(f"SectionMap placements[{index}] lacks local TextFlow evidence")
    elif section_id is not None:
        raise ValidationError(f"SectionMap placements[{index}] non-member section must be null")
