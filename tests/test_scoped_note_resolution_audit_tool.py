from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from inkline.canonical import make_bookgraph, make_evidence, make_node


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_scoped_note_resolution.py"
    spec = importlib.util.spec_from_file_location("audit_scoped_note_resolution", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metadata() -> dict[str, str]:
    return {
        "schema_name": "inkline_bookgraph",
        "schema_version": "2.0-shadow",
        "doc_id": "sample",
        "title": "Sample",
        "language": "en",
        "source_file": "sample.pdf",
        "parser_name": "mineru",
        "parser_mode": "vlm",
    }


def _graph() -> dict[str, Any]:
    return make_bookgraph(
        _metadata(),
        [
            make_node("n000001", "heading", "Chapter One", attrs={}, evidence_ids=["ev000001"]),
            make_node(
                "n000002",
                "paragraph",
                "Body text 1.",
                inline_runs=[
                    {
                        "type": "note_ref",
                        "text": "1",
                        "attrs": {
                            "marker": "1",
                            "target_note_id": "n000005",
                            "scope": "chapter",
                            "scope_key": "chapterone",
                        },
                    }
                ],
                attrs={},
                evidence_ids=["ev000002"],
            ),
            make_node(
                "n000003",
                "heading",
                "Notes",
                attrs={"note_section_id": "ns000001"},
                evidence_ids=["ev000003"],
            ),
            make_node(
                "n000004",
                "heading",
                "Chapter One",
                attrs={"note_section_id": "ns000001"},
                evidence_ids=["ev000004"],
            ),
            make_node(
                "n000005",
                "note",
                "A chapter note.",
                attrs={
                    "marker": "1",
                    "source_placement": "book_end",
                    "scope": "chapter",
                    "scope_key": "chapterone",
                    "source_text_unit_ids": ["tu000005"],
                    "note_section_id": "ns000001",
                },
                evidence_ids=["ev000005"],
            ),
            make_node(
                "n000006",
                "note",
                "Mismatched chapter note.",
                attrs={
                    "marker": "2",
                    "source_placement": "book_end",
                    "scope": "chapter",
                    "scope_key": "chaptertwo",
                    "source_text_unit_ids": ["tu000006"],
                    "note_section_id": "ns000001",
                },
                evidence_ids=["ev000006"],
            ),
            make_node(
                "n000007",
                "paragraph",
                "Body text 2.",
                inline_runs=[
                    {
                        "type": "note_ref",
                        "text": "2",
                        "attrs": {
                            "marker": "2",
                            "target_note_id": "n000006",
                            "scope": "chapter",
                            "scope_key": "chaptertwo",
                        },
                    }
                ],
                attrs={},
                evidence_ids=["ev000007"],
            ),
        ],
        [],
        [
            make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=1),
            make_evidence("ev000002", "mineru", "tu000002", source_kind="text_unit", page=2),
            make_evidence("ev000003", "mineru", "tu000003", source_kind="text_unit", page=90),
            make_evidence("ev000004", "mineru", "tu000004", source_kind="text_unit", page=90),
            make_evidence("ev000005", "mineru", "tu000005", source_kind="text_unit", page=91),
            make_evidence("ev000006", "mineru", "tu000006", source_kind="text_unit", page=92),
            make_evidence("ev000007", "mineru", "tu000007", source_kind="text_unit", page=3),
        ],
        projections={
            "reading_order": [
                "n000001",
                "n000002",
                "n000007",
                "n000003",
                "n000004",
                "n000005",
                "n000006",
            ]
        },
    )


def test_scoped_note_resolution_audit_reports_high_risk_scope_mismatch(tmp_path) -> None:
    tool = _load_tool()
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")

    report = tool.audit_scoped_note_resolution(graph_path)

    assert report["summary"]["scoped_resolved_count"] == 2
    assert report["summary"]["high_risk_resolved_count"] == 1
    high_risk = report["high_risk_resolved"][0]
    assert high_risk["source_node_id"] == "n000007"
    assert high_risk["target_note_id"] == "n000006"
    assert high_risk["risk_flags"] == ["scope_mismatch"]


def test_scoped_note_resolution_audit_cli_writes_json_and_markdown(tmp_path, capsys) -> None:
    tool = _load_tool()
    graph_path = tmp_path / "graph.json"
    output_path = tmp_path / "audit.json"
    markdown_path = tmp_path / "audit.md"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")

    exit_code = tool.main(
        [
            str(graph_path),
            "--output",
            str(output_path),
            "--markdown-output",
            str(markdown_path),
            "--summary-only",
        ]
    )

    assert exit_code == 0
    stdout_report = json.loads(capsys.readouterr().out)
    assert stdout_report["summary"]["scoped_resolved_count"] == 2
    assert json.loads(output_path.read_text(encoding="utf-8"))["books"][0]["summary"][
        "high_risk_resolved_count"
    ] == 1
    assert "Scoped Note Resolution Audit" in markdown_path.read_text(encoding="utf-8")
