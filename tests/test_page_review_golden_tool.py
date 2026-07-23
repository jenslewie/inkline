from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "check_page_review_golden.py"
    spec = importlib.util.spec_from_file_location("check_page_review_golden", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_page_review_golden_checker_reports_only_stable_page_contract_diffs(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "golden.json"
    observed_path = tmp_path / "observed.json"
    golden = _page_review("sample", "front_exterior_page")
    observed = _page_review("sample", "back_exterior_page")
    observed["metadata"]["schema_version"] = "0.8-shadow"
    observed["llm"] = {"model": "new-model", "prompt_version": "new-prompt"}
    golden_path.write_text(json.dumps(golden), encoding="utf-8")
    observed_path.write_text(json.dumps(observed), encoding="utf-8")

    report = tool.check_page_review_golden(golden_path, observed_path)

    assert report["status"] == "fail"
    assert report["errors"] == [
        {
            "kind": "field_mismatch",
            "page": 1,
            "field": "special_page_kind",
            "golden": "front_exterior_page",
            "observed": "back_exterior_page",
        }
    ]


def test_page_review_golden_checker_accepts_metadata_changes(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "golden.json"
    observed_path = tmp_path / "observed.json"
    golden_path.write_text(json.dumps(_page_review("sample", "front_exterior_page")), encoding="utf-8")
    observed = _page_review("sample", "front_exterior_page")
    observed["metadata"]["schema_version"] = "0.8-shadow"
    observed_path.write_text(json.dumps(observed), encoding="utf-8")

    report = tool.check_page_review_golden(golden_path, observed_path)

    assert report["status"] == "pass"
    assert report["errors"] == []


def test_page_review_golden_checker_rejects_an_unexpected_page(tmp_path) -> None:
    tool = _load_tool()
    golden_path = tmp_path / "golden.json"
    observed_path = tmp_path / "observed.json"
    golden_path.write_text(json.dumps(_page_review("sample", "front_exterior_page")), encoding="utf-8")
    observed = _page_review("sample", "front_exterior_page")
    observed["pages"].append(
        {
            "page": 2,
            "page_role": "text_flow_page",
            "book_block_position": "front_matter",
            "special_page_kind": None,
            "text_flow_action": "include",
            "visual_asset_action": "not_needed",
        }
    )
    observed_path.write_text(json.dumps(observed), encoding="utf-8")

    report = tool.check_page_review_golden(golden_path, observed_path)

    assert report["status"] == "fail"
    assert report["errors"] == [{"kind": "unexpected_page", "page": 2}]


def _page_review(doc_id: str, special_page_kind: str) -> dict:
    return {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.5-shadow", "doc_id": doc_id},
        "pages": [
            {
                "page": 1,
                "page_role": "visual_page",
                "book_block_position": "external_wrap",
                "special_page_kind": special_page_kind,
                "text_flow_action": "exclude",
                "visual_asset_action": "retain",
            }
        ],
    }
