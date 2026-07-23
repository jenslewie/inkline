from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "run_page_review_golden_suite.py"
    spec = importlib.util.spec_from_file_location("run_page_review_golden_suite", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discover_golden_books_sorts_only_complete_artifacts(tmp_path: Path) -> None:
    tool = _load_tool()
    _write_review(tmp_path / "zeta" / "zeta_page_review.json", "zeta")
    _write_review(tmp_path / "alpha" / "alpha_page_review.json", "alpha")
    (tmp_path / "incomplete").mkdir()

    assert tool.discover_golden_books(tmp_path) == ["alpha", "zeta"]


def test_evaluate_staged_reviews_reports_missing_and_stable_field_diffs(tmp_path: Path) -> None:
    tool = _load_tool()
    golden_root = tmp_path / "golden"
    staging_root = tmp_path / "staging"
    _write_review(golden_root / "alpha" / "alpha_page_review.json", "alpha")
    _write_review(golden_root / "beta" / "beta_page_review.json", "beta")
    _write_review(
        staging_root / "alpha" / "alpha_page_review.json",
        "alpha",
        special_page_kind="back_exterior_page",
    )

    report = tool.evaluate_staged_page_reviews(golden_root, staging_root, ["alpha", "beta"])

    assert report["status"] == "fail"
    assert report["books"][0]["book"] == "alpha"
    assert report["books"][0]["report"]["errors"][0]["field"] == "special_page_kind"
    assert report["books"][1] == {
        "book": "beta",
        "status": "fail",
        "error": "missing_staged_page_review",
    }


def test_publish_staged_reviews_replaces_workspace_only_after_green_suite(tmp_path: Path) -> None:
    tool = _load_tool()
    staging_root = tmp_path / "workspace" / ".staging" / "run-1"
    workspace_root = tmp_path / "workspace"
    _write_review(staging_root / "alpha" / "alpha_page_review.json", "alpha")
    old = workspace_root / "alpha"
    old.mkdir(parents=True)
    (old / "old.txt").write_text("old", encoding="utf-8")

    tool.publish_staged_page_reviews(staging_root, workspace_root, ["alpha"])

    assert (workspace_root / "alpha" / "alpha_page_review.json").is_file()
    assert not (workspace_root / "alpha" / "old.txt").exists()
    assert not (staging_root / "alpha").exists()


def test_publish_staged_reviews_refuses_failed_report(tmp_path: Path) -> None:
    tool = _load_tool()
    staging_root = tmp_path / "workspace" / ".staging" / "run-1"
    workspace_root = tmp_path / "workspace"
    _write_review(staging_root / "alpha" / "alpha_page_review.json", "alpha")
    old = workspace_root / "alpha"
    old.mkdir(parents=True)
    (old / "old.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ValueError, match="passing golden report"):
        tool.publish_staged_page_reviews(
            staging_root,
            workspace_root,
            ["alpha"],
            report={"status": "fail"},
        )

    assert (workspace_root / "alpha" / "old.txt").is_file()


def test_run_suite_keeps_workspace_when_staged_result_differs(tmp_path: Path, monkeypatch) -> None:
    tool = _load_tool()
    golden_root = tmp_path / "golden"
    workspace_root = tmp_path / "workspace"
    _write_review(golden_root / "alpha" / "alpha_page_review.json", "alpha")
    old = workspace_root / "alpha"
    old.mkdir(parents=True)
    (old / "old.txt").write_text("old", encoding="utf-8")

    def write_mismatch(book, _args, staging_root):
        _write_review(
            staging_root / book / f"{book}_page_review.json",
            book,
            special_page_kind="back_exterior_page",
        )

    monkeypatch.setattr(tool, "stage_page_review", write_mismatch)

    report = tool.run_suite(_suite_args(tmp_path, golden_root, workspace_root))

    assert report["status"] == "fail"
    assert (workspace_root / "alpha" / "old.txt").is_file()
    assert (tmp_path / "staging" / "suite" / "alpha" / "alpha_page_review.json").is_file()


def test_run_suite_publishes_only_a_passing_staged_result(tmp_path: Path, monkeypatch) -> None:
    tool = _load_tool()
    golden_root = tmp_path / "golden"
    workspace_root = tmp_path / "workspace"
    _write_review(golden_root / "alpha" / "alpha_page_review.json", "alpha")

    def write_match(book, _args, staging_root):
        _write_review(staging_root / book / f"{book}_page_review.json", book)

    monkeypatch.setattr(tool, "stage_page_review", write_match)

    report = tool.run_suite(_suite_args(tmp_path, golden_root, workspace_root))

    assert report["status"] == "pass"
    assert (workspace_root / "alpha" / "alpha_page_review.json").is_file()
    assert not (tmp_path / "staging" / "suite" / "alpha").exists()


def test_run_suite_reports_generation_failure_without_publishing(tmp_path: Path, monkeypatch) -> None:
    tool = _load_tool()
    golden_root = tmp_path / "golden"
    workspace_root = tmp_path / "workspace"
    _write_review(golden_root / "alpha" / "alpha_page_review.json", "alpha")
    old = workspace_root / "alpha"
    old.mkdir(parents=True)
    (old / "old.txt").write_text("old", encoding="utf-8")

    def fail_generation(*_args):
        raise tool.subprocess.CalledProcessError(7, ["mineru-page-review"])

    monkeypatch.setattr(tool, "stage_page_review", fail_generation)

    report = tool.run_suite(_suite_args(tmp_path, golden_root, workspace_root))

    assert report["status"] == "fail"
    assert report["books"] == [
        {
            "book": "alpha",
            "status": "fail",
            "error": "page_review_generation_failed: exit 7",
        }
    ]
    assert (workspace_root / "alpha" / "old.txt").is_file()


def test_runner_cli_forwards_repeated_book_selection(tmp_path: Path, monkeypatch) -> None:
    tool = _load_tool()
    received = {}

    def capture_args(args):
        received["args"] = args
        return {"status": "pass"}

    monkeypatch.setattr(tool, "run_suite", capture_args)

    exit_code = tool.main(
        [
            "--book",
            "alpha",
            "--book",
            "beta",
            "--golden-root",
            str(tmp_path / "golden"),
            "--mineru-root",
            str(tmp_path / "mineru"),
            "--samples-root",
            str(tmp_path / "samples"),
            "--workspace-root",
            str(tmp_path / "workspace"),
            "--run-id",
            "focused",
            "--no-skeleton-llm",
            "--no-llm",
        ]
    )

    assert exit_code == 0
    assert received["args"].book == ["alpha", "beta"]
    assert received["args"].run_id == "focused"
    assert received["args"].skeleton_llm is False
    assert received["args"].llm is False


def _write_review(path: Path, doc_id: str, *, special_page_kind: str = "front_exterior_page") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "metadata": {"doc_id": doc_id},
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
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _suite_args(tmp_path: Path, golden_root: Path, workspace_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        book=["alpha"],
        golden_root=golden_root,
        mineru_root=tmp_path / "mineru",
        samples_root=tmp_path / "samples",
        workspace_root=workspace_root,
        staging_root=tmp_path / "staging",
        run_id="suite",
        skeleton_llm=False,
        llm=False,
        llm_model="qwen-test",
        llm_api_url="http://test.invalid",
        llm_timeout_seconds=1,
    )
