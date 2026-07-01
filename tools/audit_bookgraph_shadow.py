#!/usr/bin/env python3
"""Build and audit a BookGraph shadow artifact from a legacy canonical JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from inkline.canonical import audit_bookgraph, validate_bookgraph
from inkline.parsers.mineru.normalize.bookgraph_shadow import build_bookgraph_shadow


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    canonical = _read_json(args.canonical)
    graph = build_bookgraph_shadow(canonical)
    validate_bookgraph(graph)

    audit = audit_bookgraph(
        graph, legacy_canonical=None if args.no_projection_diff else canonical
    )
    if args.bookgraph_output:
        _write_json(args.bookgraph_output, graph)
    if args.audit_output:
        _write_json(args.audit_output, audit)

    summary = _summary(audit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return _exit_code(args, audit)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build canonical_v2 BookGraph from an existing canonical.json and "
            "emit a compact audit summary."
        )
    )
    parser.add_argument("canonical", type=Path, help="Existing v1 canonical.json")
    parser.add_argument(
        "--bookgraph-output",
        type=Path,
        help="Optional path for the generated canonical_v2.json shadow artifact",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        help="Optional path for the full BookGraph audit JSON",
    )
    parser.add_argument(
        "--no-projection-diff",
        action="store_true",
        help="Skip BookGraph -> v1-like block projection comparison",
    )
    parser.add_argument(
        "--fail-on-structure-warnings",
        action="store_true",
        help="Exit 1 when audit structure_warnings is non-empty",
    )
    parser.add_argument(
        "--max-body-like-display-blocks",
        type=int,
        help="Exit 1 when body_like_display_blocks exceeds this count",
    )
    parser.add_argument(
        "--max-heading-like-display-blocks",
        type=int,
        help="Exit 1 when heading_like_display_blocks exceeds this count",
    )
    parser.add_argument(
        "--expect-exact-projection",
        action="store_true",
        help="Exit 1 unless supported text blocks round-trip exactly",
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


def _summary(audit: dict[str, Any]) -> dict[str, Any]:
    projection_diff = audit.get("projection_diff") or {}
    return {
        "metadata": audit.get("metadata", {}),
        "node_counts": audit.get("node_counts", {}),
        "ignored_block_counts": audit.get("ignored_block_counts", {}),
        "display_block_count": audit.get("display_blocks", {}).get("count", 0),
        "heading_like_display_blocks": len(audit.get("heading_like_display_blocks", [])),
        "body_like_display_blocks": len(audit.get("body_like_display_blocks", [])),
        "structure_warnings": audit.get("structure_warnings", []),
        "exact_projection": projection_diff.get("exact_supported_fields_match"),
    }


def _exit_code(args: argparse.Namespace, audit: dict[str, Any]) -> int:
    failed = False
    if args.fail_on_structure_warnings and audit.get("structure_warnings"):
        failed = True
    if args.max_body_like_display_blocks is not None:
        failed = failed or (
            len(audit.get("body_like_display_blocks", []))
            > args.max_body_like_display_blocks
        )
    if args.max_heading_like_display_blocks is not None:
        failed = failed or (
            len(audit.get("heading_like_display_blocks", []))
            > args.max_heading_like_display_blocks
        )
    if args.expect_exact_projection:
        projection_diff = audit.get("projection_diff") or {}
        failed = failed or not projection_diff.get("exact_supported_fields_match")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
