from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from typing import Any

from inkline.canonical.bookgraph import make_bookgraph, make_edge, validate_bookgraph
from inkline.canonical.footnote_text import strip_footnote_marker

_LEADING_MARKER_PATTERN = re.compile(
    r"^\s*(?P<marker>\d{1,3}|[①-⓿❶-➓¹²³⁴⁵⁶⁷⁸⁹⁰\*†‡§]+)"
    r"(?:[\s.、．,)）]|$)"
)


def normalize_bookgraph_notes(graph: dict[str, Any]) -> dict[str, Any]:
    """Convert legacy footnote nodes into the Phase 4 unified note node shape."""
    validate_bookgraph(graph)
    nodes = [_normalize_node_notes(node) for node in graph["nodes"]]
    return make_bookgraph(
        graph["metadata"],
        nodes,
        graph["edges"],
        graph["evidence"],
        assets=graph.get("assets") or {},
        projections=graph.get("projections") or {},
    )


def resolve_page_footnote_refs(graph: dict[str, Any]) -> dict[str, Any]:
    """Link note_ref runs to same-page page-foot notes when marker evidence is unique."""
    normalized = normalize_bookgraph_notes(graph)
    evidence_by_id = {
        str(record["evidence_id"]): record for record in normalized["evidence"]
    }
    notes_by_page_marker = _page_foot_notes_by_page_marker(
        normalized["nodes"], evidence_by_id
    )
    nodes = deepcopy(normalized["nodes"])
    edges = deepcopy(normalized["edges"])
    existing_edges = {
        (str(edge.get("edge_type")), str(edge.get("source")), str(edge.get("target")))
        for edge in edges
    }
    counts = Counter(
        {
            "page_footnote_resolved": 0,
            "page_footnote_ambiguous": 0,
            "page_footnote_unresolved": 0,
        }
    )

    for node in nodes:
        if node.get("node_type") == "note":
            continue
        node_pages = _node_pages(node, evidence_by_id)
        for run in node.get("inline_runs") or []:
            if not isinstance(run, dict) or run.get("type") != "note_ref":
                continue
            if _note_ref_target(run):
                continue
            marker = _note_ref_marker(run)
            if not marker:
                continue
            candidates = [
                candidate
                for page in sorted(node_pages)
                for candidate in notes_by_page_marker.get((page, marker), [])
            ]
            unique_candidates = _unique_nodes(candidates)
            if len(unique_candidates) == 1:
                note = unique_candidates[0]
                _set_note_ref_target(run, marker, note["node_id"])
                edge_key = ("references_note", str(node["node_id"]), str(note["node_id"]))
                if edge_key not in existing_edges:
                    edges.append(
                        make_edge(
                            "references_note",
                            str(node["node_id"]),
                            str(note["node_id"]),
                            evidence_ids=_edge_evidence_ids(node, note),
                            attrs={
                                "marker": marker,
                                "source_placement": "page_foot",
                                "scope": "page",
                                "match_confidence": "exact",
                            },
                        )
                    )
                    existing_edges.add(edge_key)
                counts["page_footnote_resolved"] += 1
            elif unique_candidates:
                counts["page_footnote_ambiguous"] += 1
            else:
                counts["page_footnote_unresolved"] += 1

    metadata = {
        **normalized["metadata"],
        "shadow_note_ref_resolution": dict(counts),
    }
    return make_bookgraph(
        metadata,
        nodes,
        edges,
        normalized["evidence"],
        assets=normalized.get("assets") or {},
        projections=normalized.get("projections") or {},
    )


def audit_bookgraph_notes(graph: dict[str, Any]) -> dict[str, Any]:
    validate_bookgraph(graph)
    note_ids = {
        str(node["node_id"]) for node in graph["nodes"] if node.get("node_type") == "note"
    }
    referenced_note_ids = {
        str(edge["target"])
        for edge in graph["edges"]
        if edge.get("edge_type") == "references_note" and edge.get("target") in note_ids
    }
    note_ref_counts = _note_ref_counts(graph["nodes"])
    return {
        "note_count": len(note_ids),
        "legacy_footnote_count": sum(
            1 for node in graph["nodes"] if node.get("node_type") == "footnote"
        ),
        "references_note_edge_count": sum(
            1 for edge in graph["edges"] if edge.get("edge_type") == "references_note"
        ),
        "resolved_note_ref_count": note_ref_counts["resolved"],
        "unresolved_note_ref_count": note_ref_counts["unresolved"],
        "orphan_note_count": len(note_ids - referenced_note_ids),
        "notes_by_source_placement": dict(
            sorted(_note_attr_counts(graph["nodes"], "source_placement").items())
        ),
        "notes_by_scope": dict(sorted(_note_attr_counts(graph["nodes"], "scope").items())),
    }


