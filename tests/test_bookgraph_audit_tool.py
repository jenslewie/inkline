from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_bookgraph_shadow.py"
    spec = importlib.util.spec_from_file_location("audit_bookgraph_shadow", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical() -> dict[str, Any]:
    return {
        "metadata": {
            "schema_version": "1.0",
            "doc_id": "fixture",
            "title": "Fixture",
            "language": "zh-CN",
            "source_file": "fixture.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        "blocks": [
            {
                "block_id": "b000001",
                "type": "heading",
                "text": "第一章",
                "level": 1,
                "source": {"page": 1, "bbox": [100, 100, 500, 140]},
                "attrs": {},
            },
            {
                "block_id": "b000002",
                "type": "paragraph",
                "text": "正文段落",
                "source": {"page": 1, "bbox": [100, 160, 800, 220]},
                "attrs": {},
            },
            {
                "block_id": "b000003",
                "type": "display_block",
                "text": "展示段落" * 20,
                "source": {"page": 1, "bbox": [180, 260, 760, 360]},
                "attrs": {"layout_role": "inline_display_block"},
            },
        ],
    }


def test_audit_bookgraph_shadow_tool_writes_shadow_and_audit(tmp_path, capsys) -> None:
    tool = _load_tool()
    canonical_path = tmp_path / "canonical.json"
    bookgraph_path = tmp_path / "canonical_v2.json"
    audit_path = tmp_path / "bookgraph_audit.json"
    canonical_path.write_text(json.dumps(_canonical()), encoding="utf-8")

    exit_code = tool.main(
        [
            str(canonical_path),
            "--bookgraph-output",
            str(bookgraph_path),
            "--audit-output",
            str(audit_path),
            "--expect-exact-projection",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["metadata"]["schema_name"] == "inkline_bookgraph"
    assert summary["exact_projection"] is True
    assert bookgraph_path.exists()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["projection_diff"]["exact_supported_fields_match"] is True


def test_audit_bookgraph_shadow_tool_can_fail_on_body_like_display_threshold(
    tmp_path,
) -> None:
    tool = _load_tool()
    canonical_path = tmp_path / "canonical.json"
    canonical_path.write_text(json.dumps(_canonical()), encoding="utf-8")

    exit_code = tool.main(
        [
            str(canonical_path),
            "--max-body-like-display-blocks",
            "0",
        ]
    )

    assert exit_code == 1
