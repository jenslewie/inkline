from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from inkline.canonical.bookgraph import (
    BOOKGRAPH_SCHEMA_NAME,
    BOOKGRAPH_SCHEMA_VERSION,
    make_bookgraph,
    make_edge,
    make_evidence,
    make_node,
)
from inkline.canonical.observed import validate_observed_document


def build_bookgraph_from_observed(document: dict[str, Any]) -> dict[str, Any]:
    validate_observed_document(document)
    metadata = _bookgraph_metadata(document)
    nodes: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    reading_order: list[str] = []
    ignored_counts: Counter[str] = Counter()
    parser = str(metadata.get("parser_name") or "")

    for observation in document["observations"]:
        node_type = _node_type(observation)
        if node_type is None:
            ignored_counts[str(observation["kind"])] += 1
            continue
        node_id = f"n{len(nodes) + 1:06d}"
        evidence_id = f"ev{len(evidence_records) + 1:06d}"
        node = _node_from_observation(observation, node_id, evidence_id, node_type)
        evidence = _evidence_from_observation(observation, evidence_id, parser)
        nodes.append(node)
        evidence_records.append(evidence)
        reading_order.append(node_id)
        edges.append(
            make_edge(
                "appears_on_page",
                node_id,
                f"page:{observation['page']}",
                evidence_ids=[evidence_id],
            )
        )

    metadata["shadow_ignored_observation_counts"] = dict(sorted(ignored_counts.items()))
    projections = {
        "reading_order": reading_order,
        "epub_flow": list(reading_order),
        "rag_units": _rag_units(nodes, evidence_records),
    }
    return make_bookgraph(
        metadata,
        nodes,
        edges,
        evidence_records,
        assets=deepcopy(document.get("assets") or {}),
        projections=projections,
    )


def _bookgraph_metadata(document: dict[str, Any]) -> dict[str, Any]:
    source = document["metadata"]
    return {
        "schema_name": BOOKGRAPH_SCHEMA_NAME,
        "schema_version": BOOKGRAPH_SCHEMA_VERSION,
        "doc_id": source.get("doc_id") or "",
        "title": source.get("title") or "",
        "language": source.get("language") or "",
        "source_file": source.get("source_file") or "",
        "parser_name": source.get("parser_name") or "",
        "parser_mode": source.get("parser_mode") or "",
        "shadow_source_schema_version": source.get("schema_version"),
    }


def _node_type(observation: dict[str, Any]) -> str | None:
    role_hint = observation["role_hint"]
    if role_hint == "title_text":
        return "heading"
    if role_hint == "body_text":
        return "paragraph"
    if role_hint == "list_text":
        return "list_item"
    if observation["kind"] == "footnote_region" or role_hint == "footnote_text":
        return "footnote"
    return None


def _node_from_observation(
    observation: dict[str, Any], node_id: str, evidence_id: str, node_type: str
) -> dict[str, Any]:
    attrs = {
        "source_observation_id": observation["observation_id"],
        "role_hint": observation["role_hint"],
    }
    observation_attrs = observation.get("attrs") or {}
    inline_runs = observation_attrs.get("inline_runs")
    return make_node(
        node_id,
        node_type,
        str(observation.get("text") or ""),
        level=1 if node_type == "heading" else None,
        inline_runs=deepcopy(inline_runs) if isinstance(inline_runs, list) else None,
        attrs=attrs,
        evidence_ids=[evidence_id],
    )


def _evidence_from_observation(
    observation: dict[str, Any], evidence_id: str, parser: str
) -> dict[str, Any]:
    return make_evidence(
        evidence_id,
        parser,
        observation["observation_id"],
        source_kind="observation",
        page=observation["page"],
        bbox=deepcopy(observation.get("bbox")),
        spans=deepcopy(observation.get("spans") or []),
        parser_payload=deepcopy(observation.get("parser_payload") or {}),
    )


def _rag_units(
    nodes: list[dict[str, Any]], evidence_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    evidence_by_id = {record["evidence_id"]: record for record in evidence_records}
    heading_path: list[str] = []
    current_heading_node_id: str | None = None
    units: list[dict[str, Any]] = []
    for node in nodes:
        if node["node_type"] == "heading":
            heading_path = [node["text"]] if node["text"] else []
            current_heading_node_id = node["node_id"]
            continue
        units.append(
            {
                "unit_id": f"ru{len(units) + 1:06d}",
                "node_id": node["node_id"],
                "text": node["text"],
                "heading_path": list(heading_path),
                "parent_node_ids": [current_heading_node_id] if current_heading_node_id else [],
                "source_pages": _source_pages(node, evidence_by_id),
                "evidence_ids": list(node["evidence_ids"]),
            }
        )
    return units


def _source_pages(
    node: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> list[int]:
    pages: list[int] = []
    for evidence_id in node.get("evidence_ids", []):
        evidence = evidence_by_id.get(evidence_id)
        if not evidence:
            continue
        for page in evidence.get("pages") or []:
            if isinstance(page, int) and page not in pages:
                pages.append(page)
    return pages
