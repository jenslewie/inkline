#!/usr/bin/env python3
"""Compare v1-shadow and ObservedDocument-shadow BookGraph build paths."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from inkline.canonical import validate_bookgraph
from inkline.canonical.observed_bookgraph import build_observed_bookgraph_artifacts
from inkline.parsers.mineru.normalize.bookgraph_shadow import build_bookgraph_shadow


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = compare_shadow_paths(args.canonical, args.observed)
    if args.output:
        _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def compare_shadow_paths(canonical_path: Path, observed_path: Path) -> dict[str, Any]:
    canonical = _read_json(canonical_path)
    observed = _read_json(observed_path)
    v1_graph = build_bookgraph_shadow(canonical)
    observed_artifacts = build_observed_bookgraph_artifacts(observed)
    observed_graph = observed_artifacts["public_graph"]
    validate_bookgraph(v1_graph)
    validate_bookgraph(observed_graph)

    v1_summary = _graph_summary(v1_graph)
    observed_summary = _graph_summary(
        observed_graph, ignored_counts=observed_artifacts["ignored_counts"]
    )
    return {
        "v1_shadow": v1_summary,
        "observed_shadow": observed_summary,
        "node_count_delta": _counter_delta(
            v1_summary["node_counts"], observed_summary["node_counts"]
        ),
        "ignored_counts_delta": _counter_delta(
            v1_summary["ignored_counts"], observed_summary["ignored_counts"]
        ),
        "reading_order_count_delta": (
            observed_summary["reading_order_count"] - v1_summary["reading_order_count"]
        ),
        "display_paragraph_ratio_delta": _ratio_delta(v1_summary, observed_summary),
        "text_snippet_delta": _text_snippet_delta(v1_graph, observed_graph),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare BookGraph outputs from v1 canonical and observed shadow paths."
    )
    parser.add_argument("canonical", type=Path, help="Existing v1 canonical.json")
    parser.add_argument("observed", type=Path, help="ObservedDocument shadow JSON")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path")
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


def _graph_summary(
    graph: dict[str, Any], *, ignored_counts: dict[str, int] | None = None
) -> dict[str, Any]:
    node_counts = dict(sorted(Counter(node["node_type"] for node in graph["nodes"]).items()))
    metadata = graph.get("metadata") or {}
    resolved_ignored_counts = ignored_counts
    if resolved_ignored_counts is None:
        resolved_ignored_counts = metadata.get("shadow_ignored_observation_counts") or metadata.get(
            "shadow_ignored_block_counts"
        ) or {}
    return {
        "node_counts": node_counts,
        "ignored_counts": dict(sorted(resolved_ignored_counts.items())),
        "reading_order_count": len(graph.get("projections", {}).get("reading_order") or []),
        "display_paragraph_ratio": _display_paragraph_ratio(node_counts),
    }


def _counter_delta(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    keys = sorted(set(left) | set(right))
    return {key: int(right.get(key, 0)) - int(left.get(key, 0)) for key in keys}


def _display_paragraph_ratio(node_counts: dict[str, int]) -> float | None:
    paragraph_count = node_counts.get("paragraph", 0)
    if paragraph_count == 0:
        return None
    return round(node_counts.get("display_block", 0) / paragraph_count, 4)


def _ratio_delta(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    left_ratio = left.get("display_paragraph_ratio")
    right_ratio = right.get("display_paragraph_ratio")
    if left_ratio is None or right_ratio is None:
        return None
    return round(float(right_ratio) - float(left_ratio), 4)


def _text_snippet_delta(
    v1_graph: dict[str, Any], observed_graph: dict[str, Any]
) -> dict[str, list[str]]:
    v1_text = Counter(_node_text_snippets(v1_graph))
    observed_text = Counter(_node_text_snippets(observed_graph))
    missing = list((v1_text - observed_text).elements())
    extra = list((observed_text - v1_text).elements())
    return {
        "missing_in_observed": sorted(missing),
        "extra_in_observed": sorted(extra),
    }


def _node_text_snippets(graph: dict[str, Any]) -> list[str]:
    snippets: list[str] = []
    for node in graph["nodes"]:
        text = " ".join(str(node.get("text") or "").split())
        if text:
            snippets.append(text[:80])
    return snippets


if __name__ == "__main__":
    sys.exit(main())
