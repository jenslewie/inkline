from __future__ import annotations

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
from inkline.canonical.bookgraph_notes import resolve_page_footnote_refs
from inkline.canonical.observed import validate_observed_document
from inkline.canonical.page_roles import classify_observed_page_roles, page_roles_by_page
from inkline.canonical.text_unit_layout import (
    audit_text_unit_layout,
    classify_text_units_by_layout,
)
from inkline.canonical.text_units import build_text_units


def build_bookgraph_from_observed(document: dict[str, Any]) -> dict[str, Any]:
    validate_observed_document(document)
    metadata = _bookgraph_metadata(document)
    nodes: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    reading_order: list[str] = []
    parser = str(metadata.get("parser_name") or "")
    text_units, ignored_counts = build_text_units(document)
    layout_audit = audit_text_unit_layout(text_units, document["pages"], document["observations"])
    page_role_records = classify_observed_page_roles(document, layout_audit=layout_audit)
    roles_by_page = page_roles_by_page(page_role_records)
    text_units = classify_text_units_by_layout(text_units, document["pages"])

    for unit in text_units:
        node_id = f"n{len(nodes) + 1:06d}"
        evidence_id = f"ev{len(evidence_records) + 1:06d}"
        nodes.append(_node_from_unit(unit, node_id, evidence_id, roles_by_page))
        evidence_records.append(_evidence_from_unit(unit, evidence_id, parser))
        reading_order.append(node_id)
        edges.append(
            make_edge(
                "appears_on_page",
                node_id,
                f"page:{unit['page']}",
                evidence_ids=[evidence_id],
            )
        )

    metadata["shadow_ignored_observation_counts"] = ignored_counts
    metadata["shadow_text_unit_layout_audit_summary"] = layout_audit["summary"]
    metadata["shadow_text_unit_layout_page_coverage"] = layout_audit["page_coverage"]
    metadata["shadow_text_unit_layout_profile_quality"] = layout_audit["profile_quality"]
    metadata["shadow_page_roles"] = _canonical_page_role_records(page_role_records)
    projections = {"reading_order": reading_order}
    graph = make_bookgraph(
        metadata,
        nodes,
        edges,
        evidence_records,
        assets=deepcopy(document.get("assets") or {}),
        projections=projections,
    )
    return resolve_page_footnote_refs(graph)


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


def _node_from_unit(
    unit: dict[str, Any],
    node_id: str,
    evidence_id: str,
    roles_by_page: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    node_type = unit["unit_type"]
    attrs = {
        "source_text_unit_id": unit["unit_id"],
        "source_observation_ids": list(unit["observation_ids"]),
        "role_hints": list(unit["role_hints"]),
    }
    unit_attrs = unit.get("attrs") or {}
    for key in ("layout_role", "layout_classification", "merge_reasons"):
        if key in unit_attrs:
            attrs[key] = deepcopy(unit_attrs[key])
    page_role = roles_by_page.get(int(unit["page"]))
    if page_role:
        attrs["page_role"] = page_role["page_role"]
        attrs["page_role_signals"] = list(page_role["signals"])
    inline_runs = unit_attrs.get("inline_runs")
    return make_node(
        node_id,
        node_type,
        str(unit.get("text") or ""),
        level=1 if node_type == "heading" else None,
        inline_runs=deepcopy(inline_runs) if isinstance(inline_runs, list) else None,
        attrs=attrs,
        evidence_ids=[evidence_id],
    )


def _evidence_from_unit(unit: dict[str, Any], evidence_id: str, parser: str) -> dict[str, Any]:
    return make_evidence(
        evidence_id,
        parser,
        unit["unit_id"],
        source_kind="text_unit",
        page=unit["page"],
        pages=deepcopy(unit.get("pages") or []),
        bbox=deepcopy(unit.get("bbox")),
        spans=deepcopy(unit.get("spans") or []),
        parser_payload={
            "observation_ids": list(unit["observation_ids"]),
            "parser_payloads": deepcopy(unit.get("parser_payloads") or []),
        },
    )


def _canonical_page_role_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "page": int(record["page"]),
            "page_role": str(record["page_role"]),
            "signals": list(record.get("signals") or []),
        }
        for record in records
    ]
