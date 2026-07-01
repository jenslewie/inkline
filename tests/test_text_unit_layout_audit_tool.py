from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from inkline.canonical import make_observation, make_observed_document, make_observed_page


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_text_unit_layout.py"
    spec = importlib.util.spec_from_file_location("audit_text_unit_layout", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _observed() -> dict[str, Any]:
    return make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "sample_parser",
            "parser_mode": "base",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body before",
                page=1,
                bbox=[100, 100, 900, 130],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Inset text",
                page=1,
                bbox=[260, 170, 730, 200],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body after",
                page=1,
                bbox=[100, 240, 900, 270],
                role_hint="body_text",
                attrs={"reading_order": 3},
            ),
        ],
    )


def test_audit_text_unit_layout_cli_writes_parser_neutral_report(tmp_path, capsys) -> None:
    tool = _load_tool()
    observed_path = tmp_path / "observed.json"
    output_path = tmp_path / "layout_audit.json"
    observed_path.write_text(json.dumps(_observed()), encoding="utf-8")

    exit_code = tool.main([str(observed_path), "--output", str(output_path)])

    assert exit_code == 0
    stdout_report = json.loads(capsys.readouterr().out)
    written_report = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_report == written_report
    assert written_report["summary"]["classified_display_blocks"] == 1
    assert written_report["unit_records"][1]["decision"] == "display_block"
    assert "text" not in written_report["unit_records"][1]
