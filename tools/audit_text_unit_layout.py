#!/usr/bin/env python3
"""Audit parser-neutral TextUnit layout classification signals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from inkline.canonical import audit_text_unit_layout, build_text_units, validate_observed_document


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_observed_text_unit_layout(args.observed)
    if args.output:
        _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def audit_observed_text_unit_layout(observed_path: Path) -> dict[str, Any]:
    observed = _read_json(observed_path)
    validate_observed_document(observed)
    units, ignored_counts = build_text_units(observed)
    report = audit_text_unit_layout(units, observed["pages"], observed["observations"])
    report["ignored_observation_counts"] = ignored_counts
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit TextUnit layout classification signals from an ObservedDocument JSON."
    )
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


if __name__ == "__main__":
    sys.exit(main())
