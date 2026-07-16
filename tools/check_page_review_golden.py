#!/usr/bin/env python3
"""Check a PageReview artifact against a verified golden PageReview."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_STABLE_PAGE_FIELDS = (
    "page_role",
    "book_block_position",
    "special_page_kind",
    "text_flow_action",
    "visual_asset_action",
)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = check_page_review_golden(args.golden_page_review, args.page_review)
    if args.output:
        _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


def check_page_review_golden(golden_path: Path, page_review_path: Path) -> dict[str, Any]:
    """Compare the stable page-consumption contract for every golden page."""

    golden = _read_json(golden_path)
    observed = _read_json(page_review_path)
    errors: list[dict[str, Any]] = []
    golden_doc_id = _doc_id(golden)
    observed_doc_id = _doc_id(observed)
    if golden_doc_id != observed_doc_id:
        errors.append(
            {
                "kind": "doc_id_mismatch",
                "golden": golden_doc_id,
                "observed": observed_doc_id,
            }
        )
    golden_pages = _pages_by_number(golden, golden_path)
    observed_pages = _pages_by_number(observed, page_review_path)
    for page, golden_record in sorted(golden_pages.items()):
        observed_record = observed_pages.get(page)
        if observed_record is None:
            errors.append({"kind": "missing_page", "page": page})
            continue
        for field in _STABLE_PAGE_FIELDS:
            if observed_record.get(field) != golden_record.get(field):
                errors.append(
                    {
                        "kind": "field_mismatch",
                        "page": page,
                        "field": field,
                        "golden": golden_record.get(field),
                        "observed": observed_record.get(field),
                    }
                )
    for page in sorted(set(observed_pages) - set(golden_pages)):
        errors.append({"kind": "unexpected_page", "page": page})
    return {
        "status": "pass" if not errors else "fail",
        "golden_page_review": str(golden_path),
        "page_review": str(page_review_path),
        "golden_doc_id": golden_doc_id,
        "page_review_doc_id": observed_doc_id,
        "golden_page_count": len(golden_pages),
        "errors": errors,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("golden_page_review", type=Path)
    parser.add_argument("page_review", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _doc_id(page_review: dict[str, Any]) -> str:
    metadata = page_review.get("metadata")
    return str(metadata.get("doc_id") or "") if isinstance(metadata, dict) else ""


def _pages_by_number(page_review: dict[str, Any], path: Path) -> dict[int, dict[str, Any]]:
    pages = page_review.get("pages")
    if not isinstance(pages, list):
        raise ValueError(f"page_review.pages must be a list: {path}")
    result: dict[int, dict[str, Any]] = {}
    for index, record in enumerate(pages):
        if not isinstance(record, dict) or not isinstance(record.get("page"), int):
            raise ValueError(f"page_review.pages[{index}] must contain an integer page: {path}")
        page = int(record["page"])
        if page in result:
            raise ValueError(f"duplicate page {page}: {path}")
        result[page] = record
    return result


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    sys.exit(main())
