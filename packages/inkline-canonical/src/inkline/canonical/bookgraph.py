from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from inkline.canonical.schema import ValidationError

BOOKGRAPH_SCHEMA_NAME = "inkline_bookgraph"
BOOKGRAPH_SCHEMA_VERSION = "2.0-shadow"

BOOKGRAPH_NODE_TYPES = {
    "heading",
    "paragraph",
    "display_block",
    "list_item",
    "footnote",
    "note",
}

BOOKGRAPH_EDGE_TYPES = {
    "appears_on_page",
    "references_note",
    "defines_note",
    "continues",
    "contains",
    "caption_of",
    "table_note_of",
}

REQUIRED_TOP_LEVEL_FIELDS = {
    "metadata": dict,
    "nodes": list,
    "edges": list,
    "evidence": list,
    "assets": dict,
    "projections": dict,
}

REQUIRED_METADATA_FIELDS = (
    "schema_name",
    "schema_version",
    "doc_id",
    "title",
    "language",
    "source_file",
    "parser_name",
    "parser_mode",
)

REQUIRED_NODE_FIELDS = {
    "node_id": str,
    "node_type": str,
    "text": str,
    "attrs": dict,
    "evidence_ids": list,
}

REQUIRED_EVIDENCE_FIELDS = {
    "evidence_id": str,
    "parser": str,
    "source_id": str,
    "source_kind": str,
}

REQUIRED_NOTE_ATTR_FIELDS = {
    "marker": str,
    "source_placement": str,
    "scope": str,
    "source_text_unit_ids": list,
}


