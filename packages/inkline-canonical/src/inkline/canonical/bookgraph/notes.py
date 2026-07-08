from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from inkline.canonical.bookgraph.footnote_text import strip_footnote_marker
from inkline.canonical.bookgraph.schema import make_bookgraph, make_edge, validate_bookgraph

_NOTE_SECTION_HEADING_PATTERN = re.compile(
    r"^\s*(?:注释|注|notes?|endnotes?)\s*$", re.IGNORECASE
)
_NOTE_SECTION_STOP_HEADING_PATTERN = re.compile(
    r"^\s*(?:参考文献|参考书目|扩展阅读|索引|出版后记|版权|bibliography|references|index)\s*$",
    re.IGNORECASE,
)
_LEADING_MARKER_PATTERN = re.compile(
    r"^\s*(?P<marker>\d{1,3}|[①-⓿❶-➓¹²³⁴⁵⁶⁷⁸⁹⁰\*†‡§]+)"
    r"(?:[\s.、．,)）]|$)"
)


@dataclass
class _NoteSectionState:
    section_id: int = 0
    in_note_section: bool = False
    source_placement: str = ""
    current_scope_key: str = ""
    current_scope_label: str = ""
    section_count: int = 0
    converted_count: int = 0

    @property
    def note_section_id(self) -> str:
        return f"ns{self.section_id:06d}"

    def enter(self, source_placement: str) -> None:
        self.section_id += 1
        self.section_count += 1
        self.in_note_section = True
        self.source_placement = source_placement
        self.current_scope_key = ""
        self.current_scope_label = ""

    def exit(self) -> None:
        self.in_note_section = False
        self.source_placement = ""
        self.current_scope_key = ""
        self.current_scope_label = ""

    def set_scope(self, text: str) -> None:
        self.current_scope_label = _scope_label(text)
        self.current_scope_key = _scope_key(self.current_scope_label)


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


def normalize_bookgraph_note_sections(graph: dict[str, Any]) -> dict[str, Any]:
    """Promote explicit note-section entries into note nodes when structure is clear."""
    normalized = normalize_bookgraph_notes(graph)
    evidence_by_id = {
        str(record["evidence_id"]): record for record in normalized["evidence"]
    }
    reading_order = list(normalized.get("projections", {}).get("reading_order") or [])
    page_count = _max_page(normalized["evidence"])
    nodes = deepcopy(normalized["nodes"])
    mutable_by_id = {str(node["node_id"]): node for node in nodes}
    state = _NoteSectionState()

    for node_id in reading_order:
        node = mutable_by_id.get(str(node_id))
        if not node:
            continue
        _update_note_section_node(node, state, evidence_by_id, page_count)
    promoted_page_foot_reference_count = _promote_page_foot_reference_nodes(
        nodes,
        evidence_by_id,
        _page_sizes_from_metadata(normalized["metadata"]),
    )

    metadata = {
        **normalized["metadata"],
        "shadow_note_section_detection": {
            "explicit_note_section_count": state.section_count,
            "promoted_note_count": state.converted_count,
            "promoted_page_foot_reference_count": promoted_page_foot_reference_count,
        },
    }
    return make_bookgraph(
        metadata,
        nodes,
        normalized["edges"],
        normalized["evidence"],
        assets=normalized.get("assets") or {},
        projections=normalized.get("projections") or {},
    )


def resolve_bookgraph_note_refs(graph: dict[str, Any]) -> dict[str, Any]:
    """Resolve deterministic page-foot and explicit note-section references."""
    normalized = normalize_bookgraph_note_sections(graph)
    page_resolved = _resolve_page_footnote_refs_normalized(normalized)
    return _resolve_scoped_note_refs_normalized(page_resolved)


def resolve_page_footnote_refs(graph: dict[str, Any]) -> dict[str, Any]:
    """Link note_ref runs to same-page page-foot notes when marker evidence is unique."""
    normalized = normalize_bookgraph_notes(graph)
    return _resolve_page_footnote_refs_normalized(normalized)


def _resolve_page_footnote_refs_normalized(graph: dict[str, Any]) -> dict[str, Any]:
    evidence_by_id = {
        str(record["evidence_id"]): record for record in graph["evidence"]
    }
    notes_by_page_marker = _page_foot_notes_by_page_marker(
        graph["nodes"], evidence_by_id
    )
    nodes = deepcopy(graph["nodes"])
    edges = deepcopy(graph["edges"])
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
        **graph["metadata"],
        "shadow_note_ref_resolution": dict(counts),
    }
    return make_bookgraph(
        metadata,
        nodes,
        edges,
        graph["evidence"],
        assets=graph.get("assets") or {},
        projections=graph.get("projections") or {},
    )


