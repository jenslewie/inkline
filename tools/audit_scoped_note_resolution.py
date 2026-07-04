#!/usr/bin/env python3
"""Audit deterministic scoped note_ref resolution for BookGraph artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from inkline.canonical import validate_bookgraph

SCOPED_PLACEMENTS = {"chapter_end", "book_end", "note_section"}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_scoped_note_resolution_many(args.graphs, sample_limit=args.sample_limit)
    if args.output:
        _write_json(args.output, report)
    if args.markdown_output:
        _write_text(args.markdown_output, render_markdown_report(report))
    printed_report = _summary_only(report) if args.summary_only else report
    print(json.dumps(printed_report, ensure_ascii=False, indent=2))
    return 0


def audit_scoped_note_resolution_many(
    graph_paths: list[Path], *, sample_limit: int = 30
) -> dict[str, Any]:
    books = [audit_scoped_note_resolution(path, sample_limit=sample_limit) for path in graph_paths]
    return {"summary": _combined_summary(books), "books": books}


def audit_scoped_note_resolution(path: Path, *, sample_limit: int = 30) -> dict[str, Any]:
    graph = _read_json(path)
    validate_bookgraph(graph)
    context = _context(graph)
    records = _resolved_records(graph, context)
    high_risk = [record for record in records if record["risk_flags"]]
    ambiguous_groups = _ambiguous_groups(graph, context)
    chapter_stats = _chapter_stats(records)
    return {
        "path": str(path),
        "metadata": _metadata(graph),
        "summary": _book_summary(graph, records, high_risk, ambiguous_groups),
        "chapter_stats": chapter_stats,
        "high_risk_resolved": high_risk[:sample_limit],
        "manual_review_samples": _manual_review_samples(records, high_risk, sample_limit),
        "ambiguous_groups": ambiguous_groups[:sample_limit],
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = ["# Scoped Note Resolution Audit", ""]
    summary = report["summary"]
    lines.extend(
        [
            "## Summary",
            "",
            f"- books: {summary['book_count']}",
            f"- scoped resolved: {summary['scoped_resolved_count']}",
            f"- high risk resolved: {summary['high_risk_resolved_count']}",
            f"- ambiguous groups: {summary['ambiguous_group_count']}",
            "",
        ]
    )
    for book in report["books"]:
        title = book["metadata"].get("title") or book["metadata"].get("doc_id")
        lines.extend(_book_markdown(title, book))
    return "\n".join(lines).rstrip() + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit deterministic scoped note_ref resolution in BookGraph JSON."
    )
    parser.add_argument("graphs", nargs="+", type=Path, help="BookGraph JSON path(s)")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path")
    parser.add_argument("--markdown-output", type=Path, help="Optional Markdown report path")
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=30,
        help="Maximum sample records per book for high-risk/manual/ambiguous sections.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only compact summary to stdout; --output still receives full report.",
    )
    return parser


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


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _metadata(graph: dict[str, Any]) -> dict[str, str]:
    metadata = graph.get("metadata") or {}
    return {
        "doc_id": str(metadata.get("doc_id") or ""),
        "title": str(metadata.get("title") or ""),
        "source_file": str(metadata.get("source_file") or ""),
    }


def _context(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph["nodes"]
    evidence_by_id = {str(record["evidence_id"]): record for record in graph["evidence"]}
    node_by_id = {str(node["node_id"]): node for node in nodes}
    reading_order = [str(node_id) for node_id in graph["projections"].get("reading_order") or []]
    note_index = _note_index(nodes)
    return {
        "node_by_id": node_by_id,
        "evidence_by_id": evidence_by_id,
        "reading_order": reading_order,
        "body_scope_by_node": _body_scope_by_node(reading_order, node_by_id),
        "note_index": note_index,
        "duplicate_note_keys": _duplicate_note_keys(note_index),
    }


def _resolved_records(graph: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    node_by_id = context["node_by_id"]
    for node_id in context["reading_order"]:
        source = node_by_id.get(node_id)
        if not source or source.get("node_type") == "note":
            continue
        for run in source.get("inline_runs") or []:
            if not isinstance(run, dict) or run.get("type") != "note_ref":
                continue
            target_id = _note_ref_target(run)
            if not target_id:
                continue
            target = node_by_id.get(target_id)
            if not _is_scoped_note(target):
                continue
            records.append(_resolved_record(source, run, target, context))
    return records


def _resolved_record(
    source: dict[str, Any],
    run: dict[str, Any],
    target: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    source_id = str(source["node_id"])
    target_id = str(target["node_id"])
    source_scope_key = context["body_scope_by_node"].get(source_id, "")
    target_attrs = _attrs(target)
    marker = _note_ref_marker(run)
    target_marker = str(target_attrs.get("marker") or "")
    target_scope = str(target_attrs.get("scope") or "")
    target_scope_key = str(target_attrs.get("scope_key") or "")
    risk_flags = _risk_flags(
        source,
        target,
        marker=marker,
        target_marker=target_marker,
        source_scope_key=source_scope_key,
        target_scope=target_scope,
        target_scope_key=target_scope_key,
        context=context,
    )
    return {
        "source_node_id": source_id,
        "target_note_id": target_id,
        "marker": marker,
        "target_marker": target_marker,
        "source_pages": _node_pages(source, context["evidence_by_id"]),
        "target_pages": _node_pages(target, context["evidence_by_id"]),
        "source_scope_key": source_scope_key,
        "target_scope": target_scope,
        "target_scope_key": target_scope_key,
        "target_source_placement": str(target_attrs.get("source_placement") or ""),
        "risk_flags": risk_flags,
        "source_text": _snippet(source.get("text")),
        "target_text": _snippet(target.get("text")),
    }


def _risk_flags(
    source: dict[str, Any],
    target: dict[str, Any],
    *,
    marker: str,
    target_marker: str,
    source_scope_key: str,
    target_scope: str,
    target_scope_key: str,
    context: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    if marker != target_marker:
        flags.append("marker_mismatch")
    if _attrs(source).get("note_section_id"):
        flags.append("source_inside_note_section")
    if not _attrs(target).get("note_section_id"):
        flags.append("target_not_in_note_section")
    if target_scope == "chapter" and not target_scope_key:
        flags.append("missing_target_scope_key")
    if target_scope == "chapter" and source_scope_key != target_scope_key:
        flags.append("scope_mismatch")
    target_key = (target_scope, target_scope_key, target_marker)
    if target_key in context["duplicate_note_keys"]:
        flags.append("duplicate_target_marker_in_scope")
    if target_scope == "book" and len(context["note_index"].get(target_key, [])) != 1:
        flags.append("book_scope_not_unique")
    return flags


def _ambiguous_groups(graph: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for key, notes in sorted(context["note_index"].items()):
        if len(notes) <= 1:
            continue
        scope, scope_key, marker = key
        groups.append(
            {
                "scope": scope,
                "scope_key": scope_key,
                "marker": marker,
                "candidate_count": len(notes),
                "candidate_note_ids": [str(note["node_id"]) for note in notes[:10]],
                "candidate_pages": [
                    _node_pages(note, context["evidence_by_id"]) for note in notes[:10]
                ],
            }
        )
    return groups


def _chapter_stats(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        scope_key = record["target_scope_key"] or record["target_scope"] or "unknown"
        grouped[scope_key]["resolved"] += 1
        if record["risk_flags"]:
            grouped[scope_key]["high_risk"] += 1
    return [
        {"scope_key": scope_key, **dict(counts)}
        for scope_key, counts in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _book_summary(
    graph: dict[str, Any],
    records: list[dict[str, Any]],
    high_risk: list[dict[str, Any]],
    ambiguous_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = graph.get("metadata") or {}
    return {
        "scoped_resolved_count": len(records),
        "high_risk_resolved_count": len(high_risk),
        "ambiguous_group_count": len(ambiguous_groups),
        "risk_flag_counts": dict(
            sorted(Counter(flag for record in high_risk for flag in record["risk_flags"]).items())
        ),
        "metadata_scoped_resolution": metadata.get("shadow_scoped_note_ref_resolution") or {},
        "metadata_section_detection": metadata.get("shadow_note_section_detection") or {},
    }


def _combined_summary(books: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "book_count": len(books),
        "scoped_resolved_count": sum(
            book["summary"]["scoped_resolved_count"] for book in books
        ),
        "high_risk_resolved_count": sum(
            book["summary"]["high_risk_resolved_count"] for book in books
        ),
        "ambiguous_group_count": sum(book["summary"]["ambiguous_group_count"] for book in books),
    }


def _manual_review_samples(
    records: list[dict[str, Any]], high_risk: list[dict[str, Any]], sample_limit: int
) -> list[dict[str, Any]]:
    samples = list(high_risk[:sample_limit])
    seen = {(record["source_node_id"], record["target_note_id"]) for record in samples}
    for record in records:
        if len(samples) >= sample_limit:
            break
        key = (record["source_node_id"], record["target_note_id"])
        if key in seen:
            continue
        samples.append(record)
        seen.add(key)
    return samples


def _note_index(nodes: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        if not _is_scoped_note(node):
            continue
        attrs = _attrs(node)
        key = (
            str(attrs.get("scope") or "unknown"),
            str(attrs.get("scope_key") or ""),
            str(attrs.get("marker") or ""),
        )
        index[key].append(node)
    return dict(index)


def _duplicate_note_keys(
    note_index: dict[tuple[str, str, str], list[dict[str, Any]]]
) -> set[tuple[str, str, str]]:
    return {key for key, notes in note_index.items() if len(notes) > 1}


def _body_scope_by_node(
    reading_order: list[str], node_by_id: dict[str, dict[str, Any]]
) -> dict[str, str]:
    scope_by_node: dict[str, str] = {}
    current_scope = ""
    for node_id in reading_order:
        node = node_by_id.get(node_id)
        if not node or _attrs(node).get("note_section_id"):
            continue
        if node.get("node_type") == "heading":
            current_scope = _scope_key(str(node.get("text") or ""))
        if current_scope:
            scope_by_node[node_id] = current_scope
    return scope_by_node


def _is_scoped_note(node: dict[str, Any] | None) -> bool:
    if not node or node.get("node_type") != "note":
        return False
    return str(_attrs(node).get("source_placement") or "") in SCOPED_PLACEMENTS


def _attrs(node: dict[str, Any]) -> dict[str, Any]:
    attrs = node.get("attrs")
    return attrs if isinstance(attrs, dict) else {}


def _note_ref_target(run: dict[str, Any]) -> str:
    attrs = run.get("attrs") if isinstance(run.get("attrs"), dict) else {}
    return str(attrs.get("target_note_id") or run.get("target_note_id") or "")


def _note_ref_marker(run: dict[str, Any]) -> str:
    attrs = run.get("attrs") if isinstance(run.get("attrs"), dict) else {}
    return str(attrs.get("marker") or run.get("marker") or run.get("text") or "").strip()


def _node_pages(node: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> list[int]:
    pages: list[int] = []
    for evidence_id in node.get("evidence_ids") or []:
        evidence = evidence_by_id.get(str(evidence_id))
        if not evidence:
            continue
        for page in evidence.get("pages") or []:
            if isinstance(page, int) and page not in pages:
                pages.append(page)
        page = evidence.get("page")
        if isinstance(page, int) and page not in pages:
            pages.append(page)
    return sorted(pages)


def _scope_key(text: str) -> str:
    return "".join(str(text).split()).lower()


def _snippet(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit]}..."


def _summary_only(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": report["summary"],
        "books": [
            {
                "metadata": book["metadata"],
                "summary": book["summary"],
            }
            for book in report["books"]
        ],
    }


def _book_markdown(title: str, book: dict[str, Any]) -> list[str]:
    summary = book["summary"]
    lines = [
        f"## {title}",
        "",
        f"- scoped resolved: {summary['scoped_resolved_count']}",
        f"- high risk resolved: {summary['high_risk_resolved_count']}",
        f"- ambiguous groups: {summary['ambiguous_group_count']}",
        f"- risk flags: `{json.dumps(summary['risk_flag_counts'], ensure_ascii=False)}`",
        "",
        "### High Risk Samples",
        "",
    ]
    lines.extend(_sample_table(book["high_risk_resolved"]))
    lines.extend(["", "### Manual Review Samples", ""])
    lines.extend(_sample_table(book["manual_review_samples"]))
    lines.append("")
    return lines


def _sample_table(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return ["No records."]
    lines = [
        "| source | target | marker | scope | pages | risk | source text | target text |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records[:30]:
        lines.append(
            "| {source} | {target} | {marker} | {scope} | {pages} | {risk} | {source_text} | {target_text} |".format(
                source=record["source_node_id"],
                target=record["target_note_id"],
                marker=_md(record["marker"]),
                scope=_md(record["target_scope_key"] or record["target_scope"]),
                pages=_md(f"{record['source_pages']} -> {record['target_pages']}"),
                risk=_md(",".join(record["risk_flags"]) or "none"),
                source_text=_md(record["source_text"]),
                target_text=_md(record["target_text"]),
            )
        )
    return lines


def _md(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    sys.exit(main())
