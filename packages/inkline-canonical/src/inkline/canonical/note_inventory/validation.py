from __future__ import annotations

from typing import Any

from inkline.canonical.artifact_dag.validation import (
    validate_choice,
    validate_exact_fields,
    validate_id_list,
    validate_metadata,
    validate_non_empty_string,
    validate_nullable_string,
    validate_ordered_ids,
    validate_ranges,
    validate_reason,
)
from inkline.canonical.note_inventory.contract import (
    DEFINITION_FIELDS,
    NOTE_GROUP_FIELDS,
    NOTE_INVENTORY_ISSUE_KINDS,
    NOTE_INVENTORY_SCHEMA_NAME,
    NOTE_INVENTORY_SCHEMA_VERSION,
    NOTE_REF_INLINE_RUN_FIELDS,
    REFERENCE_FIELDS,
    TOP_LEVEL_FIELDS,
    UNRESOLVED_CASE_FIELDS,
)
from inkline.canonical.schema import ValidationError
from inkline.canonical.text_flow import validate_text_flow


def validate_note_inventory(inventory: dict[str, Any]) -> None:
    """Validate note definitions, inline references, groups, and unresolved coverage."""

    validate_exact_fields(inventory, TOP_LEVEL_FIELDS, "note_inventory")
    validate_metadata(
        inventory["metadata"],
        schema_name=NOTE_INVENTORY_SCHEMA_NAME,
        schema_version=NOTE_INVENTORY_SCHEMA_VERSION,
        path="note_inventory.metadata",
    )
    definitions = _validate_definitions(inventory["definitions"])
    references = _validate_references(inventory["references"])
    groups = _validate_groups(inventory["note_groups"], definitions)
    _validate_definition_group_links(definitions, groups)
    _validate_unresolved(inventory["unresolved_cases"], definitions, references)


def validate_note_inventory_against_sources(
    inventory: dict[str, Any],
    text_flow: dict[str, Any],
    note_system_review: dict[str, Any],
    note_marker_review: dict[str, Any],
) -> None:
    """Validate TextUnit, inline-run, note-system, and marker-evidence references."""

    validate_note_inventory(inventory)
    validate_text_flow(text_flow)
    doc_id = inventory["metadata"]["doc_id"]
    for name, source in (
        ("TextFlow", text_flow),
        ("NoteSystemReview", note_system_review),
        ("NoteMarkerReview", note_marker_review),
    ):
        if source.get("metadata", {}).get("doc_id") != doc_id:
            raise ValidationError(f"{name} doc_id differs from NoteInventory")
    units = {unit["unit_id"]: unit for unit in text_flow["text_units"]}
    system_ids = {
        system["note_system_id"] for system in note_system_review.get("note_systems", [])
    }
    marker_ids = {
        marker["marker_evidence_id"]
        for outcome in note_marker_review.get("outcomes", [])
        for marker in outcome.get("markers", [])
    }
    system_evidence_ids = {
        evidence["evidence_id"] for evidence in note_system_review.get("evidence", [])
    }
    for definition in inventory["definitions"]:
        unit = units.get(definition["text_unit_id"])
        if unit is None or unit["unit_type"] != "footnote":
            raise ValidationError(
                f"note definition references non-footnote TextUnit: {definition['definition_id']}"
            )
        _validate_page_membership(definition["physical_page"], unit, "note definition")
        _validate_system_and_evidence(
            definition, system_ids, marker_ids, system_evidence_ids
        )
    inventoried_reference_locations: set[tuple[str, int]] = set()
    for reference in inventory["references"]:
        unit = units.get(reference["text_unit_id"])
        if unit is None:
            raise ValidationError(
                f"note reference has unknown TextUnit: {reference['reference_id']}"
            )
        _validate_page_membership(reference["physical_page"], unit, "note reference")
        _validate_reference_inline_run(reference, unit)
        _validate_system_and_evidence(
            reference, system_ids, marker_ids, system_evidence_ids
        )
        inventoried_reference_locations.add(
            (reference["text_unit_id"], reference["inline_run_index"])
        )
    if inventoried_reference_locations != _note_ref_locations(text_flow):
        raise ValidationError("NoteInventory must cover every TextFlow note_ref exactly once")


