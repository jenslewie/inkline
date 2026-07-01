#!/usr/bin/env python3
"""Check observed BookGraph against a verified golden canonical."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from inkline.canonical import validate_bookgraph

SUPPORTED_TYPES = {"heading", "paragraph", "display_block", "list_item", "footnote"}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = check_bookgraph_golden_parity(
        args.golden_canonical,
        args.bookgraph,
        min_display_recall=args.min_display_recall,
        max_heading_ratio=args.max_heading_ratio,
    )
    if args.output:
        _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


def check_bookgraph_golden_parity(
    golden_path: Path,
    bookgraph_path: Path,
    *,
    min_display_recall: float = 0.5,
    max_heading_ratio: float = 2.0,
) -> dict[str, Any]:
    golden = _read_json(golden_path)
    graph = _read_json(bookgraph_path)
    validate_bookgraph(graph)
    golden_counts = _golden_counts(golden)
    bookgraph_counts = _bookgraph_counts(graph)
    golden_chars = _golden_text_chars(golden)
    bookgraph_chars = _bookgraph_text_chars(graph)
    errors = _errors(
        golden_counts,
        bookgraph_counts,
        min_display_recall=min_display_recall,
        max_heading_ratio=max_heading_ratio,
    )
    return {
        "status": "pass" if not errors else "fail",
        "metadata": {
            "golden_doc_id": golden.get("metadata", {}).get("doc_id") or "",
            "bookgraph_doc_id": graph.get("metadata", {}).get("doc_id") or "",
        },
        "thresholds": {
            "min_display_recall": min_display_recall,
            "max_heading_ratio": max_heading_ratio,
        },
        "golden_counts": golden_counts,
        "bookgraph_counts": bookgraph_counts,
        "count_deltas": _count_deltas(golden_counts, bookgraph_counts),
        "golden_text_chars": golden_chars,
        "bookgraph_text_chars": bookgraph_chars,
        "text_char_deltas": _count_deltas(golden_chars, bookgraph_chars),
        "ratios": {
            "display_block_recall": _ratio(
                bookgraph_counts.get("display_block", 0),
                golden_counts.get("display_block", 0),
            ),
            "heading_count_ratio": _ratio(
                bookgraph_counts.get("heading", 0),
                golden_counts.get("heading", 0),
            ),
        },
        "errors": errors,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare observed BookGraph type counts with a verified golden canonical."
    )
    parser.add_argument("golden_canonical", type=Path, help="Verified canonical.json")
    parser.add_argument("bookgraph", type=Path, help="Observed BookGraph shadow JSON")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path")
    parser.add_argument("--min-display-recall", type=float, default=0.5)
    parser.add_argument("--max-heading-ratio", type=float, default=2.0)
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


def _golden_counts(canonical: dict[str, Any]) -> dict[str, int]:
    return _sorted_counts(
        block.get("type")
        for block in canonical.get("blocks", [])
        if block.get("type") in SUPPORTED_TYPES
    )


def _bookgraph_counts(graph: dict[str, Any]) -> dict[str, int]:
    return _sorted_counts(node.get("node_type") for node in graph.get("nodes", []))


def _golden_text_chars(canonical: dict[str, Any]) -> dict[str, int]:
    chars: defaultdict[str, int] = defaultdict(int)
    for block in canonical.get("blocks", []):
        block_type = block.get("type")
        if block_type in SUPPORTED_TYPES:
            chars[str(block_type)] += len(str(block.get("text") or ""))
    return dict(sorted(chars.items()))


def _bookgraph_text_chars(graph: dict[str, Any]) -> dict[str, int]:
    chars: defaultdict[str, int] = defaultdict(int)
    for node in graph.get("nodes", []):
        node_type = str(node.get("node_type"))
        chars[node_type] += len(str(node.get("text") or ""))
    return dict(sorted(chars.items()))


def _sorted_counts(values: Any) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _count_deltas(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {
        key: int(right.get(key, 0)) - int(left.get(key, 0))
        for key in sorted(set(left) | set(right))
    }


def _errors(
    golden_counts: dict[str, int],
    bookgraph_counts: dict[str, int],
    *,
    min_display_recall: float,
    max_heading_ratio: float,
) -> list[str]:
    errors: list[str] = []
    display_recall = _ratio(
        bookgraph_counts.get("display_block", 0),
        golden_counts.get("display_block", 0),
    )
    if display_recall is not None and display_recall < min_display_recall:
        errors.append("display_block_recall_below_threshold")
    heading_ratio = _ratio(
        bookgraph_counts.get("heading", 0),
        golden_counts.get("heading", 0),
    )
    if heading_ratio is not None and heading_ratio > max_heading_ratio:
        errors.append("heading_count_above_threshold")
    return errors


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


if __name__ == "__main__":
    sys.exit(main())
