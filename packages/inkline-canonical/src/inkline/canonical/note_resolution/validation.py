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
    validate_reason,
)
from inkline.canonical.note_resolution.contract import (
    NOTE_RESOLUTION_DECISION_SOURCES,
    NOTE_RESOLUTION_SCHEMA_NAME,
    NOTE_RESOLUTION_SCHEMA_VERSION,
    NOTE_RESOLUTION_SCOPES,
    RELATION_FIELDS,
    TOP_LEVEL_FIELDS,
    UNRESOLVED_REFERENCE_FIELDS,
)
from inkline.canonical.schema import ValidationError
from inkline.canonical.section_map import validate_section_map


def validate_note_resolution(resolution: dict[str, Any]) -> None:
    """Validate immutable resolved relations and explicit unresolved references."""

    validate_exact_fields(resolution, TOP_LEVEL_FIELDS, "note_resolution")
    validate_metadata(
        resolution["metadata"],
        schema_name=NOTE_RESOLUTION_SCHEMA_NAME,
        schema_version=NOTE_RESOLUTION_SCHEMA_VERSION,
        path="note_resolution.metadata",
    )
    resolved_references = _validate_relations(resolution["relations"])
    unresolved_references = _validate_unresolved(resolution["unresolved_references"])
    if resolved_references & unresolved_references:
        raise ValidationError("note reference cannot be both resolved and unresolved")


def validate_note_resolution_against_sources(
    resolution: dict[str, Any],
    note_inventory: dict[str, Any],
    section_map: dict[str, Any],
) -> None:
    """Validate complete reference coverage, identity, and page/chapter/book scope."""

    validate_note_resolution(resolution)
    validate_section_map(section_map)
    doc_id = resolution["metadata"]["doc_id"]
    for name, source in (("NoteInventory", note_inventory), ("SectionMap", section_map)):
        if source.get("metadata", {}).get("doc_id") != doc_id:
            raise ValidationError(f"{name} doc_id differs from NoteResolution")
    references = {
        reference["reference_id"]: reference for reference in note_inventory["references"]
    }
    definitions = {
        definition["definition_id"]: definition for definition in note_inventory["definitions"]
    }
    source_evidence_by_reference = {
        reference["reference_id"]: set(reference.get("evidence_ids", []))
        for reference in note_inventory["references"]
    }
    target_evidence_by_definition = {
        definition["definition_id"]: set(definition.get("evidence_ids", []))
        for definition in note_inventory["definitions"]
    }
    section_by_text_unit = _section_by_member(section_map, "text_unit_ids")
    sections_by_id = {
        section["section_id"]: section for section in section_map["sections"]
    }
    for relation in resolution["relations"]:
        reference = references.get(relation["reference_id"])
        definition = definitions.get(relation["target_definition_id"])
        if reference is None or definition is None:
            raise ValidationError("NoteResolution relation has dangling inventory id")
        _validate_relation_identity(relation, reference, definition)
        _validate_relation_sections(
            relation,
            reference,
            definition,
            section_by_text_unit,
            sections_by_id,
        )
        if "evidence_ids" in reference and "evidence_ids" in definition:
            expected_evidence = (
                source_evidence_by_reference[reference["reference_id"]]
                | target_evidence_by_definition[definition["definition_id"]]
                | set(sections_by_id[section_id]["evidence_ids"])
                for section_id in {
                    relation["source_section_id"],
                    relation["target_section_id"],
                    relation["scope_section_id"],
                }
                if section_id is not None
            )
            if not set(relation["evidence_ids"]) <= set().union(*expected_evidence):
                raise ValidationError("NoteResolution relation has unrelated evidence")
    for unresolved in resolution["unresolved_references"]:
        reference = references.get(unresolved["reference_id"])
        if reference is None or reference["note_system_id"] != unresolved["note_system_id"]:
            raise ValidationError("NoteResolution unresolved reference is invalid")
        if not set(unresolved["candidate_definition_ids"]) <= set(definitions):
            raise ValidationError("NoteResolution has unknown candidate definition")
        if "evidence_ids" in reference and all(
            "evidence_ids" in definitions[candidate]
            for candidate in unresolved["candidate_definition_ids"]
        ):
            expected_evidence = source_evidence_by_reference[unresolved["reference_id"]] | set().union(
                *(target_evidence_by_definition[candidate] for candidate in unresolved["candidate_definition_ids"])
            )
            if not set(unresolved["evidence_ids"]) <= expected_evidence:
                raise ValidationError("NoteResolution unresolved reference has unrelated evidence")
    covered = {
        relation["reference_id"] for relation in resolution["relations"]
    } | {
        unresolved["reference_id"] for unresolved in resolution["unresolved_references"]
    }
    if covered != set(references):
        raise ValidationError("NoteResolution must partition every inventory reference")


