#!/usr/bin/env python3
"""Summarize Phase 3 observed-shadow BookGraph acceptance signals."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from inkline.canonical import validate_bookgraph
from inkline.canonical.schema import ValidationError


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = check_phase3_shadow_acceptance(args.bookgraph)
    if args.output:
        _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


def check_phase3_shadow_acceptance(paths: list[Path]) -> dict[str, Any]:
    books = [_book_report(path) for path in paths]
    return {
        "status": "pass" if all(not book["errors"] for book in books) else "fail",
        "totals": _totals(books),
        "books": books,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check structural acceptance signals for one or more Phase 3 "
            "ObservedDocument BookGraph shadow outputs."
        )
    )
    parser.add_argument("bookgraph", nargs="+", type=Path, help="BookGraph shadow JSON path")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path")
    return parser


def _book_report(path: Path) -> dict[str, Any]:
    graph = _read_json(path)
    errors = _validation_errors(graph)
    metadata = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    evidence = graph.get("evidence") if isinstance(graph.get("evidence"), list) else []
    projections = graph.get("projections") if isinstance(graph.get("projections"), dict) else {}
    reading_order = (
        projections.get("reading_order")
        if isinstance(projections.get("reading_order"), list)
        else []
    )
    node_counts = dict(sorted(Counter(_node_types(nodes)).items()))
    node_counts_by_flow_scope = _node_counts_by_flow_scope(nodes)
    node_counts_by_rag_inclusion = _node_counts_by_rag_inclusion(nodes)

    errors.extend(_structural_errors(nodes, evidence, reading_order))
    return {
        "path": str(path),
        "doc_id": metadata.get("doc_id") or "",
        "title": metadata.get("title") or "",
        "node_counts": node_counts,
        "node_counts_by_flow_scope": node_counts_by_flow_scope,
        "node_counts_by_rag_inclusion": node_counts_by_rag_inclusion,
        "page_role_counts": _page_role_counts(metadata),
        "node_count": len(nodes),
        "evidence_count": len(evidence),
        "reading_order_count": len(reading_order),
        "rag_unit_count": len(projections.get("rag_units") or []),
        "ignored_counts": _ignored_counts(metadata),
        "merge_counts": _merge_counts(nodes),
        "multi_page_evidence_count": _multi_page_evidence_count(evidence),
        "audit_summary": metadata.get("shadow_text_unit_layout_audit_summary") or {},
        "profile_quality": metadata.get("shadow_text_unit_layout_profile_quality") or {},
        "errors": sorted(set(errors)),
    }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _validation_errors(graph: dict[str, Any]) -> list[str]:
    try:
        validate_bookgraph(graph)
    except ValidationError as exc:
        return [f"schema_validation_failed:{exc}"]
    return []


def _structural_errors(
    nodes: list[Any], evidence: list[Any], reading_order: list[Any]
) -> list[str]:
    errors: list[str] = []
    if not nodes:
        errors.append("no_nodes")
    if not evidence:
        errors.append("no_evidence")
    if not reading_order:
        errors.append("no_reading_order")
    if len(reading_order) != len(nodes):
        errors.append("reading_order_node_count_mismatch")
    return errors


def _node_types(nodes: list[Any]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("node_type"), str):
            values.append(node["node_type"])
    return values


def _node_counts_by_flow_scope(nodes: list[Any]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("node_type"), str):
            continue
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        flow_scope = str(attrs.get("flow_scope") or "unknown")
        counts.setdefault(flow_scope, Counter())[node["node_type"]] += 1
    return _nested_counts(counts)


def _node_counts_by_rag_inclusion(nodes: list[Any]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("node_type"), str):
            continue
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        key = "excluded" if attrs.get("include_in_rag") is False else "included"
        counts.setdefault(key, Counter())[node["node_type"]] += 1
    return _nested_counts(counts)


def _page_role_counts(metadata: dict[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    page_roles = metadata.get("shadow_page_roles")
    if not isinstance(page_roles, list):
        return {}
    for record in page_roles:
        if not isinstance(record, dict):
            continue
        counts[str(record.get("page_role") or "unknown")] += 1
    return dict(sorted(counts.items()))


def _nested_counts(counts: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
    return {
        group: dict(sorted(group_counts.items())) for group, group_counts in sorted(counts.items())
    }


def _ignored_counts(metadata: dict[str, Any]) -> dict[str, int]:
    counts = (
        metadata.get("shadow_ignored_observation_counts")
        or metadata.get("shadow_ignored_block_counts")
        or {}
    )
    if not isinstance(counts, dict):
        return {}
    return {str(key): int(value) for key, value in sorted(counts.items()) if isinstance(value, int)}


def _merge_counts(nodes: list[Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        reasons = attrs.get("merge_reasons") if isinstance(attrs.get("merge_reasons"), list) else []
        counts.update(str(reason) for reason in reasons)
    return dict(sorted(counts.items()))


def _multi_page_evidence_count(evidence: list[Any]) -> int:
    count = 0
    for record in evidence:
        if not isinstance(record, dict):
            continue
        pages = record.get("pages") if isinstance(record.get("pages"), list) else []
        unique_pages = {page for page in pages if isinstance(page, int)}
        if len(unique_pages) > 1:
            count += 1
    return count


def _totals(books: list[dict[str, Any]]) -> dict[str, Any]:
    node_counts: Counter[str] = Counter()
    node_counts_by_flow_scope: dict[str, Counter[str]] = {}
    node_counts_by_rag_inclusion: dict[str, Counter[str]] = {}
    page_role_counts: Counter[str] = Counter()
    ignored_counts: Counter[str] = Counter()
    merge_counts: Counter[str] = Counter()
    for book in books:
        node_counts.update(book["node_counts"])
        _update_nested_counts(node_counts_by_flow_scope, book["node_counts_by_flow_scope"])
        _update_nested_counts(node_counts_by_rag_inclusion, book["node_counts_by_rag_inclusion"])
        page_role_counts.update(book["page_role_counts"])
        ignored_counts.update(book["ignored_counts"])
        merge_counts.update(book["merge_counts"])
    return {
        "book_count": len(books),
        "node_counts": dict(sorted(node_counts.items())),
        "node_counts_by_flow_scope": _nested_counts(node_counts_by_flow_scope),
        "node_counts_by_rag_inclusion": _nested_counts(node_counts_by_rag_inclusion),
        "page_role_counts": dict(sorted(page_role_counts.items())),
        "node_count": sum(book["node_count"] for book in books),
        "evidence_count": sum(book["evidence_count"] for book in books),
        "reading_order_count": sum(book["reading_order_count"] for book in books),
        "rag_unit_count": sum(book["rag_unit_count"] for book in books),
        "ignored_counts": dict(sorted(ignored_counts.items())),
        "merge_counts": dict(sorted(merge_counts.items())),
        "multi_page_evidence_count": sum(book["multi_page_evidence_count"] for book in books),
    }


def _update_nested_counts(
    target: dict[str, Counter[str]], source: dict[str, dict[str, int]]
) -> None:
    for group, counts in source.items():
        target.setdefault(group, Counter()).update(counts)


if __name__ == "__main__":
    sys.exit(main())
