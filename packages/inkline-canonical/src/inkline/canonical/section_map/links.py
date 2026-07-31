from __future__ import annotations

from typing import Any

from inkline.canonical.schema import ValidationError
from inkline.canonical.section_map.validation import validate_section_map


def validate_section_map_artifact_links(
    section_map: dict[str, Any],
    text_flow: dict[str, Any],
    table_flow: dict[str, Any],
    visual_relation_review: dict[str, Any],
    note_inventory: dict[str, Any],
) -> None:
    """Validate complete, single-state placement of every logical upstream resource."""

    validate_section_map(section_map)
    doc_id = section_map["metadata"]["doc_id"]
    for name, source in (
        ("TextFlow", text_flow),
        ("TableFlow", table_flow),
        ("VisualRelationReview", visual_relation_review),
        ("NoteInventory", note_inventory),
    ):
        if source.get("metadata", {}).get("doc_id") != doc_id:
            raise ValidationError(f"{name} doc_id differs from SectionMap")
    known = {
        "text_unit": {unit["unit_id"] for unit in text_flow.get("text_units", [])},
        "table": {table["table_id"] for table in table_flow.get("tables", [])},
        "visual_group": {
            group["visual_group_id"]
            for group in visual_relation_review.get("visual_groups", [])
        },
        "note_group": {
            group["note_group_id"] for group in note_inventory.get("note_groups", [])
        },
    }
    placed = {resource_type: set() for resource_type in known}
    for placement in section_map["resource_placements"]:
        resource_type = placement["resource_type"]
        resource_id = placement["resource_id"]
        if resource_id not in known[resource_type]:
            raise ValidationError(
                f"SectionMap resource placement references unknown {resource_type}: {resource_id}"
            )
        placed[resource_type].add(resource_id)
    for resource_type, ids in known.items():
        if placed[resource_type] != ids:
            raise ValidationError(
                f"SectionMap must place every {resource_type} as member, standalone, or unresolved"
            )
