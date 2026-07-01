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
            "rejected_too_few_references": 0,
            "rejected_invalid_width": 0,
            "rejected_unstable_widths": 0,
            "rejected_extreme_body_width": 0,
        },
    }


def _graph(doc_id: str = "sample") -> dict[str, Any]:
    node = make_node(
        "n000001",
        "paragraph",
        "Body",
        attrs={
            "source_text_unit_id": "tu000001",
            "layout_role": "normal_flow",
            "merge_reasons": ["cross_page_boundary_continuation"],
        },
        evidence_ids=["ev000001"],
    )
    evidence = make_evidence(
        "ev000001",
        "parser-neutral",
        "tu000001",
        source_kind="text_unit",
        page=1,
        pages=[1, 2],
        bbox=[10, 20, 300, 400],
        spans=[{"page": 1, "bbox": [10, 20, 300, 400]}],
    )
    return make_bookgraph(
        _metadata(doc_id),
        [node],
        [],
        [evidence],
        projections={"reading_order": ["n000001"], "epub_flow": ["n000001"], "rag_units": []},
    )


def test_phase3_shadow_acceptance_summarizes_structural_signals(tmp_path) -> None:
    tool = _load_tool()
    graph_path = tmp_path / "bookgraph.json"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")

    report = tool.check_phase3_shadow_acceptance([graph_path])

    assert report["status"] == "pass"
    assert report["totals"]["book_count"] == 1
    assert report["totals"]["node_counts"] == {"paragraph": 1}
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
