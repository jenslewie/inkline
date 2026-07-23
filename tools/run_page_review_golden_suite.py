#!/usr/bin/env python3
"""Stage and golden-check PageReview artifacts before publishing them."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def discover_golden_books(golden_root: Path) -> list[str]:
    """Return complete golden PageReview book names in deterministic order."""

    if not golden_root.is_dir():
        raise ValueError(f"golden root does not exist: {golden_root}")
    return sorted(
        directory.name
        for directory in golden_root.iterdir()
        if directory.is_dir() and (directory / f"{directory.name}_page_review.json").is_file()
    )


def evaluate_staged_page_reviews(
    golden_root: Path, staging_root: Path, books: list[str]
) -> dict[str, Any]:
    """Compare every staged result with its golden stable page contract."""

    checker = _golden_checker()
    results: list[dict[str, Any]] = []
    for book in books:
        golden_path = golden_root / book / f"{book}_page_review.json"
        staged_path = staging_root / book / f"{book}_page_review.json"
        if not staged_path.is_file():
            results.append(
                {
                    "book": book,
                    "status": "fail",
                    "error": "missing_staged_page_review",
                }
            )
            continue
        report = checker(golden_path, staged_path)
        results.append({"book": book, "status": report["status"], "report": report})
    return {
        "status": "pass" if all(result["status"] == "pass" for result in results) else "fail",
        "books": results,
    }


def publish_staged_page_reviews(
    staging_root: Path,
    workspace_root: Path,
    books: list[str],
    *,
    report: dict[str, Any] | None = None,
) -> None:
    """Replace workspace book directories only after a passing suite report."""

    if report is not None and report.get("status") != "pass":
        raise ValueError("publishing requires a passing golden report")
    backup_root = staging_root / ".publish_backups"
    workspace_root.mkdir(parents=True, exist_ok=True)
    for book in books:
        staged_book = staging_root / book
        workspace_book = workspace_root / book
        backup_book = backup_root / book
        if not staged_book.is_dir():
            raise ValueError(f"missing staged book directory: {staged_book}")
        backup_book.parent.mkdir(parents=True, exist_ok=True)
        if backup_book.exists():
            shutil.rmtree(backup_book)
        if workspace_book.exists():
            workspace_book.rename(backup_book)
        try:
            staged_book.rename(workspace_book)
        except Exception:
            if backup_book.exists() and not workspace_book.exists():
                backup_book.rename(workspace_book)
            raise
        if backup_book.exists():
            shutil.rmtree(backup_book)


def stage_page_review(book: str, args: argparse.Namespace, staging_root: Path) -> None:
    """Invoke the established PageReview CLI with a book-local staging output."""

    raw_dir = args.mineru_root / book / "vlm"
    source_pdf = args.samples_root / f"{book}.pdf"
    output = staging_root / book / f"{book}_page_review.json"
    command = [
        "uv",
        "run",
        "--extra",
        "mineru",
        "mineru-page-review",
        "--content-list-v2",
        str(raw_dir / f"{book}_content_list_v2.json"),
        "--middle",
        str(raw_dir / f"{book}_middle.json"),
        "--source-pdf",
        str(source_pdf),
        "--doc-id",
        book,
        "--title",
        book,
        "--output",
        str(output),
        "--llm-model",
        args.llm_model,
        "--llm-api-url",
        args.llm_api_url,
        "--llm-timeout-seconds",
        str(args.llm_timeout_seconds),
    ]
    command.append("--skeleton-llm" if args.skeleton_llm else "--no-skeleton-llm")
    command.append("--llm" if args.llm else "--no-llm")
    subprocess.run(command, check=True)


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    """Stage every requested book, compare it, then publish only a green batch."""

    books = args.book or discover_golden_books(args.golden_root)
    unknown = sorted(set(books) - set(discover_golden_books(args.golden_root)))
    if unknown:
        raise ValueError(f"books lack golden PageReview artifacts: {unknown}")
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    staging_root = args.staging_root / run_id
    if staging_root.exists():
        raise ValueError(f"staging run already exists: {staging_root}")
    staging_root.mkdir(parents=True)

    generation_errors: dict[str, str] = {}
    for book in books:
        try:
            stage_page_review(book, args, staging_root)
        except subprocess.CalledProcessError as exc:
            generation_errors[book] = f"page_review_generation_failed: exit {exc.returncode}"

    report = evaluate_staged_page_reviews(args.golden_root, staging_root, books)
    for entry in report["books"]:
        book = entry["book"]
        if book in generation_errors:
            entry.clear()
            entry.update(
                {
                    "book": book,
                    "status": "fail",
                    "error": generation_errors[book],
                }
            )
    report["status"] = "pass" if all(item["status"] == "pass" for item in report["books"]) else "fail"
    report.update(
        {
            "golden_root": str(args.golden_root),
            "staging_root": str(staging_root),
            "workspace_root": str(args.workspace_root),
            "books_requested": books,
        }
    )
    _write_json(staging_root / "page_review_golden_report.json", report)
    if report["status"] == "pass":
        publish_staged_page_reviews(staging_root, args.workspace_root, books, report=report)
    return report


def main(argv: list[str] | None = None) -> int:
    """Run a focused or full PageReview golden suite."""

    args = _parser().parse_args(argv)
    args.golden_root = args.golden_root.resolve()
    args.mineru_root = args.mineru_root.resolve()
    args.samples_root = args.samples_root.resolve()
    args.workspace_root = args.workspace_root.resolve()
    args.staging_root = (args.staging_root or args.workspace_root / ".staging").resolve()
    report = run_suite(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", action="append", help="Golden book to evaluate; repeat for focused runs.")
    parser.add_argument(
        "--golden-root", type=Path, default=Path("data/outputs/golden/page-review")
    )
    parser.add_argument("--mineru-root", type=Path, default=Path("data/outputs/mineru"))
    parser.add_argument("--samples-root", type=Path, default=Path("data/samples"))
    parser.add_argument(
        "--workspace-root", type=Path, default=Path("data/outputs/workspace/page-review")
    )
    parser.add_argument("--staging-root", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--skeleton-llm", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--llm", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--llm-model", default="qwen3.6:35b-a3b")
    parser.add_argument("--llm-api-url", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--llm-timeout-seconds", type=int, default=300)
    return parser


def _golden_checker():
    path = Path(__file__).with_name("check_page_review_golden.py")
    spec = importlib.util.spec_from_file_location("check_page_review_golden", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load golden checker: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_page_review_golden


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
