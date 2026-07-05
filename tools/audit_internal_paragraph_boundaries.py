#!/usr/bin/env python3
"""Audit paragraph node boundary signals in internal canonical artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

from inkline.canonical import validate_internal_canonical

MAX_SAMPLES = 20
ALLOWED_MULTI_OBSERVATION_REASONS = {
    "cross_page_boundary_continuation",
    "cross_nontext_page_boundary_continuation",
    "same_page_short_line_group",
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_internal_paragraph_boundaries(args.internal_canonical)
    if args.output:
        _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def audit_internal_paragraph_boundaries(path: Path) -> dict[str, Any]:
    internal = _read_json(path)
    validate_internal_canonical(internal)
    node_records = internal["nodes"]
    evidence_by_id = {
        record["public"]["evidence_id"]: record["public"] for record in internal["evidence"]
    }
    page_sizes = _page_sizes(internal)
    page_roles = _page_roles(internal)
    paragraphs = [record for record in node_records if record["public"]["node_type"] == "paragraph"]
    multi_observation = _multi_observation_records(paragraphs)
    same_page_geometry_leaks = [
        record
        for record in multi_observation
        if "same_page_geometry_continuation" in _merge_reasons(record)
    ]
    unexplained_multi_observation = [
        record
        for record in multi_observation
        if not (set(_merge_reasons(record)) & ALLOWED_MULTI_OBSERVATION_REASONS)
    ]
    nonconsecutive_candidates = _nonconsecutive_page_candidates(
        node_records, evidence_by_id, page_sizes, page_roles
    )
    split_groups = _split_text_unit_groups(paragraphs)
    return {
        "path": str(path),
        "summary": {
            "paragraph_nodes": len(paragraphs),
            "multi_observation_paragraphs": len(multi_observation),
            "same_page_geometry_leaks": len(same_page_geometry_leaks),
            "unexplained_multi_observation_paragraphs": len(unexplained_multi_observation),
            "split_text_unit_groups": len(split_groups),
            "nonconsecutive_page_continuation_candidates": len(nonconsecutive_candidates),
        },
        "merge_reason_counts": dict(
            sorted(
                Counter(
                    reason for record in multi_observation for reason in _merge_reasons(record)
                ).items()
            )
        ),
        "samples": {
            "same_page_geometry_leaks": _node_samples(same_page_geometry_leaks),
            "unexplained_multi_observation_paragraphs": _node_samples(
                unexplained_multi_observation
            ),
            "split_text_unit_groups": split_groups[:MAX_SAMPLES],
            "nonconsecutive_page_continuation_candidates": nonconsecutive_candidates[:MAX_SAMPLES],
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit logical paragraph boundaries using internal canonical debug data."
    )
    parser.add_argument("internal_canonical", type=Path)
    parser.add_argument("--output", type=Path)
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


def _multi_observation_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if len(_debug_attrs(record).get("source_observation_ids") or []) > 1
    ]


def _merge_reasons(record: dict[str, Any]) -> list[str]:
    reasons = _debug_attrs(record).get("merge_reasons")
    return list(reasons) if isinstance(reasons, list) else []


def _debug_attrs(record: dict[str, Any]) -> dict[str, Any]:
    debug = record.get("debug") if isinstance(record.get("debug"), dict) else {}
    attrs = debug.get("attrs") if isinstance(debug.get("attrs"), dict) else {}
    return attrs


def _node_samples(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_node_sample(record) for record in records[:MAX_SAMPLES]]


def _node_sample(record: dict[str, Any]) -> dict[str, Any]:
    public = record["public"]
    attrs = _debug_attrs(record)
    return {
        "node_id": public["node_id"],
        "text_snippet": str(public.get("text") or "")[:120],
        "source_text_unit_id": attrs.get("source_text_unit_id"),
        "source_logical_unit_id": attrs.get("source_logical_unit_id"),
        "source_observation_ids": list(attrs.get("source_observation_ids") or []),
        "merge_reasons": _merge_reasons(record),
    }


def _split_text_unit_groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        source_text_unit_id = _debug_attrs(record).get("source_text_unit_id")
        if isinstance(source_text_unit_id, str):
            grouped[source_text_unit_id].append(record)
    groups = []
    for source_text_unit_id, group in sorted(grouped.items()):
        if len(group) <= 1:
            continue
        groups.append(
            {
                "source_text_unit_id": source_text_unit_id,
                "node_ids": [record["public"]["node_id"] for record in group],
                "node_count": len(group),
                "text_snippets": [
                    str(record["public"].get("text") or "")[:80] for record in group[:5]
                ],
            }
        )
    return groups


def _nonconsecutive_page_candidates(
    records: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    page_sizes: dict[int, dict[str, float]],
    page_roles: dict[int, str],
) -> list[dict[str, Any]]:
    candidates = []
    for previous, current in pairwise(records):
        if (
            previous["public"].get("node_type") != "paragraph"
            or current["public"].get("node_type") != "paragraph"
        ):
            continue
        previous_span = _last_span(previous, evidence_by_id)
        current_span = _first_span(current, evidence_by_id)
        if previous_span is None or current_span is None:
            continue
        previous_page = int(previous_span["page"])
        current_page = int(current_span["page"])
        if current_page <= previous_page + 1:
            continue
        if (
            page_roles.get(previous_page) != "text_flow_page"
            or page_roles.get(current_page) != "text_flow_page"
        ):
            continue
        if not _near_page_bottom(previous_span, page_sizes):
            continue
        if not _near_page_top(current_span, page_sizes):
            continue
        candidates.append(
            {
                "previous_node_id": previous["public"]["node_id"],
                "current_node_id": current["public"]["node_id"],
                "page_gap": current_page - previous_page,
                "previous_page": previous_page,
                "current_page": current_page,
                "previous_page_role": page_roles.get(previous_page),
                "current_page_role": page_roles.get(current_page),
                "bridge_page_roles": {
                    str(page): page_roles.get(page)
                    for page in range(previous_page + 1, current_page)
                },
                "previous_text_snippet": str(previous["public"].get("text") or "")[-120:],
                "current_text_snippet": str(current["public"].get("text") or "")[:120],
            }
        )
    return candidates


def _first_span(
    record: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    spans = _node_spans(record, evidence_by_id)
    return spans[0] if spans else None


def _last_span(
    record: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    spans = _node_spans(record, evidence_by_id)
    return spans[-1] if spans else None


def _node_spans(
    record: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    spans = []
    for evidence_id in record["public"].get("evidence_ids") or []:
        evidence = evidence_by_id.get(evidence_id)
        if not evidence:
            continue
        for span in evidence.get("spans") or []:
            if _valid_span(span):
                spans.append(span)
    return spans


def _valid_span(span: Any) -> bool:
    bbox = span.get("bbox") if isinstance(span, dict) else None
    return (
        isinstance(span, dict)
        and isinstance(span.get("page"), int)
        and isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(value, int | float) for value in bbox)
    )


def _near_page_bottom(span: dict[str, Any], page_sizes: dict[int, dict[str, float]]) -> bool:
    page = int(span["page"])
    height = page_sizes.get(page, {}).get("height")
    return bool(height) and float(span["bbox"][3]) >= float(height) * 0.86


def _near_page_top(span: dict[str, Any], page_sizes: dict[int, dict[str, float]]) -> bool:
    page = int(span["page"])
    height = page_sizes.get(page, {}).get("height")
    return bool(height) and float(span["bbox"][1]) <= float(height) * 0.16


def _page_sizes(internal: dict[str, Any]) -> dict[int, dict[str, float]]:
    pages = internal.get("pipeline", {}).get("observed_document", {}).get("pages") or []
    return {
        int(page["page"]): {"width": float(page["width"]), "height": float(page["height"])}
        for page in pages
        if isinstance(page, dict)
        and isinstance(page.get("page"), int)
        and isinstance(page.get("width"), int | float)
        and isinstance(page.get("height"), int | float)
    }


def _page_roles(internal: dict[str, Any]) -> dict[int, str]:
    records = internal.get("pipeline", {}).get("page_roles") or []
    return {
        int(record["page"]): str(record["page_role"])
        for record in records
        if isinstance(record, dict)
        and isinstance(record.get("page"), int)
        and isinstance(record.get("page_role"), str)
    }


if __name__ == "__main__":
    raise SystemExit(main())
