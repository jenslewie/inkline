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
from inkline.canonical.bookgraph_notes import resolve_bookgraph_note_refs
from inkline.canonical.internal_canonical import make_internal_canonical
from inkline.canonical.observed import validate_observed_document
from inkline.canonical.page_roles import classify_observed_page_roles, page_roles_by_page
from inkline.canonical.text_unit_layout import (
    audit_text_unit_layout,
    classify_text_units_by_layout,
)
from inkline.canonical.text_units import build_text_units

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


def build_bookgraph_from_observed(document: dict[str, Any]) -> dict[str, Any]:
    return build_observed_bookgraph_artifacts(document)["public_graph"]


def build_internal_canonical_from_observed(document: dict[str, Any]) -> dict[str, Any]:
    artifacts = build_observed_bookgraph_artifacts(document)
    return make_internal_canonical(
        artifacts["public_graph"],
        pages=_internal_pages(artifacts["public_graph"], artifacts["page_role_records"]),
        nodes=_internal_nodes(artifacts["public_graph"], artifacts["debug_graph"]),
        edges=_internal_edges(artifacts["public_graph"], artifacts["debug_graph"]),
        evidence=_internal_evidence(artifacts["public_graph"], artifacts["debug_graph"]),
        pipeline={
            "observed_document": deepcopy(document),
            "text_units": deepcopy(artifacts["text_units"]),
            "logical_units": deepcopy(artifacts["logical_units"]),
            "layout_audit": deepcopy(artifacts["layout_audit"]),
            "page_roles": deepcopy(artifacts["page_role_records"]),
            "ignored_observation_counts": deepcopy(artifacts["ignored_counts"]),
            "bookgraph_debug_metadata": deepcopy(artifacts["debug_graph"]["metadata"]),
        },
    )


def build_observed_bookgraph_artifacts(document: dict[str, Any]) -> dict[str, Any]:
    validate_observed_document(document)
    pipeline = _observed_pipeline(document)
    nodes: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    reading_order: list[str] = []
    parser = str(pipeline["metadata"].get("parser_name") or "")
    roles_by_page = page_roles_by_page(pipeline["page_role_records"])

    for unit in pipeline["logical_units"]:
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

    metadata = pipeline["metadata"]
    metadata["shadow_ignored_observation_counts"] = pipeline["ignored_counts"]
    metadata["shadow_text_unit_layout_audit_summary"] = pipeline["layout_audit"]["summary"]
    metadata["shadow_text_unit_layout_page_coverage"] = pipeline["layout_audit"]["page_coverage"]
    metadata["shadow_text_unit_layout_profile_quality"] = pipeline["layout_audit"][
        "profile_quality"
    ]
    metadata["shadow_page_roles"] = _canonical_page_role_records(pipeline["page_role_records"])
    metadata["shadow_page_sizes"] = _canonical_page_sizes(document["pages"])
    projections = {"reading_order": reading_order}
    debug_graph = make_bookgraph(
        metadata,
        nodes,
        edges,
        evidence_records,
        assets=deepcopy(document.get("assets") or {}),
        projections=projections,
    )
    resolved_debug_graph = resolve_bookgraph_note_refs(debug_graph)
    public_graph = _public_bookgraph(resolved_debug_graph)
    return {
        "public_graph": public_graph,
        "debug_graph": resolved_debug_graph,
        "text_units": pipeline["text_units"],
        "logical_units": pipeline["logical_units"],
        "layout_audit": pipeline["layout_audit"],
        "page_role_records": pipeline["page_role_records"],
        "ignored_counts": pipeline["ignored_counts"],
    }


def _observed_pipeline(document: dict[str, Any]) -> dict[str, Any]:
    metadata = _bookgraph_metadata(document)
    text_units, ignored_counts = build_text_units(document)
    layout_audit = audit_text_unit_layout(text_units, document["pages"], document["observations"])
    page_role_records = classify_observed_page_roles(document, layout_audit=layout_audit)
    classified_units = classify_text_units_by_layout(text_units, document["pages"])
    logical_units = _logical_units_from_text_units(classified_units, document["observations"])
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


