from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from inkline.canonical import (
    make_observation,
    make_observed_document,
    make_observed_page,
)


def _load_tool() -> Any:
    path = Path(__file__).resolve().parents[1] / "tools" / "compare_bookgraph_shadow_paths.py"
    spec = importlib.util.spec_from_file_location("compare_bookgraph_shadow_paths", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical() -> dict[str, Any]:
    return {
        "metadata": {
            "schema_version": "1.0",
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        "blocks": [
            {
                "block_id": "b000001",
                "type": "heading",
                "text": "Chapter",
                "level": 1,
                "source": {"page": 1},
                "attrs": {},
            },
            {
                "block_id": "b000002",
                "type": "paragraph",
                "text": "Body",
                "source": {"page": 1},
                "attrs": {},
            },
        ],
    }


def _observed() -> dict[str, Any]:
    return make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Chapter",
                page=1,
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Body changed",
                page=1,
                role_hint="body_text",
            ),
            make_observation("obs000003", "image_region", page=1),
        ],
    )


def test_compare_bookgraph_shadow_paths_reports_structural_deltas(tmp_path) -> None:
    tool = _load_tool()
    canonical_path = tmp_path / "canonical.json"
    observed_path = tmp_path / "observed_document.json"
    canonical_path.write_text(json.dumps(_canonical()), encoding="utf-8")
    observed_path.write_text(json.dumps(_observed()), encoding="utf-8")

    report = tool.compare_shadow_paths(canonical_path, observed_path)

    assert report["v1_shadow"]["node_counts"] == {"heading": 1, "paragraph": 1}
    assert report["observed_shadow"]["node_counts"] == {"heading": 1, "paragraph": 1}
    assert report["reading_order_count_delta"] == 0
    assert report["ignored_counts_delta"] == {"image_region": 1}
    assert report["text_snippet_delta"] == {
        "missing_in_observed": ["Body"],
        "extra_in_observed": ["Body changed"],
    }


def test_compare_bookgraph_shadow_paths_cli_writes_report(tmp_path, capsys) -> None:
    tool = _load_tool()
    canonical_path = tmp_path / "canonical.json"
    observed_path = tmp_path / "observed_document.json"
    output_path = tmp_path / "compare.json"
    canonical_path.write_text(json.dumps(_canonical()), encoding="utf-8")
    observed_path.write_text(json.dumps(_observed()), encoding="utf-8")

    exit_code = tool.main([str(canonical_path), str(observed_path), "--output", str(output_path)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["reading_order_count_delta"] == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["text_snippet_delta"][
        "extra_in_observed"
    ] == ["Body changed"]
