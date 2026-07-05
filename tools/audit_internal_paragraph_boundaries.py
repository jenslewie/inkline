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
    observations_by_id = _observations_by_id(internal)
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
        node_records, evidence_by_id, observations_by_id, page_sizes, page_roles
    )
    suspicious_cross_page_merges = _suspicious_cross_page_new_paragraph_merges(
        paragraphs, observations_by_id
    )
    adjacent_page_split_candidates = _adjacent_page_split_candidates(
        node_records, evidence_by_id, observations_by_id, page_sizes, page_roles
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
            "suspicious_cross_page_new_paragraph_merges": len(suspicious_cross_page_merges),
            "adjacent_page_split_continuation_candidates": len(adjacent_page_split_candidates),
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
            "suspicious_cross_page_new_paragraph_merges": suspicious_cross_page_merges[
                :MAX_SAMPLES
            ],
            "adjacent_page_split_continuation_candidates": adjacent_page_split_candidates[
                :MAX_SAMPLES
            ],
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


def _suspicious_cross_page_new_paragraph_merges(
    records: list[dict[str, Any]],
    observations_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for record in records:
        observation_ids = list(_debug_attrs(record).get("source_observation_ids") or [])
        merge_reasons = _merge_reasons(record)
        for index, observation_id in enumerate(observation_ids[1:], start=1):
            reason = merge_reasons[index - 1] if index - 1 < len(merge_reasons) else ""
            if not reason.startswith("cross_"):
                continue
            observation = observations_by_id.get(str(observation_id))
            if not observation or not _observation_starts_new_paragraph(observation):
                continue
            previous_observation = observations_by_id.get(str(observation_ids[index - 1]))
            findings.append(
                {
                    "node_id": record["public"]["node_id"],
                    "source_text_unit_id": _debug_attrs(record).get("source_text_unit_id"),
                    "merge_reason": reason,
                    "previous_observation_id": observation_ids[index - 1],
                    "current_observation_id": observation_id,
                    "previous_page": previous_observation.get("page")
                    if previous_observation
                    else None,
                    "current_page": observation.get("page"),
                    "current_text_line_metrics": _observation_text_line_metrics(observation),
                    "previous_text_snippet": str(previous_observation.get("text") or "")[-120:]
                    if previous_observation
                    else "",
                    "current_text_snippet": str(observation.get("text") or "")[:120],
                }
            )
    return findings


def _adjacent_page_split_candidates(
    records: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    observations_by_id: dict[str, dict[str, Any]],
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
        if current_page != previous_page + 1:
            continue
        if not (
            _text_flow_like_page(page_roles.get(previous_page))
            and _text_flow_like_page(page_roles.get(current_page))
        ):
            continue
        if not _near_page_bottom(previous_span, page_sizes) or not _near_page_top(
            current_span, page_sizes
        ):
            continue
        if _horizontal_overlap_ratio(previous_span["bbox"], current_span["bbox"]) < 0.6:
            continue
        current_observation = _first_observation(current, observations_by_id)
        if not current_observation or not _observation_starts_continuation(current_observation):
            continue
        candidates.append(
            {
                "previous_node_id": previous["public"]["node_id"],
                "current_node_id": current["public"]["node_id"],
                "previous_page": previous_page,
                "current_page": current_page,
                "current_observation_id": current_observation["observation_id"],
                "current_text_line_metrics": _observation_text_line_metrics(current_observation),
                "previous_text_snippet": str(previous["public"].get("text") or "")[-120:],
                "current_text_snippet": str(current["public"].get("text") or "")[:120],
            }
        )
    return candidates


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
    observations_by_id: dict[str, dict[str, Any]],
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
        if not (
            _text_flow_like_page(page_roles.get(previous_page))
            and _text_flow_like_page(page_roles.get(current_page))
        ):
            continue
        if not _near_page_bottom(previous_span, page_sizes):
            continue
        if not _near_page_top(current_span, page_sizes):
            continue
        current_observation = _first_observation(current, observations_by_id)
        if current_observation and _observation_starts_new_paragraph(current_observation):
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


def _first_observation(
    record: dict[str, Any], observations_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    observation_ids = list(_debug_attrs(record).get("source_observation_ids") or [])
    if not observation_ids:
        return None
    return observations_by_id.get(str(observation_ids[0]))


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


def _text_flow_like_page(page_role: str | None) -> bool:
    return page_role in {"text_flow_page", "text_flow_candidate"}


def _observations_by_id(internal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    observations = (
        internal.get("pipeline", {}).get("observed_document", {}).get("observations") or []
    )
    return {
        str(observation["observation_id"]): observation
        for observation in observations
        if isinstance(observation, dict) and isinstance(observation.get("observation_id"), str)
    }


def _observation_starts_new_paragraph(observation: dict[str, Any]) -> bool:
    metrics = _observation_text_line_metrics(observation)
    if not metrics:
        return False
    line_count = _metric_int(metrics, "line_count")
    if line_count is not None and line_count < 2:
        return False
    indent = _metric_float(metrics, "first_line_indent")
    char_width = _metric_float(metrics, "char_width")
    if indent is None:
        return False
    return indent >= max(8.0, (char_width or 10.0) * 1.15)


def _observation_starts_continuation(observation: dict[str, Any]) -> bool:
    metrics = _observation_text_line_metrics(observation)
    if not metrics:
        return False
    line_count = _metric_int(metrics, "line_count")
    if line_count is not None and line_count < 2:
        return False
    indent = _metric_float(metrics, "first_line_indent")
    char_width = _metric_float(metrics, "char_width")
    if indent is None:
        return False
    return abs(indent) <= max(6.0, (char_width or 10.0) * 0.75)


def _observation_text_line_metrics(observation: dict[str, Any]) -> dict[str, Any] | None:
    attrs = observation.get("attrs") if isinstance(observation.get("attrs"), dict) else {}
    metrics = attrs.get("text_line_metrics")
    return metrics if isinstance(metrics, dict) else None


def _metric_float(metrics: dict[str, Any], key: str) -> float | None:
    try:
        return float(metrics[key])
    except (KeyError, TypeError, ValueError):
        return None


def _metric_int(metrics: dict[str, Any], key: str) -> int | None:
    try:
        return int(metrics[key])
    except (KeyError, TypeError, ValueError):
        return None


def _horizontal_overlap_ratio(left: list[float], right: list[float]) -> float:
    overlap = max(0.0, min(float(left[2]), float(right[2])) - max(float(left[0]), float(right[0])))
    width = min(float(left[2]) - float(left[0]), float(right[2]) - float(right[0]))
    if width <= 0:
        return 0.0
    return overlap / width


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