def _validate_relations(value: Any) -> set[str]:
    records = validate_ordered_ids(
        value, id_field="relation_id", prefix="nrel", path="note_resolution.relations"
    )
    reference_ids: set[str] = set()
    for index, record in enumerate(records):
        path = f"note_resolution.relations[{index}]"
        validate_exact_fields(record, RELATION_FIELDS, path)
        reference_id = validate_non_empty_string(record["reference_id"], f"{path}.reference_id")
        if reference_id in reference_ids:
            raise ValidationError("one note reference cannot have multiple resolved targets")
        reference_ids.add(reference_id)
        validate_non_empty_string(
            record["source_text_unit_id"], f"{path}.source_text_unit_id"
        )
        run_index = record["source_inline_run_index"]
        if type(run_index) is not int or run_index < 0:
            raise ValidationError(f"{path}.source_inline_run_index is invalid")
        validate_nullable_string(record["source_section_id"], f"{path}.source_section_id")
        validate_nullable_string(record["scope_section_id"], f"{path}.scope_section_id")
        validate_non_empty_string(record["marker"], f"{path}.marker")
        validate_non_empty_string(
            record["target_definition_id"], f"{path}.target_definition_id"
        )
        validate_non_empty_string(
            record["target_note_unit_id"], f"{path}.target_note_unit_id"
        )
        validate_nullable_string(record["target_section_id"], f"{path}.target_section_id")
        validate_non_empty_string(record["note_system_id"], f"{path}.note_system_id")
        scope = validate_choice(record["scope"], NOTE_RESOLUTION_SCOPES, f"{path}.scope")
        validate_id_list(record["evidence_ids"], f"{path}.evidence_ids", required=True)
        decision_source = validate_choice(
            record["decision_source"],
            NOTE_RESOLUTION_DECISION_SOURCES,
            f"{path}.decision_source",
        )
        if scope not in decision_source:
            raise ValidationError(f"{path}.decision_source differs from scope")
    return reference_ids


def _validate_unresolved(value: Any) -> set[str]:
    if not isinstance(value, list):
        raise ValidationError("note_resolution.unresolved_references must be list")
    reference_ids: set[str] = set()
    for index, record in enumerate(value):
        path = f"note_resolution.unresolved_references[{index}]"
        validate_exact_fields(record, UNRESOLVED_REFERENCE_FIELDS, path)
        reference_id = validate_non_empty_string(record["reference_id"], f"{path}.reference_id")
        if reference_id in reference_ids:
            raise ValidationError("unresolved note reference appears more than once")
        reference_ids.add(reference_id)
        validate_non_empty_string(record["note_system_id"], f"{path}.note_system_id")
        validate_id_list(record["candidate_definition_ids"], f"{path}.candidate_definition_ids")
        validate_id_list(record["evidence_ids"], f"{path}.evidence_ids", required=True)
        validate_reason(record["reason"], f"{path}.reason")
    return reference_ids


def _validate_relation_identity(
    relation: dict[str, Any],
    reference: dict[str, Any],
    definition: dict[str, Any],
) -> None:
    expected = (
        relation["source_text_unit_id"] == reference["text_unit_id"]
        and relation["source_inline_run_index"] == reference["inline_run_index"]
        and relation["marker"] == reference["marker"]
        and relation["target_note_unit_id"] == definition["text_unit_id"]
        and relation["note_system_id"]
        == reference["note_system_id"]
        == definition["note_system_id"]
        and reference["normalized_marker"] == definition["normalized_marker"]
    )
    if not expected:
        raise ValidationError("NoteResolution relation differs from inventory identity")
    if relation["scope"] == "page" and (
        reference["physical_page"] != definition["physical_page"]
    ):
        raise ValidationError("page-scoped note relation crosses physical pages")


def _validate_relation_sections(
    relation: dict[str, Any],
    reference: dict[str, Any],
    definition: dict[str, Any],
    section_by_text_unit: dict[str, str],
    sections_by_id: dict[str, dict[str, Any]],
) -> None:
    source_section = section_by_text_unit.get(reference["text_unit_id"])
    target_section = section_by_text_unit.get(definition["text_unit_id"])
    if (
        relation["source_section_id"] != source_section
        or relation["target_section_id"] != target_section
    ):
        raise ValidationError("NoteResolution section provenance differs from SectionMap")
    scope_section = relation["scope_section_id"]
    if relation["scope"] == "chapter":
        if (
            scope_section is None
            or source_section is None
            or target_section is None
            or sections_by_id[source_section]["chapter_scope_id"] != scope_section
            or sections_by_id[target_section]["chapter_scope_id"] != scope_section
            or sections_by_id[scope_section]["chapter_scope_id"] != scope_section
        ):
            raise ValidationError(
                "chapter-scoped note relation lacks one confirmed scope ancestor"
            )
    elif scope_section is not None:
        raise ValidationError("scope_section_id is only valid for chapter scope")


def _section_by_member(section_map: dict[str, Any], field: str) -> dict[str, str]:
    return {
        member_id: section["section_id"]
        for section in section_map["sections"]
        for member_id in section[field]
    }


def _is_same_or_ancestor(
    candidate: str, section_id: str, sections_by_id: dict[str, dict[str, Any]]
) -> bool:
    current_id: str | None = section_id
    while current_id is not None:
        if current_id == candidate:
            return True
        section = sections_by_id.get(current_id)
        if section is None:
            return False
        current_id = section["parent_section_id"]
    return False