def _logical_units_from_text_units(
    text_units: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    observations_by_id = {observation["observation_id"]: observation for observation in observations}
    logical_units: list[dict[str, Any]] = []
    for unit in text_units:
        logical_units.extend(_logical_units_from_text_unit(unit, observations_by_id))
    for index, unit in enumerate(logical_units, start=1):
        unit["unit_id"] = f"lu{index:06d}"
    return logical_units


def _logical_units_from_text_unit(
    unit: dict[str, Any],
    observations_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if unit.get("unit_type") != "paragraph":
        logical = deepcopy(unit)
        logical["attrs"] = deepcopy(unit.get("attrs") or {})
        logical["attrs"]["source_text_unit_id"] = unit["unit_id"]
        return [logical]

    observation_ids = list(unit.get("observation_ids") or [])
    merge_reasons = list((unit.get("attrs") or {}).get("merge_reasons") or [])
    if not observation_ids or "same_page_geometry_continuation" not in merge_reasons:
        logical = deepcopy(unit)
        logical["attrs"] = deepcopy(unit.get("attrs") or {})
        logical["attrs"]["source_text_unit_id"] = unit["unit_id"]
        return [logical]

    groups: list[list[str]] = [[observation_ids[0]]]
    group_merge_reasons: list[list[str]] = [[]]
    for index, observation_id in enumerate(observation_ids[1:]):
        reason = merge_reasons[index] if index < len(merge_reasons) else ""
        if reason == "same_page_geometry_continuation":
            groups.append([observation_id])
            group_merge_reasons.append([])
            continue
        groups[-1].append(observation_id)
        group_merge_reasons[-1].append(reason)

    logical_units = []
    for group_index, group in enumerate(groups, start=1):
        logical_units.append(
            _logical_unit_from_observation_group(
                unit,
                group,
                group_merge_reasons[group_index - 1],
                observations_by_id,
                logical_split_reason="same_page_geometry_continuation",
            )
        )
    return logical_units


def _logical_unit_from_observation_group(
    source_unit: dict[str, Any],
    observation_ids: list[str],
    merge_reasons: list[str],
    observations_by_id: dict[str, dict[str, Any]],
    *,
    logical_split_reason: str,
) -> dict[str, Any]:
    observations = [observations_by_id[observation_id] for observation_id in observation_ids]
    pages: list[int] = []
    spans: list[dict[str, Any]] = []
    parser_payloads: list[dict[str, Any]] = []
    role_hints: list[str] = []
    attrs: dict[str, Any] = {"source_text_unit_id": source_unit["unit_id"]}
    attrs["logical_split_reason"] = logical_split_reason
    if merge_reasons:
        attrs["merge_reasons"] = list(merge_reasons)
    bbox = None
    text_parts: list[str] = []
    for observation in observations:
        text = str(observation.get("text") or "")
        if text:
            text_parts.append(text)
        page = int(observation["page"])
        if page not in pages:
            pages.append(page)
        spans.extend(_observation_spans(observation))
        parser_payloads.append(deepcopy(observation.get("parser_payload") or {}))
        role_hint = str(observation.get("role_hint") or "")
        if role_hint and role_hint not in role_hints:
            role_hints.append(role_hint)
        observation_attrs = observation.get("attrs") if isinstance(observation.get("attrs"), dict) else {}
        inline_runs = observation_attrs.get("inline_runs")
        if isinstance(inline_runs, list):
            attrs.setdefault("inline_runs", []).extend(deepcopy(inline_runs))
        note_refs = observation_attrs.get("note_refs")
        if isinstance(note_refs, list):
            attrs.setdefault("note_refs", []).extend(deepcopy(note_refs))
        observation_bbox = observation.get("bbox")
        if _valid_bbox(observation_bbox):
            bbox = _union_bbox(bbox, observation_bbox) if bbox is not None else deepcopy(observation_bbox)
    return {
        "unit_id": source_unit["unit_id"],
        "unit_type": source_unit["unit_type"],
        "text": "\n".join(text_parts),
        "page": pages[0],
        "pages": pages,
        "bbox": bbox,
        "spans": spans,
        "observation_ids": list(observation_ids),
        "role_hints": role_hints,
        "attrs": attrs,
        "parser_payloads": parser_payloads,
    }


def _observation_spans(observation: dict[str, Any]) -> list[dict[str, Any]]:
    spans = observation.get("spans")
    if isinstance(spans, list) and spans:
        return deepcopy(spans)
    bbox = observation.get("bbox")
    if _valid_bbox(bbox):
        return [{"page": observation["page"], "bbox": deepcopy(bbox)}]
    return []


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )


def _union_bbox(left: list[float] | None, right: list[float]) -> list[float]:
    if left is None:
        return deepcopy(right)
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]


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
    attrs = public.get("attrs") if isinstance(public.get("attrs"), dict) else {}
    public["attrs"] = {
        key: value for key, value in attrs.items() if key not in INTERNAL_NODE_ATTRS
    }
    return public


def _public_edge(edge: dict[str, Any]) -> dict[str, Any]:
    public = deepcopy(edge)
    attrs = public.get("attrs") if isinstance(public.get("attrs"), dict) else {}
    public["attrs"] = {
        key: value for key, value in attrs.items() if key not in INTERNAL_NODE_ATTRS
    }
    return public


def _public_evidence(record: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: deepcopy(value)
        for key, value in record.items()
        if key not in INTERNAL_EVIDENCE_FIELDS
    }
    if public.get("source_kind") == "text_unit":
        public["source_kind"] = "source_span_set"
        public["source_id"] = public["evidence_id"]
    return public


def _internal_pages(
    public_graph: dict[str, Any],
    page_role_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    page_roles_by_page_number = {
        int(record["page"]): record for record in page_role_records
    }
    pages = []
    for page in public_graph.get("metadata", {}).get("pages", []):
        page_number = int(page["page"])
        pages.append(
            {
                "public": deepcopy(page),
                "debug": deepcopy(page_roles_by_page_number.get(page_number) or {}),
            }
        )
    if pages:
        return pages
    return [
        {"public": {"page": int(page)}, "debug": deepcopy(record)}
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
