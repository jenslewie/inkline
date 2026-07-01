from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from inkline.canonical import make_bookgraph, make_evidence, make_node


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "check_bookgraph_golden_parity.py"
    spec = importlib.util.spec_from_file_location("check_bookgraph_golden_parity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _golden(block_types: list[str]) -> dict[str, Any]:
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
                "text": f"{block_type} {index}",
                "source": {"page": index},
                "attrs": {},
            }
            for index, block_type in enumerate(block_types, start=1)
        ],
    }


def _graph(node_types: list[str]) -> dict[str, Any]:
    nodes = [
        make_node(
            f"n{index:06d}",
            node_type,
            f"{node_type} {index}",
            attrs={"source_text_unit_id": f"tu{index:06d}"},
            evidence_ids=[f"ev{index:06d}"],
        )
        for index, node_type in enumerate(node_types, start=1)
    ]
    evidence = [
        make_evidence(
            f"ev{index:06d}",
            "parser-neutral",
            f"tu{index:06d}",
            source_kind="text_unit",
            page=index,
            pages=[index],
        )
        for index in range(1, len(node_types) + 1)
    ]
    reading_order = [node["node_id"] for node in nodes]
    return make_bookgraph(
        {
            "doc_id": "fixture",
            "title": "Fixture",
            "language": "zh-CN",
            "source_file": "fixture.pdf",
            "parser_name": "parser-neutral",
            "parser_mode": "shadow",
        },
        nodes,
        [],
        evidence,
        projections={"reading_order": reading_order, "epub_flow": reading_order, "rag_units": []},
    )


def test_golden_parity_reports_display_recall_and_heading_overcount(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    golden_path.write_text(
        json.dumps(_golden(["heading", "paragraph", "display_block", "display_block"])),
        encoding="utf-8",
    )
    graph_path.write_text(
        json.dumps(_graph(["heading", "heading", "heading", "heading", "paragraph"])),
        encoding="utf-8",
    )

    report = tool.check_bookgraph_golden_parity(golden_path, graph_path)

    assert report["status"] == "fail"
    assert report["golden_counts"]["display_block"] == 2
    assert report["bookgraph_counts"].get("display_block", 0) == 0
    assert "display_block_recall_below_threshold" in report["errors"]
    assert "heading_count_above_threshold" in report["errors"]


def test_golden_parity_reports_display_text_char_recall(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    golden_path.write_text(
        json.dumps(_golden(["display_block", "display_block"])),
        encoding="utf-8",
    )
    graph = _graph(["display_block", "paragraph"])
    graph["nodes"][0]["text"] = "x"
    graph["nodes"][1]["text"] = "display_block 2"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")

    report = tool.check_bookgraph_golden_parity(
        golden_path,
        graph_path,
        min_display_recall=0.5,
        min_display_text_char_recall=0.5,
    )

    assert report["ratios"]["display_text_char_recall"] < 0.5
    assert "display_text_char_recall_below_threshold" in report["errors"]


def test_golden_parity_cli_writes_report_and_returns_success(tmp_path, capsys) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "canonical.json"
    graph_path = tmp_path / "canonical_v2.json"
    output_path = tmp_path / "parity.json"
    golden_path.write_text(
        json.dumps(_golden(["heading", "paragraph", "display_block"])),
        encoding="utf-8",
    )
    graph_path.write_text(
        json.dumps(_graph(["heading", "paragraph", "display_block"])),
        encoding="utf-8",
    )

    exit_code = tool.main([str(golden_path), str(graph_path), "--output", str(output_path)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
    assert json.loads(output_path.read_text(encoding="utf-8"))["errors"] == []
