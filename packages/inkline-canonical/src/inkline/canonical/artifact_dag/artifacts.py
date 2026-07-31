from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from inkline.canonical.observed.index import ObservedIndex
from inkline.canonical.schema import ValidationError


@dataclass(frozen=True)
class CanonicalArtifactBundle:
    """Immutable references to one coherent set of canonical pipeline artifacts."""

    observed: dict[str, Any]
    observed_index: ObservedIndex
    skeleton: dict[str, Any]
    page_layout: dict[str, Any]
    page_review: dict[str, Any]
    table_flow: dict[str, Any] | None
    text_flow: dict[str, Any] | None
    page_assets: dict[str, Any] | None
    visual_relation_review: dict[str, Any] | None = None
    note_system_review: dict[str, Any] | None = None
    note_marker_review_plan: dict[str, Any] | None = None
    note_marker_review: dict[str, Any] | None = None
    note_inventory: dict[str, Any] | None = None
    section_map: dict[str, Any] | None = None
    note_resolution: dict[str, Any] | None = None


def validate_complete_artifact_bundle(bundle: CanonicalArtifactBundle) -> None:
    """Require every frozen target artifact before final BookGraph assembly."""

    required = {
        "page_assets": bundle.page_assets,
        "visual_relation_review": bundle.visual_relation_review,
        "note_system_review": bundle.note_system_review,
        "note_marker_review_plan": bundle.note_marker_review_plan,
        "note_marker_review": bundle.note_marker_review,
        "table_flow": bundle.table_flow,
        "text_flow": bundle.text_flow,
        "note_inventory": bundle.note_inventory,
        "section_map": bundle.section_map,
        "note_resolution": bundle.note_resolution,
    }
    missing = sorted(name for name, artifact in required.items() if artifact is None)
    if missing:
        raise ValidationError(f"canonical artifact bundle is incomplete: {missing}")
    doc_id = bundle.observed_index.doc_id
    for name, artifact in required.items():
        if (
            name != "page_assets"
            and artifact is not None
            and artifact.get("metadata", {}).get("doc_id") != doc_id
        ):
            raise ValidationError(f"{name} doc_id differs from canonical artifact bundle")
    _validate_completed_artifacts(bundle)


def _validate_completed_artifacts(bundle: CanonicalArtifactBundle) -> None:
    from inkline.canonical.note_inventory import (
        validate_note_inventory,
        validate_note_inventory_against_sources,
    )
    from inkline.canonical.note_marker_review import (
        validate_note_marker_review,
        validate_note_marker_review_plan,
    )
    from inkline.canonical.note_resolution import (
        validate_note_resolution,
        validate_note_resolution_against_sources,
    )
    from inkline.canonical.note_system import validate_note_system_review
    from inkline.canonical.section_map import (
        validate_section_map,
        validate_section_map_artifact_links,
    )
    from inkline.canonical.table_flow import validate_table_flow
    from inkline.canonical.text_flow import (
        validate_final_text_flow_artifact_links,
        validate_text_flow,
    )
    from inkline.canonical.visual_relations import validate_visual_relation_review

    visual = _required_artifact(bundle.visual_relation_review)
    systems = _required_artifact(bundle.note_system_review)
    plan = _required_artifact(bundle.note_marker_review_plan)
    markers = _required_artifact(bundle.note_marker_review)
    tables = _required_artifact(bundle.table_flow)
    text = _required_artifact(bundle.text_flow)
    inventory = _required_artifact(bundle.note_inventory)
    sections = _required_artifact(bundle.section_map)
    resolution = _required_artifact(bundle.note_resolution)
    validate_visual_relation_review(visual)
    validate_note_system_review(systems)
    validate_note_marker_review_plan(plan)
    validate_note_marker_review(markers)
    validate_table_flow(tables)
    validate_text_flow(text)
    validate_final_text_flow_artifact_links(text, visual, systems, markers)
    validate_note_inventory(inventory)
    validate_note_inventory_against_sources(inventory, text, systems, markers)
    validate_section_map(sections)
    validate_section_map_artifact_links(sections, text, tables, visual, inventory)
    validate_note_resolution(resolution)
    validate_note_resolution_against_sources(resolution, inventory, sections)


def _required_artifact(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        raise AssertionError("complete artifact validation requires non-null artifacts")
    return value