def _resolve_scoped_note_refs_normalized(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = deepcopy(graph["nodes"])
    edges = deepcopy(graph["edges"])
    reading_order = [str(node_id) for node_id in graph["projections"].get("reading_order") or []]
    nodes_by_id = {str(node["node_id"]): node for node in nodes}
    scope_by_node = _body_scope_by_node(reading_order, nodes_by_id)
    notes_by_scope_marker = _scoped_notes_by_marker(nodes)
    existing_edges = {
        (str(edge.get("edge_type")), str(edge.get("source")), str(edge.get("target")))
        for edge in edges
    }
    counts = Counter(
        {
            "scoped_note_resolved": 0,
            "scoped_note_ambiguous": 0,
            "scoped_note_unresolved": 0,
        }
    )

    for node in nodes:
        if node.get("node_type") == "note" or _in_note_section(node):
            continue
        scope_key = scope_by_node.get(str(node["node_id"])) or ""
        for run in node.get("inline_runs") or []:
            if not isinstance(run, dict) or run.get("type") != "note_ref":
                continue
            if _note_ref_target(run):
                continue
            marker = _note_ref_marker(run)
            if not marker:
                continue
            candidates = _scoped_note_candidates(notes_by_scope_marker, marker, scope_key)
            if len(candidates) == 1:
                note = candidates[0]
                note_attrs = note.get("attrs") if isinstance(note.get("attrs"), dict) else {}
                _set_scoped_note_ref_target(run, marker, note)
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
                                "source_placement": str(
                                    note_attrs.get("source_placement") or "note_section"
                                ),
                                "scope": str(note_attrs.get("scope") or "unknown"),
                                "match_confidence": "exact",
                            },
                        )
                    )
                    existing_edges.add(edge_key)
                counts["scoped_note_resolved"] += 1
            elif candidates:
                counts["scoped_note_ambiguous"] += 1
            else:
                counts["scoped_note_unresolved"] += 1

    metadata = {
        **graph["metadata"],
        "shadow_scoped_note_ref_resolution": dict(counts),
    }
    return make_bookgraph(
        metadata,
        nodes,
        edges,
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


def _is_note_section_heading_text(text: str) -> bool:
    return bool(_NOTE_SECTION_HEADING_PATTERN.match(_first_line(text)))


def _is_note_section_stop_heading_text(text: str) -> bool:
    return bool(_NOTE_SECTION_STOP_HEADING_PATTERN.match(_first_line(text)))


def _first_line(text: str) -> str:
    return re.sub(r"\s+", " ", text.split("\n", 1)[0]).strip()


def _scope_label(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _scope_key(text: str) -> str:
    return re.sub(r"\s+", "", text).strip().lower()


def _max_page(evidence: list[dict[str, Any]]) -> int:
    pages = [
        page
        for record in evidence
        for page in (record.get("pages") or ([record.get("page")] if record.get("page") else []))
        if isinstance(page, int)
    ]
    return max(pages) if pages else 0


def _first_node_page(
    node: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> int | None:
    pages = sorted(_node_pages(node, evidence_by_id))
    return pages[0] if pages else None


def _note_section_source_placement(page: int | None, page_count: int) -> str:
    if page is not None and page_count > 0 and page >= max(1, round(page_count * 0.6)):
        return "book_end"
    return "chapter_end"


def _note_section_scope(source_placement: str, scope_key: str) -> str:
    if scope_key:
        return "chapter"
    if source_placement == "book_end":
        return "book"
    return "unknown"


def _in_note_section(node: dict[str, Any]) -> bool:
    attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
    return bool(attrs.get("note_section_id"))


def _body_scope_by_node(
    reading_order: list[str], nodes_by_id: dict[str, dict[str, Any]]
) -> dict[str, str]:
    scope_by_node: dict[str, str] = {}
    current_scope = ""
    for node_id in reading_order:
        node = nodes_by_id.get(str(node_id))
        if not node:
            continue
        if _in_note_section(node):
            continue
        if node.get("node_type") == "heading":
            current_scope = _scope_key(str(node.get("text") or ""))
        if current_scope:
            scope_by_node[str(node["node_id"])] = current_scope
    return scope_by_node


def _scoped_notes_by_marker(
    nodes: list[dict[str, Any]]
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    notes: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for node in nodes:
        if node.get("node_type") != "note":
            continue
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        if attrs.get("source_placement") == "page_foot":
            continue
        marker = str(attrs.get("marker") or "").strip()
        if not marker:
            continue
        scope = str(attrs.get("scope") or "unknown")
        scope_key = str(attrs.get("scope_key") or "")
        notes.setdefault((scope, scope_key, marker), []).append(node)
    return notes


def _scoped_note_candidates(
    notes_by_scope_marker: dict[tuple[str, str, str], list[dict[str, Any]]],
    marker: str,
    scope_key: str,
) -> list[dict[str, Any]]:
    if scope_key:
        scoped = notes_by_scope_marker.get(("chapter", scope_key, marker), [])
        if scoped:
            return _unique_nodes(scoped)
    return _unique_nodes(notes_by_scope_marker.get(("book", "", marker), []))


def _set_scoped_note_ref_target(
    run: dict[str, Any], marker: str, note: dict[str, Any]
) -> None:
    note_attrs = note.get("attrs") if isinstance(note.get("attrs"), dict) else {}
    attrs = run.setdefault("attrs", {})
    attrs["marker"] = marker
    attrs["target_note_id"] = str(note["node_id"])
    attrs["source_placement"] = str(note_attrs.get("source_placement") or "note_section")
    attrs["scope"] = str(note_attrs.get("scope") or "unknown")
    if note_attrs.get("scope_key"):
        attrs["scope_key"] = str(note_attrs["scope_key"])
    attrs["match_confidence"] = "exact"


def _update_note_section_node(
    node: dict[str, Any],
    state: _NoteSectionState,
    evidence_by_id: dict[str, dict[str, Any]],
    page_count: int,
) -> None:
    text = str(node.get("text") or "")
    node_type = str(node.get("node_type") or "")
    if node_type == "heading" and _is_note_section_heading_text(text):
        state.enter(
            _note_section_source_placement(_first_node_page(node, evidence_by_id), page_count)
        )
        node.setdefault("attrs", {})["note_section_id"] = state.note_section_id
        return
    if not state.in_note_section:
        return
    if node_type == "heading" and _is_note_section_stop_heading_text(text):
        state.exit()
        return
    if node_type == "heading":
        state.set_scope(text)
        node.setdefault("attrs", {})["note_section_id"] = state.note_section_id
        return
    _maybe_promote_note_section_entry(node, state, text, node_type)


def _maybe_promote_note_section_entry(
    node: dict[str, Any], state: _NoteSectionState, text: str, node_type: str
) -> None:
    if node_type not in {"note", "paragraph", "list_item"}:
        return
    marker = _note_marker(text, node.get("attrs") or {})
    if node_type != "note" and not marker:
        return
    attrs = node.setdefault("attrs", {})
    attrs["note_section_id"] = state.note_section_id
    attrs["marker"] = marker
    attrs["source_placement"] = state.source_placement or "note_section"
    attrs["scope"] = _note_section_scope(state.source_placement, state.current_scope_key)
    attrs["source_text_unit_ids"] = _source_text_unit_ids(node)
    if state.current_scope_key:
        attrs["scope_key"] = state.current_scope_key
        attrs["scope_label"] = state.current_scope_label
    if node_type == "note":
        return
    node["node_type"] = "note"
    node["text"] = strip_footnote_marker(text, {"note_marker": marker})
    state.converted_count += 1


def _promote_page_foot_reference_nodes(
    nodes: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    page_sizes: dict[int, dict[str, float]],
) -> int:
    reference_nodes_by_page = _reference_text_nodes_by_page(nodes, evidence_by_id)
    promoted_count = 0
    for page, page_nodes in reference_nodes_by_page.items():
        if len(page_nodes) > 10:
            continue
        page_height = page_sizes.get(page, {}).get("height")
        if not page_height:
            continue
        for node in page_nodes:
            if _in_note_section(node) or node.get("node_type") == "note":
                continue
            marker = _note_marker(str(node.get("text") or ""), node.get("attrs") or {})
            if not marker or not _node_starts_in_page_foot(node, evidence_by_id, page_height):
                continue
            attrs = node.setdefault("attrs", {})
            node["node_type"] = "note"
            node["text"] = strip_footnote_marker(
                str(node.get("text") or ""), {"note_marker": marker}
            )
            attrs["marker"] = marker
            attrs["source_placement"] = "page_foot"
            attrs["scope"] = "page"
            attrs["source_text_unit_ids"] = _source_text_unit_ids(node)
            attrs["page_foot_promotion"] = "bottom_reference_text"
            promoted_count += 1
    return promoted_count


def _reference_text_nodes_by_page(
    nodes: list[dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]]
) -> dict[int, list[dict[str, Any]]]:
    by_page: dict[int, list[dict[str, Any]]] = {}
    for node in nodes:
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        if "reference_text" not in attrs.get("role_hints", []):
            continue
        for page in _node_pages(node, evidence_by_id):
            by_page.setdefault(page, []).append(node)
    return by_page


def _node_starts_in_page_foot(
    node: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
    page_height: float,
) -> bool:
    top_values = []
    for evidence_id in node.get("evidence_ids") or []:
        evidence = evidence_by_id.get(str(evidence_id))
        bbox = evidence.get("bbox") if isinstance(evidence, dict) else None
        if isinstance(bbox, list) and len(bbox) == 4 and isinstance(bbox[1], int | float):
            top_values.append(float(bbox[1]))
    return bool(top_values) and min(top_values) / page_height >= 0.55


def _page_sizes_from_metadata(metadata: dict[str, Any]) -> dict[int, dict[str, float]]:
    sizes: dict[int, dict[str, float]] = {}
    for record in metadata.get("shadow_page_sizes") or []:
        if not isinstance(record, dict):
            continue
        page = record.get("page")
        width = record.get("width")
        height = record.get("height")
        if isinstance(page, int) and isinstance(width, int | float) and isinstance(
            height, int | float
        ):
            sizes[page] = {"width": float(width), "height": float(height)}
    return sizes


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
