from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    make_bookgraph,
    make_evidence,
    make_node,
    make_observation,
    make_observed_document,
    make_observed_page,
)


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_bookgraph_golden_alignment.py"
    spec = importlib.util.spec_from_file_location("audit_bookgraph_golden_alignment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _golden(blocks: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "metadata": {
            "schema_version": "1.0",
            "doc_id": "fixture",
            "title": "Fixture",
            "language": "zh-CN",
            "source_file": "fixture.pdf",
            "parser_name": "verified",
            "parser_mode": "golden",
        },
        "blocks": [
            {
                "block_id": f"b{index:06d}",
                "type": block_type,
                "text": text,
                "source": {
                    "page": index,
                    "bbox": [100, index * 100, 500, index * 100 + 20],
                    "spans": [{"page": index, "bbox": [100, index * 100, 500, index * 100 + 20]}],
                },
                "attrs": {},
            }
            for index, (block_type, text) in enumerate(blocks, start=1)
        ],
    }


def _graph(nodes: list[tuple[str, str]]) -> dict[str, Any]:
    graph_nodes = [
        make_node(
            f"n{index:06d}",
            node_type,
            text,
            attrs={
                "source_text_unit_id": f"tu{index:06d}",
                "layout_classification": {"signals": ["fixture"]},
            },
            evidence_ids=[f"ev{index:06d}"],
        )
        for index, (node_type, text) in enumerate(nodes, start=1)
    ]
    evidence = [
        make_evidence(
            f"ev{index:06d}",
            "parser-neutral",
            f"tu{index:06d}",
            source_kind="text_unit",
            page=index,
            pages=[index],
            bbox=[100, index * 100, 500, index * 100 + 20],
            spans=[{"page": index, "bbox": [100, index * 100, 500, index * 100 + 20]}],
        )
        for index in range(1, len(nodes) + 1)
    ]
    reading_order = [node["node_id"] for node in graph_nodes]
    return make_bookgraph(
        {
            "doc_id": "fixture",
            "title": "Fixture",
            "language": "zh-CN",
            "source_file": "fixture.pdf",
            "parser_name": "parser-neutral",
            "parser_mode": "shadow",
        },
        graph_nodes,
        [],
        evidence,
        projections={"reading_order": reading_order, "epub_flow": reading_order, "rag_units": []},
    )


def _observed_document(text: str) -> dict[str, Any]:
    return make_observed_document(
        {
            "schema_name": OBSERVED_SCHEMA_NAME,
            "schema_version": OBSERVED_SCHEMA_VERSION,
            "doc_id": "fixture",
            "title": "Fixture",
            "language": "zh-CN",
            "source_file": "fixture.pdf",
            "parser_name": "parser-neutral",
            "parser_mode": "shadow",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text=text,
                page=1,
                bbox=[100, 100, 900, 180],
                role_hint="body_text",
                attrs={"reading_order": 1},
            )
        ],
    )


def _image_text_observed_document(text: str) -> dict[str, Any]:
    return make_observed_document(
        {
            "schema_name": OBSERVED_SCHEMA_NAME,
            "schema_version": OBSERVED_SCHEMA_VERSION,
            "doc_id": "fixture",
            "title": "Fixture",
            "language": "zh-CN",
            "source_file": "fixture.pdf",
            "parser_name": "parser-neutral",
            "parser_mode": "shadow",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "image_region",
                page=1,
                bbox=[100, 100, 900, 700],
            ),
            make_observation(
                "obs000002",
                "text_region",
                text=text,
                page=1,
                bbox=[300, 760, 500, 790],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
        ],
    )