def _validate_definitions(value: Any) -> dict[str, dict[str, Any]]:
    records = validate_ordered_ids(
        value, id_field="definition_id", prefix="nd", path="note_inventory.definitions"
    )
    definitions: dict[str, dict[str, Any]] = {}
    unit_ids: set[str] = set()
    for index, record in enumerate(records):
        path = f"note_inventory.definitions[{index}]"
        validate_exact_fields(record, DEFINITION_FIELDS, path)
        text_unit_id = validate_non_empty_string(record["text_unit_id"], f"{path}.text_unit_id")
        if text_unit_id in unit_ids:
            raise ValidationError("one TextUnit cannot define multiple inventory notes")
        unit_ids.add(text_unit_id)
        _validate_positive_page(record["physical_page"], f"{path}.physical_page")
        validate_non_empty_string(record["note_system_id"], f"{path}.note_system_id")
        validate_non_empty_string(record["marker"], f"{path}.marker")
        validate_non_empty_string(record["normalized_marker"], f"{path}.normalized_marker")
        validate_nullable_string(record["note_group_id"], f"{path}.note_group_id")
        validate_id_list(record["evidence_ids"], f"{path}.evidence_ids", required=True)
        definitions[record["definition_id"]] = record
    return definitions


def _validate_references(value: Any) -> dict[str, dict[str, Any]]:
    records = validate_ordered_ids(
        value, id_field="reference_id", prefix="nr", path="note_inventory.references"
    )
    references: dict[str, dict[str, Any]] = {}
    locations: set[tuple[str, int]] = set()
    for index, record in enumerate(records):
        path = f"note_inventory.references[{index}]"
        validate_exact_fields(record, REFERENCE_FIELDS, path)
        text_unit_id = validate_non_empty_string(record["text_unit_id"], f"{path}.text_unit_id")
        run_index = record["inline_run_index"]
        if type(run_index) is not int or run_index < 0:
            raise ValidationError(f"{path}.inline_run_index is invalid")
        location = (text_unit_id, run_index)
        if location in locations:
            raise ValidationError("one inline run cannot define multiple inventory references")
        locations.add(location)
        _validate_positive_page(record["physical_page"], f"{path}.physical_page")
        validate_non_empty_string(record["note_system_id"], f"{path}.note_system_id")
        validate_non_empty_string(record["marker"], f"{path}.marker")
        validate_non_empty_string(record["normalized_marker"], f"{path}.normalized_marker")
        validate_id_list(record["evidence_ids"], f"{path}.evidence_ids", required=True)
        references[record["reference_id"]] = record
    return references


