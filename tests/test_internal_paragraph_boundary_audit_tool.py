from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.observed_bookgraph import build_internal_canonical_from_observed


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_internal_paragraph_boundaries.py"
    spec = importlib.util.spec_from_file_location("audit_internal_paragraph_boundaries", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metadata() -> dict:
    return {
        "schema_name": OBSERVED_SCHEMA_NAME,
        "schema_version": OBSERVED_SCHEMA_VERSION,
        "doc_id": "sample",
        "title": "Sample",
        "language": "en",
        "source_file": "sample.pdf",
        "parser_name": "sample_parser",
        "parser_mode": "base",
    }


def test_audit_reports_same_page_text_unit_splits_without_public_leak(tmp_path) -> None:
    tool = _load_tool()
    internal = build_internal_canonical_from_observed(
        make_observed_document(
            _metadata(),
            [make_observed_page(1, width=1000, height=1000)],
            [
                make_observation(
                    "obs000001",
                    "text_region",
                    text="First paragraph.",
                    page=1,
                    bbox=[100, 100, 700, 130],
                    role_hint="body_text",
                    attrs={"reading_order": 1},
                ),
                make_observation(
                    "obs000002",
                    "text_region",
                    text="Second paragraph.",
                    page=1,
                    bbox=[102, 135, 690, 160],
                    role_hint="body_text",
                    attrs={"reading_order": 2},
                ),
            ],
        )
    )
    path = tmp_path / "internal.json"
    tool._write_json(path, internal)

    report = tool.audit_internal_paragraph_boundaries(path)

    assert report["summary"]["paragraph_nodes"] == 2
    assert report["summary"]["split_text_unit_groups"] == 1
    assert report["summary"]["same_page_geometry_leaks"] == 0


def test_audit_reports_nonconsecutive_page_continuation_candidates(tmp_path) -> None:
    tool = _load_tool()
    internal = build_internal_canonical_from_observed(
        make_observed_document(
            _metadata(),
            [
                make_observed_page(1, width=1000, height=1000),
                make_observed_page(2, width=1000, height=1000),
                make_observed_page(3, width=1000, height=1000),
            ],
            [
                make_observation(
                    "obs000001",
                    "text_region",
                    text="Body before",
                    page=1,
                    bbox=[100, 100, 700, 130],
                    role_hint="body_text",
                    attrs={"reading_order": 1},
                ),
                make_observation(
                    "obs000002",
                    "text_region",
                    text="Paragraph tail",
                    page=1,
                    bbox=[100, 900, 700, 980],
                    role_hint="body_text",
                    attrs={"reading_order": 2},
                ),
                make_observation(
                    "obs000003",
                    "image_region",
                    page=2,
                    bbox=[100, 100, 900, 900],
                    attrs={"reading_order": 1},
                ),
                make_observation(
                    "obs000004",
                    "text_region",
                    text="Paragraph head",
                    page=3,
                    bbox=[300, 30, 890, 90],
                    role_hint="body_text",
                    attrs={"reading_order": 1},
                ),
                make_observation(
                    "obs000005",
                    "text_region",
                    text="Body after",
                    page=3,
                    bbox=[300, 180, 890, 220],
                    role_hint="body_text",
                    attrs={"reading_order": 2},
                ),
            ],
        )
    )
    path = tmp_path / "internal.json"
    tool._write_json(path, internal)

    report = tool.audit_internal_paragraph_boundaries(path)

    assert report["summary"]["nonconsecutive_page_continuation_candidates"] == 1
    sample = report["samples"]["nonconsecutive_page_continuation_candidates"][0]
    assert sample["previous_page"] == 1
    assert sample["current_page"] == 3
    assert sample["previous_page_role"] == "text_flow_page"
    assert sample["current_page_role"] == "text_flow_page"


def test_audit_does_not_skip_intervening_nonparagraph_nodes(tmp_path) -> None:
    tool = _load_tool()
    internal = build_internal_canonical_from_observed(
        make_observed_document(
            _metadata(),
            [
                make_observed_page(1, width=1000, height=1000),
                make_observed_page(2, width=1000, height=1000),
                make_observed_page(3, width=1000, height=1000),
            ],
            [
                make_observation(
                    "obs000001",
                    "text_region",
                    text="Body before",
                    page=1,
                    bbox=[100, 100, 700, 130],
                    role_hint="body_text",
                    attrs={"reading_order": 1},
                ),
                make_observation(
                    "obs000002",
                    "text_region",
                    text="Paragraph tail",
                    page=1,
                    bbox=[100, 900, 700, 980],
                    role_hint="body_text",
                    attrs={"reading_order": 2},
                ),
                make_observation(
                    "obs000003",
                    "image_region",
                    page=2,
                    bbox=[100, 100, 900, 900],
                    attrs={"reading_order": 1},
                ),
                make_observation(
                    "obs000004",
                    "text_region",
                    text="Intervening heading",
                    page=3,
                    bbox=[300, 30, 700, 90],
                    role_hint="title_text",
                    attrs={"reading_order": 1},
                ),
                make_observation(
                    "obs000005",
                    "text_region",
                    text="Paragraph head",
                    page=3,
                    bbox=[102, 120, 690, 160],
                    role_hint="body_text",
                    attrs={"reading_order": 2},
                ),
            ],
        )
    )
    path = tmp_path / "internal.json"
    tool._write_json(path, internal)

    report = tool.audit_internal_paragraph_boundaries(path)

    assert report["summary"]["nonconsecutive_page_continuation_candidates"] == 0


def test_audit_reports_suspicious_cross_page_new_paragraph_merge(tmp_path) -> None:
    tool = _load_tool()
    internal = build_internal_canonical_from_observed(
        make_observed_document(
            _metadata(),
            [
                make_observed_page(1, width=1000, height=1000),
                make_observed_page(2, width=1000, height=1000),
            ],
            [
                make_observation(
                    "obs000001",
                    "text_region",
                    text="Merged tail",
                    page=1,
                    bbox=[100, 900, 700, 980],
                    role_hint="body_text",
                    attrs={"reading_order": 1},
                ),
                make_observation(
                    "obs000002",
                    "text_region",
                    text="Actually new paragraph",
                    page=2,
                    bbox=[102, 30, 690, 90],
                    role_hint="body_text",
                    attrs={"reading_order": 1},
                ),
            ],
        )
    )
    observations = internal["pipeline"]["observed_document"]["observations"]
    observations[1]["attrs"]["text_line_metrics"] = {
        "line_count": 3,
        "first_line_indent": 18,
        "char_width": 10,
    }
    path = tmp_path / "internal.json"
    tool._write_json(path, internal)

    report = tool.audit_internal_paragraph_boundaries(path)

    assert report["summary"]["suspicious_cross_page_new_paragraph_merges"] == 1
    sample = report["samples"]["suspicious_cross_page_new_paragraph_merges"][0]
    assert sample["current_observation_id"] == "obs000002"


def test_audit_reports_adjacent_page_split_continuation_candidate(tmp_path) -> None:
    tool = _load_tool()
    internal = build_internal_canonical_from_observed(
        make_observed_document(
            _metadata(),
            [
                make_observed_page(1, width=1000, height=1000),
                make_observed_page(2, width=1000, height=1000),
            ],
            [
                make_observation(
                    "obs000001",
                    "text_region",
                    text="Split tail",
                    page=1,
                    bbox=[300, 900, 900, 980],
                    role_hint="body_text",
                    attrs={"reading_order": 1},
                ),
                make_observation(
                    "obs000002",
                    "text_region",
                    text="continues here",
                    page=2,
                    bbox=[100, 30, 700, 90],
                    role_hint="body_text",
                    attrs={"reading_order": 1},
                ),
            ],
        )
    )
    observations = internal["pipeline"]["observed_document"]["observations"]
    observations[1]["attrs"]["text_line_metrics"] = {
        "line_count": 3,
        "first_line_indent": 0,
        "char_width": 10,
    }
    path = tmp_path / "internal.json"
    tool._write_json(path, internal)

    report = tool.audit_internal_paragraph_boundaries(path)

    assert report["summary"]["adjacent_page_split_continuation_candidates"] == 1
    sample = report["samples"]["adjacent_page_split_continuation_candidates"][0]
    assert sample["previous_node_id"] == "n000001"
    assert sample["current_node_id"] == "n000002"
