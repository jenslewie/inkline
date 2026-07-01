from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from inkline.canonical.bookgraph import BOOKGRAPH_NODE_TYPES, validate_bookgraph
from inkline.canonical.bookgraph_projection import bookgraph_to_blocks


def audit_bookgraph(
    graph: dict[str, Any], *, legacy_canonical: dict[str, Any] | None = None
) -> dict[str, Any]:
    validate_bookgraph(graph)
    audit = {
        "metadata": _metadata_summary(graph),
        "node_counts": _counts(node["node_type"] for node in graph["nodes"]),
        "edge_counts": _counts(edge["edge_type"] for edge in graph["edges"]),
        "evidence": _evidence_summary(graph["evidence"]),
        "projections": _projection_summary(graph["projections"]),
        "ignored_block_counts": deepcopy(
            graph.get("metadata", {}).get("shadow_ignored_block_counts", {})
        ),
        "footnotes": _footnote_summary(graph),
        "display_blocks": _display_block_summary(graph),
    }
    if legacy_canonical is not None:
        audit["projection_diff"] = _projection_diff(graph, legacy_canonical)
    return audit


def _metadata_summary(graph: dict[str, Any]) -> dict[str, Any]:
    metadata = graph["metadata"]
    return {
        "schema_name": metadata.get("schema_name"),
        "schema_version": metadata.get("schema_version"),
        "doc_id": metadata.get("doc_id"),
        "title": metadata.get("title"),
        "parser_name": metadata.get("parser_name"),
        "parser_mode": metadata.get("parser_mode"),
        "shadow_source_schema_version": metadata.get("shadow_source_schema_version"),
    }


def _counts(values: Any) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _evidence_summary(evidence: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "count": len(evidence),
        "with_page": sum(1 for record in evidence if record.get("page") is not None),
        "with_bbox": sum(1 for record in evidence if record.get("bbox") is not None),
        "with_spans": sum(1 for record in evidence if record.get("spans")),
    }


def _projection_summary(projections: dict[str, Any]) -> dict[str, int]:
    return {
        "reading_order_count": len(projections.get("reading_order") or []),
        "epub_flow_count": len(projections.get("epub_flow") or []),
        "rag_unit_count": len(projections.get("rag_units") or []),
    }


def _footnote_summary(graph: dict[str, Any]) -> dict[str, Any]:
    note_ref_runs = _note_ref_runs(graph["nodes"])
    reference_edges = [
        edge for edge in graph["edges"] if edge.get("edge_type") == "references_note"
    ]
    edge_targets = {edge.get("target") for edge in reference_edges}
    footnote_node_ids = {
        node["node_id"] for node in graph["nodes"] if node["node_type"] == "footnote"
    }
    return {
        "footnote_nodes": len(footnote_node_ids),
        "note_ref_runs": note_ref_runs,
        "references_note_edges": len(reference_edges),
        "references_to_footnote_nodes": sum(1 for target in edge_targets if target in footnote_node_ids),
        "resolved_note_ref_ratio": _ratio(len(reference_edges), note_ref_runs),
    }


def _note_ref_runs(nodes: list[dict[str, Any]]) -> int:
    count = 0
    for node in nodes:
        if node["node_type"] == "footnote":
            continue
        for run in node.get("inline_runs", []):
            if isinstance(run, dict) and run.get("target_note_id"):
                count += 1
    return count


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _display_block_summary(graph: dict[str, Any]) -> dict[str, Any]:
    evidence_by_id = {record["evidence_id"]: record for record in graph["evidence"]}
    pages: Counter[str] = Counter()
    layout_roles: Counter[str] = Counter()
    source_block_ids: list[str] = []
    for node in graph["nodes"]:
        if node["node_type"] != "display_block":
            continue
        source_block_id = node.get("attrs", {}).get("source_block_id")
        if source_block_id:
            source_block_ids.append(str(source_block_id))
        layout_role = node.get("attrs", {}).get("layout_role")
        if layout_role:
            layout_roles[str(layout_role)] += 1
        for evidence_id in node.get("evidence_ids", []):
            page = evidence_by_id.get(evidence_id, {}).get("page")
            if page is not None:
                pages[str(page)] += 1
    return {
        "count": sum(1 for node in graph["nodes"] if node["node_type"] == "display_block"),
        "pages": dict(sorted(pages.items(), key=lambda item: int(item[0]))),
        "layout_roles": dict(sorted(layout_roles.items())),
        "source_block_ids": source_block_ids,
    }


def _projection_diff(graph: dict[str, Any], legacy_canonical: dict[str, Any]) -> dict[str, Any]:
    projected = bookgraph_to_blocks(graph)
    legacy_supported = [
        block
        for block in legacy_canonical.get("blocks", [])
        if block.get("type") in BOOKGRAPH_NODE_TYPES
    ]
    projected_by_id = {block["block_id"]: block for block in projected}
    legacy_by_id = {block["block_id"]: block for block in legacy_supported}
    missing = sorted(block_id for block_id in legacy_by_id if block_id not in projected_by_id)
    extra = sorted(block_id for block_id in projected_by_id if block_id not in legacy_by_id)
    changed = _changed_blocks(projected_by_id, legacy_by_id)
    legacy_order = [block["block_id"] for block in legacy_supported]
    projected_order = [block["block_id"] for block in projected]
    return {
        "legacy_supported_block_count": len(legacy_supported),
        "projected_block_count": len(projected),
        "reading_order_matches_legacy_supported": projected_order == legacy_order,
        "missing_block_ids": missing,
        "extra_block_ids": extra,
        "changed_blocks": changed,
        "exact_supported_fields_match": not missing and not extra and not changed,
    }


def _changed_blocks(
    projected_by_id: dict[str, dict[str, Any]], legacy_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    for block_id in sorted(projected_by_id.keys() & legacy_by_id.keys()):
        fields = _changed_fields(projected_by_id[block_id], legacy_by_id[block_id])
        if fields:
            changed.append({"block_id": block_id, "changed_fields": fields})
    return changed


def _changed_fields(projected: dict[str, Any], legacy: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for field in ("type", "text", "level"):
        if projected.get(field) != legacy.get(field):
            fields.append(field)
    if _inline_runs(projected) != _inline_runs(legacy):
        fields.append("inline_runs")
    if _source_for_compare(projected) != _source_for_compare(legacy):
        fields.append("source")
    return fields


def _inline_runs(block: dict[str, Any]) -> list[dict[str, Any]]:
    attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
    runs = attrs.get("inline_runs")
    return runs if isinstance(runs, list) else []


def _source_for_compare(block: dict[str, Any]) -> dict[str, Any]:
    source = block.get("source") if isinstance(block.get("source"), dict) else {}
    comparable = {
        key: deepcopy(source[key])
        for key in ("page", "bbox", "pages", "spans")
        if key in source and source[key] not in (None, [])
    }
    if "page" in comparable and "pages" not in comparable:
        comparable["pages"] = [comparable["page"]]
    return comparable
