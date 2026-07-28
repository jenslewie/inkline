from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.artifact_dag import CanonicalArtifactBundle
from inkline.canonical.bookgraph.internal import make_internal_canonical
from inkline.canonical.bookgraph.notes import resolve_bookgraph_note_refs
from inkline.canonical.bookgraph.schema import (
    BOOKGRAPH_SCHEMA_NAME,
    BOOKGRAPH_SCHEMA_VERSION,
    make_bookgraph,
    make_edge,
    make_evidence,
    make_node,
)
from inkline.canonical.observed.page_roles import classify_observed_page_roles, page_roles_by_page
from inkline.canonical.observed.schema import validate_observed_document
from inkline.canonical.observed.text_unit_layout import (
    audit_text_unit_layout,
    classify_text_units_by_layout,
)
from inkline.canonical.observed.text_units import build_text_units
from inkline.canonical.page_review import validate_resolved_page_review
from inkline.canonical.text_flow.builder import finalize_text_units
from inkline.canonical.text_flow.validation import validate_text_flow_against_sources

INTERNAL_METADATA_PREFIXES = ("shadow_",)
INTERNAL_NODE_ATTRS = {
    "source_text_unit_id",
    "source_logical_unit_id",
    "source_observation_ids",
    "role_hints",
    "layout_classification",
    "merge_reasons",
    "page_role",
    "page_role_signals",
    "source_text_unit_ids",
    "logical_split_reason",
}
INTERNAL_EVIDENCE_FIELDS = {"parser_payload"}


def build_bookgraph_from_observed(
    document: dict[str, Any], *, page_review: dict[str, Any] | None = None
) -> dict[str, Any]:
    return build_observed_bookgraph_artifacts(document, page_review=page_review)["public_graph"]


def build_internal_canonical_from_observed(
    document: dict[str, Any], *, page_review: dict[str, Any] | None = None
) -> dict[str, Any]:
    artifacts = build_observed_bookgraph_artifacts(document, page_review=page_review)
    return make_internal_canonical(
        artifacts["public_graph"],
        pages=_internal_pages(
            artifacts["public_graph"], artifacts["page_role_records"], artifacts["page_review"]
        ),
        nodes=_internal_nodes(artifacts["public_graph"], artifacts["debug_graph"]),
        edges=_internal_edges(artifacts["public_graph"], artifacts["debug_graph"]),
        evidence=_internal_evidence(artifacts["public_graph"], artifacts["debug_graph"]),
        pipeline={
            "observed_document": deepcopy(document),
            "text_units": deepcopy(artifacts["text_units"]),
            "logical_units": deepcopy(artifacts["logical_units"]),
            "layout_audit": deepcopy(artifacts["layout_audit"]),
            "page_roles": deepcopy(artifacts["page_role_records"]),
            "page_review": deepcopy(artifacts["page_review"]),
            "ignored_observation_counts": deepcopy(artifacts["ignored_counts"]),
            "bookgraph_debug_metadata": deepcopy(artifacts["debug_graph"]["metadata"]),
        },
    )


def build_bookgraph_from_artifacts(bundle: CanonicalArtifactBundle) -> dict[str, Any]:
    """Assemble a public BookGraph without reconstructing upstream artifacts."""

    return _bookgraph_artifacts_from_bundle(bundle)["public_graph"]


def build_internal_canonical_from_artifacts(
    bundle: CanonicalArtifactBundle, public_graph: dict[str, Any]
) -> dict[str, Any]:
    """Assemble internal provenance from the same TextFlow used by the public graph."""

    artifacts = _bookgraph_artifacts_from_bundle(bundle)
    return make_internal_canonical(
        public_graph,
        pages=_internal_pages(public_graph, artifacts["page_role_records"], bundle.page_review),
        nodes=_internal_nodes(public_graph, artifacts["debug_graph"]),
        edges=_internal_edges(public_graph, artifacts["debug_graph"]),
        evidence=_internal_evidence(public_graph, artifacts["debug_graph"]),
        pipeline={
            "observed_document": deepcopy(bundle.observed),
            "text_flow": deepcopy(bundle.text_flow),
            "layout_audit": deepcopy(artifacts["layout_audit"]),
            "page_roles": deepcopy(artifacts["page_role_records"]),
            "page_review": deepcopy(bundle.page_review),
            "ignored_observation_counts": deepcopy(
                bundle.text_flow["ignored_observation_counts"] if bundle.text_flow else {}
            ),
            "bookgraph_debug_metadata": deepcopy(artifacts["debug_graph"]["metadata"]),
        },
    )