def make_bookgraph(
    metadata: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    assets: dict[str, Any] | None = None,
    projections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph = {
        "metadata": {**metadata},
        "nodes": deepcopy(nodes),
        "edges": deepcopy(edges),
        "evidence": deepcopy(evidence),
        "assets": deepcopy(assets) if assets is not None else {},
        "projections": deepcopy(projections) if projections is not None else {},
    }
    graph["metadata"].setdefault("schema_name", BOOKGRAPH_SCHEMA_NAME)
    graph["metadata"].setdefault("schema_version", BOOKGRAPH_SCHEMA_VERSION)
    graph["projections"].setdefault("reading_order", [])
    validate_bookgraph(graph)
    return graph


def make_node(
    node_id: str,
    node_type: str,
    text: str = "",
    *,
    level: int | None = None,
    inline_runs: list[dict[str, Any]] | None = None,
    attrs: dict[str, Any] | None = None,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "node_id": node_id,
        "node_type": node_type,
        "text": text,
        "attrs": deepcopy(attrs) if attrs is not None else {},
        "evidence_ids": list(evidence_ids or []),
    }
    if level is not None:
        node["level"] = level
    if inline_runs is not None:
        node["inline_runs"] = deepcopy(inline_runs)
    return node


def make_edge(
    edge_type: str,
    source: str,
    target: str,
    *,
    evidence_ids: list[str] | None = None,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "edge_type": edge_type,
        "source": source,
        "target": target,
        "evidence_ids": list(evidence_ids or []),
        "attrs": deepcopy(attrs) if attrs is not None else {},
    }


def make_evidence(
    evidence_id: str,
    parser: str,
    source_id: str,
    *,
    source_kind: str = "unknown",
    page: int | None = None,
    pages: list[int] | None = None,
    bbox: list[float] | None = None,
    spans: list[dict[str, Any]] | None = None,
    parser_payload: dict[str, Any] | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    resolved_pages = list(pages) if pages is not None else ([page] if page is not None else [])
    resolved_page = page if page is not None else (resolved_pages[0] if resolved_pages else None)
    evidence: dict[str, Any] = {
        "evidence_id": evidence_id,
        "parser": parser,
        "source_id": source_id,
        "source_kind": source_kind,
        "page": resolved_page,
        "pages": resolved_pages,
        "bbox": deepcopy(bbox),
        "spans": deepcopy(spans) if spans is not None else [],
        "parser_payload": deepcopy(parser_payload) if parser_payload is not None else {},
        "confidence": confidence,
    }
    return evidence


def validate_bookgraph(graph: dict[str, Any]) -> None:
    _validate_top_level(graph)
    _validate_metadata(graph["metadata"])
    node_types = _validate_nodes(graph["nodes"])
    node_ids = set(node_types)
    evidence_ids = _validate_evidence(graph["evidence"])
    _validate_edges(graph["edges"], node_types, evidence_ids)
    _validate_projections(graph["projections"], node_ids)


def _validate_top_level(graph: dict[str, Any]) -> None:
    for field, expected_type in REQUIRED_TOP_LEVEL_FIELDS.items():
        value = graph.get(field)
        if not isinstance(value, expected_type):
            raise ValidationError(f"{field} must be {expected_type.__name__}")


def _validate_metadata(metadata: dict[str, Any]) -> None:
    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata:
            raise ValidationError(f"metadata.{field} is required")
    if metadata.get("schema_name") != BOOKGRAPH_SCHEMA_NAME:
        raise ValidationError(f"metadata.schema_name must be {BOOKGRAPH_SCHEMA_NAME}")
    if metadata.get("schema_version") != BOOKGRAPH_SCHEMA_VERSION:
        raise ValidationError(f"metadata.schema_version must be {BOOKGRAPH_SCHEMA_VERSION}")


def _validate_nodes(nodes: list[dict[str, Any]]) -> dict[str, str]:
    node_types: dict[str, str] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValidationError(f"nodes[{index}] must be object")
        for field, expected_type in REQUIRED_NODE_FIELDS.items():
            value = node.get(field)
            if not isinstance(value, expected_type):
                raise ValidationError(f"nodes[{index}].{field} must be {expected_type.__name__}")
        node_id = node["node_id"]
        if node_id in node_types:
            raise ValidationError(f"duplicate node_id: {node_id}")
        if node["node_type"] not in BOOKGRAPH_NODE_TYPES:
            raise ValidationError(f"nodes[{index}].node_type is invalid: {node['node_type']}")
        node_types[node_id] = node["node_type"]
    for index, node in enumerate(nodes):
        if node["node_type"] == "note":
            _validate_note_attrs(node["attrs"], f"nodes[{index}].attrs")
        if "inline_runs" in node and not isinstance(node["inline_runs"], list):
            raise ValidationError(f"nodes[{index}].inline_runs must be list")
        if "inline_runs" in node:
            _validate_inline_runs(node["inline_runs"], node_types, f"nodes[{index}].inline_runs")
    return node_types


def _validate_note_attrs(attrs: dict[str, Any], path: str) -> None:
    for field, expected_type in REQUIRED_NOTE_ATTR_FIELDS.items():
        value = attrs.get(field)
        if not isinstance(value, expected_type):
            raise ValidationError(f"{path}.{field} must be {expected_type.__name__}")


def _validate_inline_runs(
    inline_runs: list[Any], node_types: dict[str, str], path: str
) -> None:
    for index, run in enumerate(inline_runs):
        if not isinstance(run, dict):
            raise ValidationError(f"{path}[{index}] must be object")
        if run.get("type") != "note_ref":
            continue
        attrs = run.get("attrs") if isinstance(run.get("attrs"), dict) else {}
        target_note_id = attrs.get("target_note_id") or run.get("target_note_id")
        if target_note_id is None:
            continue
        if not isinstance(target_note_id, str):
            raise ValidationError(f"{path}[{index}].target_note_id must be str")
        if not _is_bookgraph_node_ref(target_note_id):
            continue
        if target_note_id not in node_types:
            raise ValidationError(f"{path}[{index}].attrs.target_note_id missing node")
        if not _is_note_node_type(node_types[target_note_id]):
            raise ValidationError(f"{path}[{index}].attrs.target_note_id note_ref target must be note")


def _validate_evidence(evidence: list[dict[str, Any]]) -> set[str]:
    evidence_ids: set[str] = set()
    for index, record in enumerate(evidence):
        if not isinstance(record, dict):
            raise ValidationError(f"evidence[{index}] must be object")
        for field, expected_type in REQUIRED_EVIDENCE_FIELDS.items():
            value = record.get(field)
            if not isinstance(value, expected_type):
                raise ValidationError(f"evidence[{index}].{field} must be {expected_type.__name__}")
        evidence_id = record["evidence_id"]
        if evidence_id in evidence_ids:
            raise ValidationError(f"duplicate evidence_id: {evidence_id}")
        evidence_ids.add(evidence_id)
    return evidence_ids


def _validate_edges(
    edges: list[dict[str, Any]], node_types: dict[str, str], evidence_ids: set[str]
) -> None:
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise ValidationError(f"edges[{index}] must be object")
        if edge.get("edge_type") not in BOOKGRAPH_EDGE_TYPES:
            raise ValidationError(f"edges[{index}].edge_type is invalid: {edge.get('edge_type')}")
        for endpoint in ("source", "target"):
            value = edge.get(endpoint)
            if not isinstance(value, str):
                raise ValidationError(f"edges[{index}].{endpoint} must be str")
            if _is_bookgraph_node_ref(value) and value not in node_types:
                raise ValidationError(f"edges[{index}].{endpoint} missing node: {value}")
        if edge.get("edge_type") == "references_note":
            target = edge.get("target")
            if isinstance(target, str) and not _is_note_node_type(node_types.get(target)):
                raise ValidationError(f"edges[{index}].references_note target must be note")
        _validate_evidence_ids(edge.get("evidence_ids", []), evidence_ids, f"edges[{index}]")


def _is_note_node_type(node_type: str | None) -> bool:
    return node_type in {"note", "footnote"}


def _is_bookgraph_node_ref(value: str) -> bool:
    return bool(re.fullmatch(r"n\d+", value))


def _validate_projections(projections: dict[str, Any], node_ids: set[str]) -> None:
    reading_order = projections.get("reading_order")
    if not isinstance(reading_order, list):
        raise ValidationError("projections.reading_order must be list")
    for node_id in reading_order:
        if node_id not in node_ids:
            raise ValidationError(f"projections.reading_order missing node: {node_id}")
    for field in ("epub_flow", "rag_units"):
        if field in projections and not isinstance(projections[field], list):
            raise ValidationError(f"projections.{field} must be list")


def _validate_evidence_ids(values: list[Any], evidence_ids: set[str], path: str) -> None:
    if not isinstance(values, list):
        raise ValidationError(f"{path}.evidence_ids must be list")
    for evidence_id in values:
        if evidence_id not in evidence_ids:
            raise ValidationError(f"{path}.evidence_ids missing evidence: {evidence_id}")