def _page_foot_notes_by_page_marker(
    nodes: list[dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]]
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    notes: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for node in nodes:
        if node.get("node_type") != "note":
            continue
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        if attrs.get("source_placement") != "page_foot" or attrs.get("scope") != "page":
            continue
        marker = str(attrs.get("marker") or "").strip()
        if not marker:
            continue
        for page in _node_pages(node, evidence_by_id):
            notes.setdefault((page, marker), []).append(node)
    return notes


def _node_pages(
    node: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> set[int]:
    pages: set[int] = set()
    for evidence_id in node.get("evidence_ids") or []:
        evidence = evidence_by_id.get(str(evidence_id))
        if not evidence:
            continue
        evidence_pages = evidence.get("pages")
        if isinstance(evidence_pages, list):
            pages.update(page for page in evidence_pages if isinstance(page, int))
        page = evidence.get("page")
        if isinstance(page, int):
            pages.add(page)
    return pages


def _unique_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node["node_id"])
        if node_id in seen:
            continue
        seen.add(node_id)
        unique.append(node)
    return unique


def _note_ref_marker(run: dict[str, Any]) -> str:
    attrs = run.get("attrs") if isinstance(run.get("attrs"), dict) else {}
    marker = attrs.get("marker") or run.get("marker") or run.get("text")
    return str(marker or "").strip()


def _note_ref_target(run: dict[str, Any]) -> str:
    attrs = run.get("attrs") if isinstance(run.get("attrs"), dict) else {}
    return str(attrs.get("target_note_id") or run.get("target_note_id") or "").strip()


def _set_note_ref_target(run: dict[str, Any], marker: str, note_id: str) -> None:
    attrs = run.setdefault("attrs", {})
    attrs["marker"] = marker
    attrs["target_note_id"] = note_id
    attrs["source_placement"] = "page_foot"
    attrs["scope"] = "page"
    attrs["match_confidence"] = "exact"


def _edge_evidence_ids(source_node: dict[str, Any], target_node: dict[str, Any]) -> list[str]:
    evidence_ids: list[str] = []
    for evidence_id in [*source_node.get("evidence_ids", []), *target_node.get("evidence_ids", [])]:
        if isinstance(evidence_id, str) and evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
    return evidence_ids


def _normalize_node_notes(node: dict[str, Any]) -> dict[str, Any]:
    if node.get("node_type") != "footnote":
        return deepcopy(node)

    normalized = deepcopy(node)
    attrs = normalized.setdefault("attrs", {})
    marker = _note_marker(str(normalized.get("text") or ""), attrs)
    normalized["node_type"] = "note"
    normalized["text"] = strip_footnote_marker(
        str(normalized.get("text") or ""),
        {"note_marker": marker} if marker else None,
    )
    attrs["marker"] = marker
    source_placement, scope = _note_source_scope(attrs)
    attrs["source_placement"] = source_placement
    attrs["scope"] = scope
    attrs["source_text_unit_ids"] = _source_text_unit_ids(normalized)
    return normalized


def _note_marker(text: str, attrs: dict[str, Any]) -> str:
    explicit_marker = attrs.get("note_marker") or attrs.get("marker")
    if isinstance(explicit_marker, str):
        return explicit_marker.strip()
    match = _LEADING_MARKER_PATTERN.match(text)
    return match.group("marker").strip() if match else ""


def _source_text_unit_ids(node: dict[str, Any]) -> list[str]:
    attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
    source_text_unit_id = attrs.get("source_text_unit_id")
    if isinstance(source_text_unit_id, str) and source_text_unit_id:
        return [source_text_unit_id]
    return [str(node["node_id"])]


def _note_source_scope(attrs: dict[str, Any]) -> tuple[str, str]:
    if attrs.get("page_role") == "note_section_candidate":
        return "note_section_candidate", "unknown"
    return "page_foot", "page"


def _note_ref_counts(nodes: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in nodes:
        for run in node.get("inline_runs") or []:
            if not isinstance(run, dict) or run.get("type") != "note_ref":
                continue
            attrs = run.get("attrs") if isinstance(run.get("attrs"), dict) else {}
            if attrs.get("target_note_id") or run.get("target_note_id"):
                counts["resolved"] += 1
            else:
                counts["unresolved"] += 1
    return counts


def _note_attr_counts(nodes: list[dict[str, Any]], attr: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in nodes:
        if node.get("node_type") != "note":
            continue
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        counts[str(attrs.get(attr) or "unknown")] += 1
    return counts