def _validate_groups(
    value: Any, definitions: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    records = validate_ordered_ids(
        value, id_field="note_group_id", prefix="ng", path="note_inventory.note_groups"
    )
    groups: dict[str, dict[str, Any]] = {}
    owned_definitions: set[str] = set()
    for index, record in enumerate(records):
        path = f"note_inventory.note_groups[{index}]"
        validate_exact_fields(record, NOTE_GROUP_FIELDS, path)
        validate_non_empty_string(record["note_system_id"], f"{path}.note_system_id")
        validate_id_list(record["heading_text_unit_ids"], f"{path}.heading_text_unit_ids")
        definition_ids = set(
            validate_id_list(record["definition_ids"], f"{path}.definition_ids", required=True)
        )
        if not definition_ids <= set(definitions):
            raise ValidationError(f"{path}.definition_ids contain unknown definitions")
        if owned_definitions & definition_ids:
            raise ValidationError("note definition cannot belong to multiple groups")
        owned_definitions.update(definition_ids)
        validate_ranges(record["physical_ranges"], f"{path}.physical_ranges", required=True)
        validate_id_list(record["evidence_ids"], f"{path}.evidence_ids", required=True)
        groups[record["note_group_id"]] = record
    return groups


def _validate_definition_group_links(
    definitions: dict[str, dict[str, Any]], groups: dict[str, dict[str, Any]]
) -> None:
    for definition_id, definition in definitions.items():
        group_id = definition["note_group_id"]
        if group_id is None:
            continue
        group = groups.get(group_id)
        if group is None or definition_id not in group["definition_ids"]:
            raise ValidationError(f"definition {definition_id} has inconsistent note_group_id")
        if definition["note_system_id"] != group["note_system_id"]:
            raise ValidationError(f"definition {definition_id} crosses note systems")


def _validate_unresolved(
    value: Any,
    definitions: dict[str, dict[str, Any]],
    references: dict[str, dict[str, Any]],
) -> None:
    records = validate_ordered_ids(
        value, id_field="case_id", prefix="niu", path="note_inventory.unresolved_cases"
    )
    for index, record in enumerate(records):
        path = f"note_inventory.unresolved_cases[{index}]"
        validate_exact_fields(record, UNRESOLVED_CASE_FIELDS, path)
        validate_choice(record["kind"], NOTE_INVENTORY_ISSUE_KINDS, f"{path}.kind")
        definition_ids = set(
            validate_id_list(record["definition_ids"], f"{path}.definition_ids")
        )
        reference_ids = set(
            validate_id_list(record["reference_ids"], f"{path}.reference_ids")
        )
        if not definition_ids and not reference_ids:
            raise ValidationError(f"{path} must reference an inventory record")
        if not definition_ids <= set(definitions) or not reference_ids <= set(references):
            raise ValidationError(f"{path} references unknown inventory records")
        validate_id_list(record["evidence_ids"], f"{path}.evidence_ids", required=True)
        validate_reason(record["reason"], f"{path}.reason")


def _validate_reference_inline_run(
    reference: dict[str, Any], unit: dict[str, Any]
) -> None:
    runs = unit["attrs"].get("inline_runs", [])
    index = reference["inline_run_index"]
    if not isinstance(runs, list) or index >= len(runs):
        raise ValidationError("note reference points outside TextFlow inline_runs")
    run = runs[index]
    validate_exact_fields(run, NOTE_REF_INLINE_RUN_FIELDS, "note_ref inline run")
    if (
        run["type"] != "note_ref"
        or run["marker"] != reference["marker"]
        or run["source_page"] != reference["physical_page"]
        or run["target_note_id"] is not None
        or run["resolution_status"] != "unresolved"
    ):
        raise ValidationError("note reference differs from unresolved TextFlow inline run")
    validate_id_list(run["evidence_ids"], "note_ref inline run.evidence_ids", required=True)


def _note_ref_locations(text_flow: dict[str, Any]) -> set[tuple[str, int]]:
    return {
        (unit["unit_id"], index)
        for unit in text_flow["text_units"]
        for index, run in enumerate(unit["attrs"].get("inline_runs", []))
        if isinstance(run, dict) and run.get("type") == "note_ref"
    }


def _validate_system_and_evidence(
    record: dict[str, Any],
    system_ids: set[str],
    marker_ids: set[str],
    system_evidence_ids: set[str],
) -> None:
    if record["note_system_id"] not in system_ids:
        raise ValidationError("NoteInventory references unknown note system")
    evidence_ids = set(record["evidence_ids"])
    if not evidence_ids <= marker_ids | system_evidence_ids:
        raise ValidationError("NoteInventory references unknown note evidence")
    if not evidence_ids & marker_ids:
        raise ValidationError("NoteInventory record lacks marker evidence")


def _validate_positive_page(value: Any, path: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{path} is invalid")


def _validate_page_membership(page: int, unit: dict[str, Any], noun: str) -> None:
    if page not in unit["pages"]:
        raise ValidationError(f"{noun} page differs from TextFlow provenance")
