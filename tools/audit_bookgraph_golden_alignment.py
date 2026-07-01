#!/usr/bin/env python3
"""Audit concrete content alignment between a verified canonical and BookGraph."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from inkline.canonical import validate_bookgraph

DEFAULT_TARGET_TYPES = ("display_block", "heading")
SUPPORTED_TYPES = {"heading", "paragraph", "display_block", "list_item", "footnote"}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_bookgraph_golden_alignment(
        args.golden_canonical,
        args.bookgraph,
        target_types=tuple(args.target_type or DEFAULT_TARGET_TYPES),
    )
    if args.output:
        _write_json(args.output, report)
    stdout_report = _summary_report(report) if args.summary_only else report
    print(json.dumps(stdout_report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


def audit_bookgraph_golden_alignment(
    golden_path: Path,
    bookgraph_path: Path,
    *,
    target_types: tuple[str, ...] = DEFAULT_TARGET_TYPES,
) -> dict[str, Any]:
    golden = _read_json(golden_path)
    graph = _read_json(bookgraph_path)
    validate_bookgraph(graph)
    golden_records = _golden_records(golden)
    observed_records = _observed_records(graph)
    pairs = _align_records(golden_records, observed_records)
    report = _report(golden, graph, golden_records, observed_records, pairs, target_types)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Align verified canonical blocks with observed BookGraph nodes and report "
            "matched, false-positive, false-negative, and type-mismatch records."
        )
    )
    parser.add_argument("golden_canonical", type=Path, help="Verified canonical.json")
    parser.add_argument("bookgraph", type=Path, help="Observed BookGraph shadow JSON")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path")
    parser.add_argument(
        "--target-type",
        action="append",
        choices=sorted(SUPPORTED_TYPES),
        help="Type to audit. May be passed more than once. Defaults to display_block and heading.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only status, metadata, and summary to stdout. --output still receives full detail.",
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


def _golden_records(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, block in enumerate(canonical.get("blocks", []), start=1):
        block_type = block.get("type")
        text = str(block.get("text") or "")
        if block_type not in SUPPORTED_TYPES or not _normalized_text(text):
            continue
        source = block.get("source") if isinstance(block.get("source"), dict) else {}
        records.append(
            {
                "side": "golden",
                "record_id": str(block.get("block_id") or f"golden:{index}"),
                "record_type": str(block_type),
                "reading_order": index,
                "text": text,
                "text_preview": _preview(text),
                "normalized_text": _normalized_text(text),
                "page": source.get("page"),
                "pages": list(
                    source.get("pages") or ([source["page"]] if "page" in source else [])
                ),
                "bbox": source.get("bbox"),
                "spans": source.get("spans") or [],
                "attrs": block.get("attrs") if isinstance(block.get("attrs"), dict) else {},
            }
        )
    return records


def _observed_records(graph: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_by_id = {
        evidence["evidence_id"]: evidence
        for evidence in graph.get("evidence", [])
        if isinstance(evidence, dict) and isinstance(evidence.get("evidence_id"), str)
    }
    reading_order = {
        node_id: index
        for index, node_id in enumerate(
            graph.get("projections", {}).get("reading_order", []), start=1
        )
        if isinstance(node_id, str)
    }
    records: list[dict[str, Any]] = []
    for index, node in enumerate(graph.get("nodes", []), start=1):
        node_type = node.get("node_type")
        text = str(node.get("text") or "")
        if node_type not in SUPPORTED_TYPES or not _normalized_text(text):
            continue
        evidence = _first_evidence(node, evidence_by_id)
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        records.append(
            {
                "side": "observed",
                "record_id": str(node.get("node_id") or f"observed:{index}"),
                "record_type": str(node_type),
                "reading_order": reading_order.get(node.get("node_id"), index),
                "text": text,
                "text_preview": _preview(text),
                "normalized_text": _normalized_text(text),
                "page": evidence.get("page"),
                "pages": list(evidence.get("pages") or []),
                "bbox": evidence.get("bbox"),
                "spans": evidence.get("spans") or [],
                "attrs": attrs,
            }
        )
    return records


def _first_evidence(
    node: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    for evidence_id in node.get("evidence_ids", []):
        if isinstance(evidence_id, str) and evidence_id in evidence_by_id:
            return evidence_by_id[evidence_id]
    return {}


def _align_records(
    golden_records: list[dict[str, Any]], observed_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    observed_by_text: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for observed in observed_records:
        observed_by_text[observed["normalized_text"]].append(observed)
    used_observed: set[str] = set()
    pairs: list[dict[str, Any]] = []
    for golden in golden_records:
        candidates = [
            observed
            for observed in observed_by_text.get(golden["normalized_text"], [])
            if observed["record_id"] not in used_observed
        ]
        if not candidates:
            continue
        observed = _best_observed_candidate(golden, candidates)
        used_observed.add(observed["record_id"])
        pairs.append(
            {
                "alignment": "exact_normalized_text",
                "golden": _public_record(golden),
                "observed": _public_record(observed),
            }
        )
    return pairs


def _best_observed_candidate(
    golden: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    return sorted(
        candidates,
        key=lambda observed: (
            observed["record_type"] != golden["record_type"],
            _page_distance(golden, observed),
            observed["reading_order"],
        ),
    )[0]


def _report(
    golden: dict[str, Any],
    graph: dict[str, Any],
    golden_records: list[dict[str, Any]],
    observed_records: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    target_types: tuple[str, ...],
) -> dict[str, Any]:
    matched: dict[str, list[dict[str, Any]]] = {target: [] for target in target_types}
    false_negatives: dict[str, list[dict[str, Any]]] = {target: [] for target in target_types}
    false_positives: dict[str, list[dict[str, Any]]] = {target: [] for target in target_types}
    type_mismatches: dict[str, list[dict[str, Any]]] = {target: [] for target in target_types}
    pair_by_golden = {pair["golden"]["record_id"]: pair for pair in pairs}
    pair_by_observed = {pair["observed"]["record_id"]: pair for pair in pairs}

    for target in target_types:
        for pair in pairs:
            golden_type = pair["golden"]["record_type"]
            observed_type = pair["observed"]["record_type"]
            if golden_type == target and observed_type == target:
                matched[target].append(pair)
            elif target in {golden_type, observed_type} and golden_type != observed_type:
                type_mismatches[target].append(pair)
        for golden_record in _records_of_type(golden_records, target):
            pair = pair_by_golden.get(golden_record["record_id"])
            if pair is None or pair["observed"]["record_type"] != target:
                false_negatives[target].append(
                    _miss_record(
                        "unmatched" if pair is None else "type_mismatch",
                        golden=_public_record(golden_record),
                        observed=pair["observed"] if pair else None,
                        observed_candidates=(
                            _similar_candidates(golden_record, observed_records)
                            if pair is None
                            else []
                        ),
                    )
                )
        for observed_record in _records_of_type(observed_records, target):
            pair = pair_by_observed.get(observed_record["record_id"])
            if pair is None or pair["golden"]["record_type"] != target:
                false_positives[target].append(
                    _miss_record(
                        "unmatched" if pair is None else "type_mismatch",
                        golden=pair["golden"] if pair else None,
                        observed=_public_record(observed_record),
                        golden_candidates=(
                            _similar_candidates(observed_record, golden_records)
                            if pair is None
                            else []
                        ),
                    )
                )

    summary = {
        target: {
            "golden_count": len(_records_of_type(golden_records, target)),
            "observed_count": len(_records_of_type(observed_records, target)),
            "net_count_delta": len(_records_of_type(observed_records, target))
            - len(_records_of_type(golden_records, target)),
            "matched": len(matched[target]),
            "false_negative": len(false_negatives[target]),
            "false_positive": len(false_positives[target]),
            "type_mismatch": len(type_mismatches[target]),
        }
        for target in target_types
    }
    has_errors = any(
        summary[target]["false_negative"]
        or summary[target]["false_positive"]
        or summary[target]["type_mismatch"]
        for target in target_types
    )
    return {
        "status": "fail" if has_errors else "pass",
        "metadata": {
            "golden_doc_id": golden.get("metadata", {}).get("doc_id") or "",
            "bookgraph_doc_id": graph.get("metadata", {}).get("doc_id") or "",
            "alignment_method": "exact_normalized_text",
            "target_types": list(target_types),
        },
        "summary": summary,
        "matched": matched,
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "type_mismatches": type_mismatches,
        "unmatched": {
            "golden": _unmatched_records(golden_records, pair_by_golden, target_types),
            "observed": _unmatched_records(observed_records, pair_by_observed, target_types),
        },
    }


def _records_of_type(records: list[dict[str, Any]], record_type: str) -> list[dict[str, Any]]:
    return [record for record in records if record["record_type"] == record_type]


def _miss_record(
    reason: str,
    *,
    golden: dict[str, Any] | None,
    observed: dict[str, Any] | None,
    observed_candidates: list[dict[str, Any]] | None = None,
    golden_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    record = {"reason": reason, "golden": golden, "observed": observed}
    if observed_candidates is not None:
        record["observed_candidates"] = observed_candidates
    if golden_candidates is not None:
        record["golden_candidates"] = golden_candidates
    return record


def _unmatched_records(
    records: list[dict[str, Any]],
    pair_by_id: dict[str, dict[str, Any]],
    target_types: tuple[str, ...],
) -> list[dict[str, Any]]:
    return [
        _public_record(record)
        for record in records
        if record["record_type"] in target_types and record["record_id"] not in pair_by_id
    ]


def _summary_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": report["status"],
        "metadata": report["metadata"],
        "summary": report["summary"],
    }


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    attrs = record.get("attrs") if isinstance(record.get("attrs"), dict) else {}
    layout_classification = attrs.get("layout_classification")
    return {
        "record_id": record["record_id"],
        "record_type": record["record_type"],
        "reading_order": record["reading_order"],
        "text_preview": record["text_preview"],
        "page": record.get("page"),
        "pages": record.get("pages") or [],
        "bbox": record.get("bbox"),
        "spans": record.get("spans") or [],
        "layout_role": attrs.get("layout_role"),
        "layout_form": attrs.get("layout_form"),
        "alignment": attrs.get("alignment"),
        "layout_signals": (
            layout_classification.get("signals")
            if isinstance(layout_classification, dict)
            else None
        ),
    }


def _similar_candidates(
    record: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    limit: int = 5,
    min_similarity: float = 0.35,
) -> list[dict[str, Any]]:
    scored = []
    for candidate in candidates:
        similarity = _text_similarity(record["normalized_text"], candidate["normalized_text"])
        if similarity < min_similarity:
            continue
        scored.append(
            {
                "text_similarity": round(similarity, 4),
                "page_overlap": _page_overlap(record, candidate),
                "record": _public_record(candidate),
            }
        )
    return sorted(
        scored,
        key=lambda item: (
            not item["page_overlap"],
            -item["text_similarity"],
            item["record"]["reading_order"],
        ),
    )[:limit]


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left in right:
        return len(left) / len(right)
    if right in left:
        return len(right) / len(left)
    return SequenceMatcher(None, left, right).ratio()


def _page_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_pages = {page for page in left.get("pages", []) if isinstance(page, int)}
    right_pages = {page for page in right.get("pages", []) if isinstance(page, int)}
    if left_pages and right_pages:
        return bool(left_pages & right_pages)
    return left.get("page") == right.get("page")


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _preview(value: str, limit: int = 120) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    return collapsed[:limit]


def _page_distance(left: dict[str, Any], right: dict[str, Any]) -> int:
    left_page = left.get("page")
    right_page = right.get("page")
    if isinstance(left_page, int) and isinstance(right_page, int):
        return abs(left_page - right_page)
    return 999999


if __name__ == "__main__":
    sys.exit(main())
