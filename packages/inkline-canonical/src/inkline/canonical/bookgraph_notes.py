from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from typing import Any

from inkline.canonical.bookgraph import make_bookgraph, validate_bookgraph
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
    attrs["source_placement"] = "page_foot"
    attrs["scope"] = "page"
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
