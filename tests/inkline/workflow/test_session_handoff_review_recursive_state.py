from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from session_handoff_test_support import (
    GitContext,
    _git,
    _validate,
    _write_records,
    validator,
)


def _replace_round_body(context: GitContext, replacement: str) -> None:
    review_path = context.handoff_directory / "review.md"
    review_text = review_path.read_text(encoding="utf-8")
    body_round = f"### Round 1: `{context.candidate}`"
    prefix, separator, suffix = review_text.rpartition(body_round)
    assert separator
    review_path.write_text(
        prefix + replacement + suffix,
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "front_matter_comment",
    [
        "### Round 1: `{candidate}`",
        "### Round 1: candidate-without-backticks",
    ],
)
def test_front_matter_round_comment_cannot_supply_missing_body_round(
    git_context: GitContext,
    front_matter_comment: str,
) -> None:
    _write_records(git_context)
    review_path = git_context.handoff_directory / "review.md"
    review_text = review_path.read_text(encoding="utf-8").replace(
        "workflow_version: 2",
        "workflow_version: 2\n" + front_matter_comment.format(candidate=git_context.candidate),
        1,
    )
    review_path.write_text(review_text, encoding="utf-8")
    _replace_round_body(git_context, "No review round was recorded in the Markdown body.")

    errors = _validate(git_context)

    assert any("final_round" in error and "recorded review rounds" in error for error in errors)


@pytest.mark.parametrize(
    "front_matter_comment",
    [
        "### Round 99: `{candidate}`",
        "### Round 99: candidate-without-backticks",
    ],
)
def test_front_matter_round_comment_does_not_affect_valid_body_round(
    git_context: GitContext,
    front_matter_comment: str,
) -> None:
    _write_records(git_context)
    review_path = git_context.handoff_directory / "review.md"
    review_path.write_text(
        review_path.read_text(encoding="utf-8").replace(
            "workflow_version: 2",
            "workflow_version: 2\n" + front_matter_comment.format(candidate=git_context.candidate),
            1,
        ),
        encoding="utf-8",
    )

    assert _validate(git_context) == []


def _create_origin(path: Path, *, text: str = "initial\n") -> None:
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "workflow-test@example.invalid")
    _git(path, "config", "user.name", "Workflow Test")
    (path / "tracked.txt").write_text(text, encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-q", "-m", "test: initial content")


def _add_local_submodule(repository: Path, origin: Path, path: str) -> None:
    _git(
        repository,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(origin),
        path,
    )
    _git(repository, "commit", "-q", "-am", f"test: add {path} submodule")


def _context_at_current_head(context: GitContext) -> GitContext:
    return GitContext(
        repo=context.repo,
        handoff_directory=context.handoff_directory,
        prerequisite=context.candidate,
        candidate=_git(context.repo, "rev-parse", "HEAD"),
    )


def _direct_submodule_context(
    git_context: GitContext,
    tmp_path: Path,
) -> tuple[GitContext, Path]:
    origin = tmp_path / "direct-origin"
    _create_origin(origin)
    _add_local_submodule(git_context.repo, origin, "child-module")
    context = _context_at_current_head(git_context)
    _write_records(context)
    return context, context.repo / "child-module"


def _nested_submodule_context(
    git_context: GitContext,
    tmp_path: Path,
) -> tuple[GitContext, Path]:
    nested_origin = tmp_path / "nested-origin"
    _create_origin(nested_origin)
    direct_origin = tmp_path / "direct-origin"
    _create_origin(direct_origin)
    _add_local_submodule(direct_origin, nested_origin, "nested-module")
    _add_local_submodule(git_context.repo, direct_origin, "child-module")
    _git(
        git_context.repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "update",
        "-q",
        "--init",
        "--recursive",
    )
    context = _context_at_current_head(git_context)
    _write_records(context)
    return context, context.repo / "child-module" / "nested-module"


def test_complete_accepts_clean_populated_submodule(
    git_context: GitContext,
    tmp_path: Path,
) -> None:
    context, _child = _direct_submodule_context(git_context, tmp_path)

    assert _validate(context) == []


def test_complete_accepts_clean_nested_populated_submodule(
    git_context: GitContext,
    tmp_path: Path,
) -> None:
    context, _nested = _nested_submodule_context(git_context, tmp_path)

    assert _validate(context) == []


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_complete_rejects_index_flags_in_populated_submodule(
    git_context: GitContext,
    tmp_path: Path,
    index_flag: str,
) -> None:
    context, child = _direct_submodule_context(git_context, tmp_path)
    _git(child, "update-index", index_flag, "tracked.txt")

    errors = _validate(context)

    assert any("child-module" in error and "index flag" in error for error in errors)


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_complete_rejects_index_flags_in_nested_populated_submodule(
    git_context: GitContext,
    tmp_path: Path,
    index_flag: str,
) -> None:
    context, nested = _nested_submodule_context(git_context, tmp_path)
    _git(nested, "update-index", index_flag, "tracked.txt")

    errors = _validate(context)

    assert any("child-module/nested-module" in error and "index flag" in error for error in errors)


def test_complete_rejects_modified_file_in_populated_submodule(
    git_context: GitContext,
    tmp_path: Path,
) -> None:
    context, child = _direct_submodule_context(git_context, tmp_path)
    (child / "tracked.txt").write_text("modified\n", encoding="utf-8")

    errors = _validate(context)

    assert any(
        "child-module" in error and "tracked worktree and index" in error for error in errors
    )


def test_complete_does_not_descend_into_uninitialized_submodule(
    git_context: GitContext,
    tmp_path: Path,
) -> None:
    context, _child = _direct_submodule_context(git_context, tmp_path)
    _git(context.repo, "submodule", "deinit", "-q", "-f", "child-module")

    assert _validate(context) == []


def test_complete_fails_closed_when_populated_submodule_inspection_fails(
    git_context: GitContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, child = _direct_submodule_context(git_context, tmp_path)
    original_git = validator._git

    def failing_git(repo: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        if repo == child and arguments[:2] == ["status", "--porcelain"]:
            return subprocess.CompletedProcess([], 128, "", "forced inspection failure")
        return original_git(repo, arguments)

    monkeypatch.setattr(validator, "_git", failing_git)

    errors = _validate(context)

    assert any(
        "child-module" in error and "cannot inspect tracked worktree" in error for error in errors
    )
