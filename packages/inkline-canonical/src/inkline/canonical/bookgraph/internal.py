from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.bookgraph.schema import validate_bookgraph
from inkline.canonical.schema import ValidationError

INTERNAL_CANONICAL_SCHEMA_NAME = "inkline_internal_canonical"
INTERNAL_CANONICAL_SCHEMA_VERSION = "0.1-dev"

REQUIRED_INTERNAL_TOP_LEVEL_FIELDS = {
    "schema_name": str,
    "schema_version": str,
    "public_projection": dict,
    "pages": list,
    "nodes": list,
    "edges": list,
    "evidence": list,
    "pipeline": dict,
}


def make_internal_canonical(
    public_projection: dict[str, Any],
    *,
    pages: list[dict[str, Any]] | None = None,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    pipeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    internal = {
        "schema_name": INTERNAL_CANONICAL_SCHEMA_NAME,
        "schema_version": INTERNAL_CANONICAL_SCHEMA_VERSION,
        "public_projection": deepcopy(public_projection),
        "pages": deepcopy(pages) if pages is not None else [],
        "nodes": deepcopy(nodes) if nodes is not None else [],
        "edges": deepcopy(edges) if edges is not None else [],
        "evidence": deepcopy(evidence) if evidence is not None else [],
        "pipeline": deepcopy(pipeline) if pipeline is not None else {},
    }
    validate_internal_canonical(internal)
    return internal


def validate_internal_canonical(internal: dict[str, Any]) -> None:
    for field, expected_type in REQUIRED_INTERNAL_TOP_LEVEL_FIELDS.items():
        value = internal.get(field)
        if not isinstance(value, expected_type):
            raise ValidationError(f"{field} must be {expected_type.__name__}")
    if internal["schema_name"] != INTERNAL_CANONICAL_SCHEMA_NAME:
        raise ValidationError(
            f"schema_name must be {INTERNAL_CANONICAL_SCHEMA_NAME}"
        )
    if internal["schema_version"] != INTERNAL_CANONICAL_SCHEMA_VERSION:
        raise ValidationError(
            f"schema_version must be {INTERNAL_CANONICAL_SCHEMA_VERSION}"
        )
    validate_bookgraph(internal["public_projection"])
    _validate_public_debug_pairs(internal["pages"], "pages")
    _validate_public_debug_pairs(internal["nodes"], "nodes")
    _validate_public_debug_pairs(internal["edges"], "edges")
    _validate_public_debug_pairs(internal["evidence"], "evidence")


def _validate_public_debug_pairs(records: list[Any], path: str) -> None:
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValidationError(f"{path}[{index}] must be object")
        public = record.get("public")
        debug = record.get("debug")
        if not isinstance(public, dict):
            raise ValidationError(f"{path}[{index}].public must be object")
        if not isinstance(debug, dict):
            raise ValidationError(f"{path}[{index}].debug must be object")
