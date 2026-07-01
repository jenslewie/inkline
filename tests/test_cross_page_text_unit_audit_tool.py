from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from inkline.canonical import make_observation, make_observed_document, make_observed_page


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_cross_page_text_units.py"
    spec = importlib.util.spec_from_file_location("audit_cross_page_text_units", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document() -> dict[str, Any]:
    metadata = {
        "doc_id": "sample",
        "title": "Sample",
        "language": "en",
        "source_file": "sample.pdf",
        "parser_name": "parser-neutral",
        "parser_mode": "shadow",
    }
    return make_observed_document(
        metadata,
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Page bottom",
                page=1,
                bbox=[100, 900, 700, 980],
                spans=[{"page": 1, "bbox": [100, 900, 700, 980]}],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Page top",
                page=2,
                bbox=[102, 30, 690, 90],
                spans=[{"page": 2, "bbox": [102, 30, 690, 90]}],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
        ],
    )


def test_cross_page_text_unit_audit_reports_geometry_signals(tmp_path) -> None:
    tool = _load_tool()
    observed_path = tmp_path / "observed.json"
    observed_path.write_text(json.dumps(_document()), encoding="utf-8")

    report = tool.audit_cross_page_text_units(observed_path)

    assert report["summary"]["cross_page_unit_count"] == 1
    assert report["summary"]["cross_page_transition_count"] == 1
    record = report["records"][0]
    assert record["unit_id"] == "tu000001"
    assert record["from_page"] == 1
    assert record["to_page"] == 2
    assert record["previous_bottom_ratio"] == 0.98
    assert record["next_top_ratio"] == 0.03
    assert record["left_delta"] == 2.0
    assert record["horizontal_overlap_ratio"] > 0.99
    assert record["observation_ids"] == ["obs000001", "obs000002"]


def test_cross_page_text_unit_audit_cli_writes_report(tmp_path, capsys) -> None:
    tool = _load_tool()
    observed_path = tmp_path / "observed.json"
    output_path = tmp_path / "audit.json"
    observed_path.write_text(json.dumps(_document()), encoding="utf-8")

    exit_code = tool.main([str(observed_path), "--output", str(output_path)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["summary"]["cross_page_transition_count"] == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["records"][0]["to_page"] == 2


def test_cross_page_text_unit_audit_cli_can_print_summary_only(tmp_path, capsys) -> None:
    tool = _load_tool()
    observed_path = tmp_path / "observed.json"
    output_path = tmp_path / "audit.json"
    observed_path.write_text(json.dumps(_document()), encoding="utf-8")

    exit_code = tool.main([str(observed_path), "--summary-only", "--output", str(output_path)])

    assert exit_code == 0
    stdout_report = json.loads(capsys.readouterr().out)
    assert stdout_report["summary"]["cross_page_transition_count"] == 1
    assert "records" not in stdout_report
    assert json.loads(output_path.read_text(encoding="utf-8"))["records"][0]["to_page"] == 2
