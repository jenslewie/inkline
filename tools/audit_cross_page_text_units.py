#!/usr/bin/env python3
"""Audit geometry signals for cross-page TextUnit aggregation."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

from inkline.canonical import build_text_units


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_cross_page_text_units(args.observed)
    if args.output:
        _write_json(args.output, report)
    printed_report = _summary_report(report) if args.summary_only else report
    print(json.dumps(printed_report, ensure_ascii=False, indent=2))
    return 0


def audit_cross_page_text_units(path: Path) -> dict[str, Any]:
    document = _read_json(path)
    units, ignored_counts = build_text_units(document)
    records = _records(units, _page_heights(document.get("pages") or []))
    return {
        "metadata": {
            "doc_id": document.get("metadata", {}).get("doc_id") or "",
            "title": document.get("metadata", {}).get("title") or "",
            "source_file": document.get("metadata", {}).get("source_file") or "",
        },
        "summary": _summary(units, records, ignored_counts),
        "records": records,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit parser-neutral geometry signals behind cross-page TextUnit merges."
    )
    parser.add_argument("observed", type=Path, help="ObservedDocument shadow JSON path")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only metadata and summary to stdout; --output still receives full records.",
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


def _summary_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "metadata": report["metadata"],
        "summary": report["summary"],
    }


def _records(units: list[dict[str, Any]], page_heights: dict[int, float]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for unit in units:
        attrs = unit.get("attrs") if isinstance(unit.get("attrs"), dict) else {}
        merge_reasons = (
            attrs.get("merge_reasons") if isinstance(attrs.get("merge_reasons"), list) else []
        )
        if "cross_page_boundary_continuation" not in merge_reasons:
            continue
        spans = _valid_spans(unit.get("spans") or [])
        records.extend(_transition_records(unit, spans, page_heights))
    return records


def _transition_records(
    unit: dict[str, Any],
    spans: list[dict[str, Any]],
    page_heights: dict[int, float],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for previous, current in pairwise(spans):
        previous_page = int(previous["page"])
        current_page = int(current["page"])
        if previous_page == current_page:
            continue
        previous_bbox = previous["bbox"]
        current_bbox = current["bbox"]
        previous_height = page_heights.get(previous_page)
        current_height = page_heights.get(current_page)
        records.append(
            {
                "unit_id": unit["unit_id"],
                "from_page": previous_page,
                "to_page": current_page,
                "previous_bbox": previous_bbox,
                "next_bbox": current_bbox,
                "previous_bottom_ratio": _ratio(previous_bbox[3], previous_height),
                "next_top_ratio": _ratio(current_bbox[1], current_height),
                "left_delta": round(abs(float(previous_bbox[0]) - float(current_bbox[0])), 4),
                "horizontal_overlap_ratio": _horizontal_overlap_ratio(previous_bbox, current_bbox),
                "observation_ids": list(unit.get("observation_ids") or []),
                "unit_pages": list(unit.get("pages") or []),
                "span_count": len(spans),
            }
        )
    return records


def _valid_spans(spans: list[Any]) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        page = span.get("page")
        bbox = span.get("bbox")
        if isinstance(page, int) and _valid_bbox(bbox):
            valid.append({"page": page, "bbox": [float(value) for value in bbox]})
    return valid


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )


def _page_heights(pages: list[Any]) -> dict[int, float]:
    heights: dict[int, float] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_number = page.get("page")
        height = page.get("height")
        if isinstance(page_number, int) and isinstance(height, int | float):
            heights[page_number] = float(height)
    return heights


def _ratio(value: float, total: float | None) -> float | None:
    if total is None or total <= 0:
        return None
    return round(float(value) / total, 4)


def _horizontal_overlap_ratio(left: list[float], right: list[float]) -> float:
    overlap = max(0.0, min(float(left[2]), float(right[2])) - max(float(left[0]), float(right[0])))
    width = min(float(left[2]) - float(left[0]), float(right[2]) - float(right[0]))
    if width <= 0:
        return 0.0
    return round(overlap / width, 4)


def _summary(
    units: list[dict[str, Any]],
    records: list[dict[str, Any]],
    ignored_counts: dict[str, int],
) -> dict[str, Any]:
    cross_page_units = [
        unit
        for unit in units
        if "cross_page_boundary_continuation" in (unit.get("attrs", {}).get("merge_reasons") or [])
    ]
    transition_pages = sorted({f"{record['from_page']}->{record['to_page']}" for record in records})
    return {
        "unit_count": len(units),
        "cross_page_unit_count": len(cross_page_units),
        "cross_page_transition_count": len(records),
        "max_transitions_per_unit": _max_transitions_per_unit(records),
        "ignored_observation_counts": dict(sorted(ignored_counts.items())),
        "transition_page_count": len(transition_pages),
        "transition_page_sample": transition_pages[:20],
    }


def _max_transitions_per_unit(records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    counts = Counter(record["unit_id"] for record in records)
    return max(counts.values())


if __name__ == "__main__":
    sys.exit(main())