def _bookgraph_artifacts_from_bundle(
    bundle: CanonicalArtifactBundle,
) -> dict[str, Any]:
    text_flow = bundle.text_flow
    if text_flow is None:
        raise ValueError("cannot assemble BookGraph while PageReview remains unresolved")
    validate_text_flow_against_sources(
        text_flow,
        bundle.observed,
        bundle.skeleton,
        bundle.page_review,
        bundle.page_layout,
        observed_index=bundle.observed_index,
    )
    units = text_flow["text_units"]
    page_role_records = bundle.page_review["pages"]
    layout_audit = audit_text_unit_layout(
        units,
        bundle.observed["pages"],
        bundle.observed["observations"],
        page_layout=bundle.page_layout,
    )
    roles_by_page = page_roles_by_page(page_role_records)
    parser = str(bundle.observed["metadata"].get("parser_name") or "")
    nodes, evidence, edges, reading_order = _graph_records_for_units(units, parser, roles_by_page)
    metadata = _bookgraph_metadata(bundle.observed)
    metadata["shadow_ignored_observation_counts"] = text_flow["ignored_observation_counts"]
    metadata["shadow_text_unit_layout_audit_summary"] = layout_audit["summary"]
    metadata["shadow_text_unit_layout_page_coverage"] = layout_audit["page_coverage"]
    metadata["shadow_text_unit_layout_profile_quality"] = layout_audit["profile_quality"]
    metadata["shadow_page_roles"] = _canonical_page_role_records(page_role_records)
    metadata["shadow_page_sizes"] = _canonical_page_sizes(bundle.observed["pages"])
    debug_graph = resolve_bookgraph_note_refs(
        make_bookgraph(
            metadata,
            nodes,
            edges,
            evidence,
            assets=deepcopy(bundle.page_assets or {}),
            projections={"reading_order": reading_order},
        )
    )
    return {
        "public_graph": _public_bookgraph(debug_graph),
        "debug_graph": debug_graph,
        "layout_audit": layout_audit,
        "page_role_records": page_role_records,
    }


def build_observed_bookgraph_artifacts(
    document: dict[str, Any], *, page_review: dict[str, Any] | None = None
) -> dict[str, Any]:
    validate_observed_document(document)
    pipeline = _observed_pipeline(document)
    parser = str(pipeline["metadata"].get("parser_name") or "")
    roles_by_page = page_roles_by_page(pipeline["page_role_records"])
    resolved_page_review = _resolved_page_review(page_review)
    logical_units = _filter_logical_units_by_page_review(
        pipeline["logical_units"], resolved_page_review
    )
    nodes, evidence_records, edges, reading_order = _graph_records_for_units(
        logical_units,
        parser,
        roles_by_page,
    )

    metadata = pipeline["metadata"]
    metadata["shadow_ignored_observation_counts"] = pipeline["ignored_counts"]
    metadata["shadow_text_unit_layout_audit_summary"] = pipeline["layout_audit"]["summary"]
    metadata["shadow_text_unit_layout_page_coverage"] = pipeline["layout_audit"]["page_coverage"]
    metadata["shadow_text_unit_layout_profile_quality"] = pipeline["layout_audit"][
        "profile_quality"
    ]
    metadata["shadow_page_roles"] = _canonical_page_role_records(pipeline["page_role_records"])
    metadata["shadow_page_sizes"] = _canonical_page_sizes(document["pages"])
    debug_graph = make_bookgraph(
        metadata,
        nodes,
        edges,
        evidence_records,
        assets=deepcopy(document.get("assets") or {}),
        projections={"reading_order": reading_order},
    )
    resolved_debug_graph = resolve_bookgraph_note_refs(debug_graph)
    public_graph = _public_bookgraph(resolved_debug_graph)
    return {
        "public_graph": public_graph,
        "debug_graph": resolved_debug_graph,
        "text_units": pipeline["text_units"],
        "logical_units": pipeline["logical_units"],
        "page_review": resolved_page_review,
        "layout_audit": pipeline["layout_audit"],
        "page_role_records": pipeline["page_role_records"],
        "ignored_counts": pipeline["ignored_counts"],
    }


