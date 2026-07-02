from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from inkline.canonical import make_bookgraph, make_evidence, make_node


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "check_phase3_shadow_acceptance.py"
    spec = importlib.util.spec_from_file_location("check_phase3_shadow_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metadata(doc_id: str = "sample") -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "title": "Sample",
        "language": "en",
        "source_file": "sample.pdf",
        "parser_name": "parser-neutral",
        "parser_mode": "shadow",
        "shadow_source_schema_version": "2.0-observed-shadow",
        "shadow_ignored_observation_counts": {"image_region": 1},
        "shadow_text_unit_layout_audit_summary": {
            "pages_with_profiles": 1,
            "paragraph_units": 1,
            "classified_display_blocks": 0,
            "skipped_no_bbox": 0,
            "skipped_no_profile": 0,
        },
        "shadow_text_unit_layout_profile_quality": {
            "accepted": 1,
            "filled_from_nearest_profile": 0,
            "rejected_no_stable_profile": 0,
            "rejected_invalid_width": 0,
            "rejected_unstable_widths": 0,
            "rejected_extreme_body_width": 0,
        },
        "shadow_page_roles": [
            {
                "page": 1,
                "page_role": "title_like_page",
                "flow_scope": "front_matter",
                "include_in_epub": True,
                "include_in_rag": False,
                "signals": ["early_page", "sparse_centered_text", "no_body_profile"],
            },
            {
                "page": 2,
                "page_role": "body",
                "flow_scope": "body",
                "include_in_epub": True,
                "include_in_rag": True,
                "signals": ["body_profile"],
            },
        ],
    }


def _graph(doc_id: str = "sample") -> dict[str, Any]:
    front_heading = make_node(
        "n000001",
        "heading",
        "Title",
        attrs={
            "source_text_unit_id": "tu000001",
            "flow_scope": "front_matter",
            "page_role": "title_like_page",
            "include_in_rag": False,
        },
        evidence_ids=["ev000001"],
    )
    body_node = make_node(
        "n000002",
        "paragraph",
        "Body",
        attrs={
            "source_text_unit_id": "tu000002",
            "layout_role": "normal_flow",
            "flow_scope": "body",
            "page_role": "body",
            "include_in_rag": True,
            "merge_reasons": ["cross_page_boundary_continuation"],
        },
        evidence_ids=["ev000002"],
    )
    front_evidence = make_evidence(
        "ev000001",
        "parser-neutral",
        "tu000001",
        source_kind="text_unit",
        page=1,
        pages=[1],
        bbox=[10, 20, 300, 80],
    )
    body_evidence = make_evidence(
        "ev000002",
        "parser-neutral",
        "tu000002",
        source_kind="text_unit",
        page=2,
        pages=[2, 3],
        bbox=[10, 20, 300, 400],
        spans=[{"page": 2, "bbox": [10, 20, 300, 400]}],
    )
    return make_bookgraph(
        _metadata(doc_id),
        [front_heading, body_node],
        [],
        [front_evidence, body_evidence],
        projections={
            "reading_order": ["n000001", "n000002"],
            "epub_flow": ["n000001", "n000002"],
            "rag_units": [{"unit_id": "ru000001", "node_id": "n000002"}],
        },
    )


def test_phase3_shadow_acceptance_summarizes_structural_signals(tmp_path) -> None:
    tool = _load_tool()
    graph_path = tmp_path / "bookgraph.json"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")

    report = tool.check_phase3_shadow_acceptance([graph_path])

    assert report["status"] == "pass"
    assert report["totals"]["book_count"] == 1
    assert report["totals"]["node_counts"] == {"heading": 1, "paragraph": 1}
    assert report["totals"]["node_counts_by_flow_scope"] == {
        "body": {"paragraph": 1},
        "front_matter": {"heading": 1},
    }
    assert report["totals"]["node_counts_by_rag_inclusion"] == {
        "excluded": {"heading": 1},
        "included": {"paragraph": 1},
    }
    assert report["books"][0]["page_role_counts"] == {
        "body": 1,
        "title_like_page": 1,
    }
    assert report["totals"]["merge_counts"] == {"cross_page_boundary_continuation": 1}
    assert report["books"][0]["multi_page_evidence_count"] == 1
    assert report["books"][0]["ignored_counts"] == {"image_region": 1}
    assert report["books"][0]["profile_quality"]["accepted"] == 1


def test_phase3_shadow_acceptance_cli_writes_report(tmp_path, capsys) -> None:
    tool = _load_tool()
    graph_path = tmp_path / "bookgraph.json"
    output_path = tmp_path / "acceptance.json"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")

    exit_code = tool.main([str(graph_path), "--output", str(output_path)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
    assert json.loads(output_path.read_text(encoding="utf-8"))["books"][0]["doc_id"] == "sample"


def test_phase3_shadow_acceptance_fails_on_empty_reading_order(tmp_path) -> None:
    tool = _load_tool()
    graph = _graph()
    graph["projections"]["reading_order"] = []
    graph_path = tmp_path / "bookgraph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")

    report = tool.check_phase3_shadow_acceptance([graph_path])

    assert report["status"] == "fail"
    assert "reading_order_node_count_mismatch" in report["books"][0]["errors"]