def test_alignment_audit_finds_display_fp_and_fn_hidden_by_equal_counts(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    golden_path.write_text(
        json.dumps(
            _golden(
                [
                    ("display_block", "true display one"),
                    ("display_block", "true display two"),
                    ("paragraph", "body paragraph promoted by mistake"),
                ]
            )
        ),
        encoding="utf-8",
    )
    graph_path.write_text(
        json.dumps(
            _graph(
                [
                    ("display_block", "true display one"),
                    ("paragraph", "true display two"),
                    ("display_block", "body paragraph promoted by mistake"),
                ]
            )
        ),
        encoding="utf-8",
    )

    report = tool.audit_bookgraph_golden_alignment(golden_path, graph_path)

    assert report["summary"]["display_block"]["golden_count"] == 2
    assert report["summary"]["display_block"]["observed_count"] == 2
    assert report["summary"]["display_block"]["net_count_delta"] == 0
    assert report["summary"]["display_block"]["matched"] == 1
    assert report["summary"]["display_block"]["false_negative"] == 1
    assert report["summary"]["display_block"]["false_positive"] == 1
    assert report["summary"]["display_block"]["type_mismatch"] == 2
    assert report["false_negatives"]["display_block"][0]["golden"]["text_preview"] == (
        "true display two"
    )
    assert report["false_positives"]["display_block"][0]["observed"]["text_preview"] == (
        "body paragraph promoted by mistake"
    )


def test_alignment_audit_reports_heading_type_mismatches(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    golden_path.write_text(
        json.dumps(_golden([("heading", "chapter title"), ("paragraph", "body line")])),
        encoding="utf-8",
    )
    graph_path.write_text(
        json.dumps(_graph([("paragraph", "chapter title"), ("heading", "body line")])),
        encoding="utf-8",
    )

    report = tool.audit_bookgraph_golden_alignment(golden_path, graph_path)

    assert report["summary"]["heading"]["golden_count"] == 1
    assert report["summary"]["heading"]["observed_count"] == 1
    assert report["summary"]["heading"]["net_count_delta"] == 0
    assert report["summary"]["heading"]["matched"] == 0
    assert report["summary"]["heading"]["false_negative"] == 1
    assert report["summary"]["heading"]["false_positive"] == 1
    assert report["summary"]["heading"]["type_mismatch"] == 2


def test_alignment_audit_cli_writes_report(tmp_path, capsys) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    output_path = tmp_path / "alignment.json"
    golden_path.write_text(
        json.dumps(_golden([("display_block", "display text")])),
        encoding="utf-8",
    )
    graph_path.write_text(
        json.dumps(_graph([("display_block", "display text")])),
        encoding="utf-8",
    )

    exit_code = tool.main(
        [str(golden_path), str(graph_path), "--output", str(output_path), "--summary-only"]
    )

    assert exit_code == 0
    stdout_report = json.loads(capsys.readouterr().out)
    assert stdout_report["status"] == "pass"
    assert "matched" not in stdout_report
    assert (
        json.loads(output_path.read_text(encoding="utf-8"))["summary"]["display_block"]["matched"]
        == 1
    )


def test_alignment_audit_unmatched_details_are_limited_to_target_types(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    golden_path.write_text(
        json.dumps(
            _golden(
                [
                    ("display_block", "display text"),
                    ("paragraph", "unrelated unmatched paragraph"),
                ]
            )
        ),
        encoding="utf-8",
    )
    graph_path.write_text(
        json.dumps(_graph([("display_block", "display text")])),
        encoding="utf-8",
    )

    report = tool.audit_bookgraph_golden_alignment(golden_path, graph_path)

    assert report["unmatched"]["golden"] == []


def test_alignment_audit_reports_near_candidates_for_split_content(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    golden_path.write_text(
        json.dumps(_golden([("display_block", "alpha beta gamma")])),
        encoding="utf-8",
    )
    graph_path.write_text(
        json.dumps(
            _graph(
                [
                    ("display_block", "alpha beta"),
                    ("display_block", "gamma"),
                ]
            )
        ),
        encoding="utf-8",
    )

    report = tool.audit_bookgraph_golden_alignment(golden_path, graph_path)

    candidates = report["false_negatives"]["display_block"][0]["observed_candidates"]
    assert candidates[0]["record"]["text_preview"] == "alpha beta"
    assert candidates[0]["text_similarity"] > 0.5


def test_alignment_audit_can_include_text_unit_layout_record(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    observed_path = tmp_path / "observed.json"
    golden_path.write_text(
        json.dumps(_golden([("display_block", "quoted text")])),
        encoding="utf-8",
    )
    graph_path.write_text(
        json.dumps(_graph([("paragraph", "quoted text")])),
        encoding="utf-8",
    )
    observed_path.write_text(
        json.dumps(_observed_document("quoted text")),
        encoding="utf-8",
    )

    report = tool.audit_bookgraph_golden_alignment(
        golden_path,
        graph_path,
        observed_path=observed_path,
    )

    observed = report["type_mismatches"]["display_block"][0]["observed"]
    assert observed["source_text_unit_id"] == "tu000001"
    assert observed["layout_audit"]["decision"] == "skipped_no_profile"


def test_alignment_audit_breaks_down_misses_by_page_bucket(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    observed_path = tmp_path / "observed.json"
    golden_path.write_text(
        json.dumps(_golden([("paragraph", "map label")])),
        encoding="utf-8",
    )
    graph_path.write_text(
        json.dumps(_graph([("display_block", "map label")])),
        encoding="utf-8",
    )
    observed_path.write_text(
        json.dumps(_image_text_observed_document("map label")),
        encoding="utf-8",
    )

    report = tool.audit_bookgraph_golden_alignment(
        golden_path,
        graph_path,
        observed_path=observed_path,
    )

    observed = report["false_positives"]["display_block"][0]["observed"]
    assert observed["page_buckets"] == ["image_with_text_units", "paragraph_without_profile"]
    assert report["summary"]["display_block"]["page_bucket_breakdown"]["false_positive"] == {
        "image_with_text_units": 1,
        "paragraph_without_profile": 1,
    }