def _graph_records_for_units(
    logical_units: list[dict[str, Any]],
    parser: str,
    roles_by_page: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    nodes: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    reading_order: list[str] = []
    for unit in logical_units:
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
    return nodes, evidence_records, edges, reading_order


def _resolved_page_review(page_review: dict[str, Any] | None) -> dict[str, Any] | None:
    if page_review is None:
        return None
    validate_resolved_page_review(page_review)
    return deepcopy(page_review)


def _filter_logical_units_by_page_review(
    logical_units: list[dict[str, Any]], page_review: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if page_review is None:
        return logical_units
    text_flow_actions_by_page = {
        int(record["page"]): str(record.get("text_flow_action") or "")
        for record in page_review.get("pages") or []
        if isinstance(record, dict) and isinstance(record.get("page"), int)
    }
    filtered = []
    for unit in logical_units:
        pages = [int(page) for page in unit.get("pages") or [unit["page"]]]
        if all(text_flow_actions_by_page.get(page) == "include" for page in pages):
            filtered.append(unit)
    return filtered


def _observed_pipeline(document: dict[str, Any]) -> dict[str, Any]:
    metadata = _bookgraph_metadata(document)
    text_units, ignored_counts = build_text_units(document)
    layout_audit = audit_text_unit_layout(text_units, document["pages"], document["observations"])
    page_role_records = classify_observed_page_roles(document, layout_audit=layout_audit)
    classified_units = classify_text_units_by_layout(text_units, document["pages"])
    logical_units = finalize_text_units(
        classified_units,
        document["observations"],
        page_role_records,
        document["pages"],
    )
    return {
        "metadata": metadata,
        "text_units": classified_units,
        "logical_units": logical_units,
        "layout_audit": layout_audit,
        "page_role_records": page_role_records,
        "ignored_counts": ignored_counts,
    }


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
    unit_attrs = unit.get("attrs") or {}
    attrs = {
        "source_logical_unit_id": unit["unit_id"],
        "source_text_unit_id": unit_attrs.get("source_text_unit_id", unit["unit_id"]),
        "source_observation_ids": list(unit["observation_ids"]),
        "role_hints": list(unit["role_hints"]),
    }
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


def _public_bookgraph(debug_graph: dict[str, Any]) -> dict[str, Any]:
    public = deepcopy(debug_graph)
    public["metadata"] = {
        key: value
        for key, value in public["metadata"].items()
        if not key.startswith(INTERNAL_METADATA_PREFIXES)
    }
    public["nodes"] = [_public_node(node) for node in public["nodes"]]
    public["evidence"] = [_public_evidence(record) for record in public["evidence"]]
    public["edges"] = [_public_edge(edge) for edge in public["edges"]]
    public["projections"] = {
        "reading_order": list(public.get("projections", {}).get("reading_order") or [])
    }
    return make_bookgraph(
        public["metadata"],
        public["nodes"],
        public["edges"],
        public["evidence"],
        assets=public.get("assets") or {},
        projections=public["projections"],
    )


def _public_node(node: dict[str, Any]) -> dict[str, Any]:
    public = deepcopy(node)
    attrs = public.get("attrs") or {}
    public["attrs"] = {key: value for key, value in attrs.items() if key not in INTERNAL_NODE_ATTRS}  # pyright: ignore[reportOptionalMemberAccess]
    return public


def _public_edge(edge: dict[str, Any]) -> dict[str, Any]:
    public = deepcopy(edge)
    attrs = public.get("attrs") or {}
    public["attrs"] = {key: value for key, value in attrs.items() if key not in INTERNAL_NODE_ATTRS}
    return public


def _public_evidence(record: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: deepcopy(value) for key, value in record.items() if key not in INTERNAL_EVIDENCE_FIELDS
    }
    if public.get("source_kind") == "text_unit":
        public["source_kind"] = "source_span_set"
        public["source_id"] = public["evidence_id"]
    return public


def _internal_pages(
    public_graph: dict[str, Any],
    page_role_records: list[dict[str, Any]],
    page_review: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    page_roles_by_page_number = {int(record["page"]): record for record in page_role_records}
    review_by_page_number = {
        int(record["page"]): record
        for record in (page_review or {}).get("pages") or []
        if isinstance(record, dict) and isinstance(record.get("page"), int)
    }
    pages = []
    for page in public_graph.get("metadata", {}).get("pages", []):
        page_number = int(page["page"])
        pages.append(
            {
                "public": deepcopy(page),
                "debug": {
                    "page_role": deepcopy(page_roles_by_page_number.get(page_number) or {}),
                    "page_review": deepcopy(review_by_page_number.get(page_number) or {}),
                },
            }
        )
    if pages:
        return pages
    return [
        {
            "public": {"page": int(page)},
            "debug": {
                "page_role": deepcopy(record),
                "page_review": deepcopy(review_by_page_number.get(page) or {}),
            },
        }
        for page, record in sorted(page_roles_by_page_number.items())
    ]


def _internal_nodes(
    public_graph: dict[str, Any],
    debug_graph: dict[str, Any],
) -> list[dict[str, Any]]:
    public_by_id = {node["node_id"]: node for node in public_graph["nodes"]}
    records = []
    for debug_node in debug_graph["nodes"]:
        node_id = debug_node["node_id"]
        records.append(
            {
                "public": deepcopy(public_by_id[node_id]),
                "debug": {
                    "attrs": deepcopy(debug_node.get("attrs") or {}),
                    "inline_runs": deepcopy(debug_node.get("inline_runs") or []),
                },
            }
        )
    return records


def _internal_edges(
    public_graph: dict[str, Any],
    debug_graph: dict[str, Any],
) -> list[dict[str, Any]]:
    public_edges = public_graph["edges"]
    records = []
    for index, debug_edge in enumerate(debug_graph["edges"]):
        public_edge = public_edges[index] if index < len(public_edges) else {}
        records.append(
            {
                "public": deepcopy(public_edge),
                "debug": {"attrs": deepcopy(debug_edge.get("attrs") or {})},
            }
        )
    return records


def _internal_evidence(
    public_graph: dict[str, Any],
    debug_graph: dict[str, Any],
) -> list[dict[str, Any]]:
    public_by_id = {record["evidence_id"]: record for record in public_graph["evidence"]}
    records = []
    for debug_record in debug_graph["evidence"]:
        evidence_id = debug_record["evidence_id"]
        records.append(
            {
                "public": deepcopy(public_by_id[evidence_id]),
                "debug": {
                    "source_id": debug_record.get("source_id"),
                    "source_kind": debug_record.get("source_kind"),
                    "parser_payload": deepcopy(debug_record.get("parser_payload") or {}),
                },
            }
        )
    return records


def _canonical_page_role_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "page": int(record["page"]),
            "page_role": str(record["page_role"]),
            "signals": list(record.get("signals") or []),
        }
        for record in records
    ]


def _canonical_page_sizes(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "page": int(page["page"]),
            "width": float(page["width"]),
            "height": float(page["height"]),
        }
        for page in pages
    ]
