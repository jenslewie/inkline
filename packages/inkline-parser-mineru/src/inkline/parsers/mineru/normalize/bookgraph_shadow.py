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

SUPPORTED_SHADOW_BLOCK_TYPES = {
    "heading",
    "paragraph",
    "display_block",
    "list_item",
    "footnote",
}


def build_bookgraph_shadow(canonical: dict[str, Any]) -> dict[str, Any]:
    metadata = _bookgraph_metadata(canonical)
    nodes: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    reading_order: list[str] = []
    block_to_node: dict[str, str] = {}
    ignored_counts: Counter[str] = Counter()
    parser = str(metadata.get("parser_name") or "mineru")

    for block in canonical.get("blocks", []):
        block_type = block.get("type")
        if block_type not in SUPPORTED_SHADOW_BLOCK_TYPES:
            ignored_counts[str(block_type or "unknown")] += 1
            continue
        node_id = f"n{len(nodes) + 1:06d}"
        evidence_id = f"ev{len(evidence_records) + 1:06d}"
        node = _node_from_block(block, node_id, evidence_id)
        evidence = _evidence_from_block(block, evidence_id, parser)
        nodes.append(node)
        evidence_records.append(evidence)
        reading_order.append(node_id)
        block_id = str(block.get("block_id") or node_id)
        block_to_node[block_id] = node_id
        if evidence.get("page") is not None:
            edges.append(
                make_edge(
                    "appears_on_page",
                    node_id,
                    f"page:{evidence['page']}",
                    evidence_ids=[evidence_id],
                )
            )

    edges.extend(_note_reference_edges(nodes, block_to_node))
    metadata["shadow_ignored_block_counts"] = dict(sorted(ignored_counts.items()))
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
        assets=deepcopy(canonical.get("assets") or {}),
        projections=projections,
    )


def _bookgraph_metadata(canonical: dict[str, Any]) -> dict[str, Any]:
    source = canonical.get("metadata") or {}
    return {
        "schema_name": BOOKGRAPH_SCHEMA_NAME,
        "schema_version": BOOKGRAPH_SCHEMA_VERSION,
        "doc_id": source.get("doc_id") or "",
        "title": source.get("title") or "",
        "language": source.get("language") or "",
        "source_file": source.get("source_file") or "",
        "parser_name": source.get("parser_name") or "mineru",
        "parser_mode": source.get("parser_mode") or "",
        "shadow_source_schema_version": source.get("schema_version"),
    }


def _node_from_block(block: dict[str, Any], node_id: str, evidence_id: str) -> dict[str, Any]:
    block_type = str(block.get("type"))
    block_attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
    attrs = {
        "legacy_block_id": str(block.get("block_id") or node_id),
        "logical_role": _logical_role(block_type),
        "layout_context": _layout_context(block_type, block_attrs),
    }
    if block_type == "footnote" and block_attrs.get("note_id"):
        attrs["note_id"] = str(block_attrs["note_id"])
    inline_runs = block_attrs.get("inline_runs")
    return make_node(
        node_id,
        block_type,
        str(block.get("text") or ""),
        level=block.get("level") if block_type == "heading" else None,
        inline_runs=deepcopy(inline_runs) if isinstance(inline_runs, list) else None,
        attrs=attrs,
        evidence_ids=[evidence_id],
    )


def _evidence_from_block(block: dict[str, Any], evidence_id: str, parser: str) -> dict[str, Any]:
    source = block.get("source") if isinstance(block.get("source"), dict) else {}
    page = source.get("page")
    pages = source.get("pages")
    return make_evidence(
        evidence_id,
        parser,
        str(block.get("block_id") or evidence_id),
        source_kind="legacy_block",
        page=page if isinstance(page, int) else None,
        pages=list(pages) if isinstance(pages, list) else None,
        bbox=deepcopy(source.get("bbox")),
        spans=deepcopy(source.get("spans")) if isinstance(source.get("spans"), list) else None,
        parser_payload={"legacy_type": block.get("type")},
    )


def _logical_role(block_type: str) -> str:
    return {
        "heading": "heading",
        "paragraph": "body",
        "list_item": "body",
        "display_block": "display",
        "footnote": "footnote",
    }[block_type]


def _layout_context(block_type: str, block_attrs: dict[str, Any]) -> str:
    explicit = block_attrs.get("layout_context")
    if explicit:
        return str(explicit)
    legacy_role = str(block_attrs.get("layout_role") or "")
    if legacy_role in {"inline_display_block", "same_page_display_block_continuation"}:
        return "inline_flow"
    if legacy_role in {"standalone_display_page", "standalone_display_group"}:
        return "standalone"
    if legacy_role:
        return "set_off" if block_type == "display_block" else legacy_role
    return {
        "heading": "heading",
        "paragraph": "normal_flow",
        "list_item": "normal_flow",
        "display_block": "set_off",
        "footnote": "footnote",
    }[block_type]


def _note_reference_edges(
    nodes: list[dict[str, Any]], block_to_node: dict[str, str]
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    footnote_nodes = _footnote_node_aliases(nodes)
    for node in nodes:
        if node["node_type"] == "footnote":
            continue
        for run in node.get("inline_runs", []):
            target_note_id = run.get("target_note_id") if isinstance(run, dict) else None
            if not target_note_id:
                continue
            target = footnote_nodes.get(str(target_note_id)) or block_to_node.get(str(target_note_id))
            if target is None:
                continue
            edges.append(
                make_edge(
                    "references_note",
                    node["node_id"],
                    target,
                    evidence_ids=list(node["evidence_ids"]),
                    attrs={"target_note_id": str(target_note_id)},
                )
            )
    return edges


def _footnote_node_aliases(nodes: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in nodes:
        if node["node_type"] != "footnote":
            continue
        attrs = node.get("attrs") or {}
        legacy_block_id = attrs.get("legacy_block_id") or attrs.get("source_block_id")
        for alias in (legacy_block_id, attrs.get("note_id")):
            if alias:
                aliases[str(alias)] = node["node_id"]
        if legacy_block_id:
            aliases[f"note_{legacy_block_id}"] = node["node_id"]
    return aliases


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
        source_pages = _source_pages(node, evidence_by_id)
        units.append(
            {
                "unit_id": f"ru{len(units) + 1:06d}",
                "node_id": node["node_id"],
                "text": node["text"],
                "heading_path": list(heading_path),
                "parent_node_ids": [current_heading_node_id] if current_heading_node_id else [],
                "source_pages": source_pages,
                "evidence_ids": list(node["evidence_ids"]),
            }
        )
    return units


def _source_pages(node: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> list[int]:
    pages: list[int] = []
    for evidence_id in node.get("evidence_ids", []):
        evidence = evidence_by_id.get(evidence_id)
        if not evidence:
            continue
        evidence_pages = evidence.get("pages") or []
        for page in evidence_pages:
            if isinstance(page, int) and page not in pages:
                pages.append(page)
    return pages
