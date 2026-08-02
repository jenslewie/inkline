"""Validate a generated review-gated session handoff directory."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Sequence

PLACEHOLDER_PATTERN = re.compile(r"\{\{[^{}]+\}\}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
TERMINAL_STATUSES = {"complete", "blocked", "superseded"}
TASK_KINDS = {"code", "documentation"}


def _front_matter(path: Path, errors: list[str]) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"{path.name}: cannot read file: {error}")
        return {}

    lines = text.splitlines()
    if not lines or lines[0] != "---":
        errors.append(f"{path.name}: missing YAML front matter")
        return {}
    try:
        closing_index = lines.index("---", 1)
    except ValueError:
        errors.append(f"{path.name}: unterminated YAML front matter")
        return {}

    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing_index], start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            errors.append(f"{path.name}:{line_number}: invalid front-matter scalar")
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key in metadata:
            errors.append(f"{path.name}:{line_number}: duplicate front-matter key {key!r}")
        metadata[key] = value
    return metadata


def _require(metadata: dict[str, str], field: str, source: str, errors: list[str]) -> str:
    value = metadata.get(field, "").strip()
    if not value:
        errors.append(f"{source}: required field {field!r} is missing or empty")
    return value


def _agent_ids(value: str) -> set[str]:
    if value.strip() == "none":
        return set()
    return {agent_id.strip() for agent_id in value.split(",") if agent_id.strip()}


def _record_file(directory: Path, name: str, *, required: bool, errors: list[str]) -> Path | None:
    path = directory / name
    if path.is_symlink():
        errors.append(f"{name}: workflow records must not be symbolic links")
        return None
    if not path.is_file():
        if required:
            errors.append(f"{name} is required but does not exist at {path}")
        return None
    return path


def _configured_record_path(
    directory: Path,
    configured: str,
    expected_name: str,
    source: str,
    errors: list[str],
) -> Path | None:
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute():
        path = directory / path
    expected = directory / expected_name
    try:
        if path.resolve() != expected.resolve():
            errors.append(f"{source}: path must name the current {expected_name}")
            return None
    except OSError as error:
        errors.append(f"{source}: cannot resolve path: {error}")
        return None
    return _record_file(directory, expected_name, required=True, errors=errors)


def _find_git_repository(directory: Path, errors: list[str]) -> Path | None:
    for candidate in (directory, *directory.parents):
        if (candidate / ".git").exists():
            return candidate
    errors.append("handoff directory is not inside a Git repository")
    return None


def _git(repo: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _validate_commit_syntax(value: str, field: str, source: str, errors: list[str]) -> bool:
    if COMMIT_PATTERN.fullmatch(value) is None:
        errors.append(f"{source}: {field} must be an exact 40-character lowercase commit id")
        return False
    return True


def _validate_git_commit(
    repo: Path, value: str, field: str, source: str, errors: list[str]
) -> bool:
    if not _validate_commit_syntax(value, field, source, errors):
        return False
    result = _git(repo, ["cat-file", "-e", f"{value}^{{commit}}"])
    if result.returncode != 0:
        errors.append(f"{source}: {field} does not name a commit in the repository")
        return False
    return True


def _validate_repository_state(
    directory: Path,
    prerequisite: str,
    result_commit: str,
    approved_commit: str | None,
    expected_commit: str | None,
    errors: list[str],
) -> None:
    if expected_commit is None:
        errors.append("expected_commit is required for terminal handoff validation")
        return
    repo = _find_git_repository(directory, errors)
    if repo is None:
        return
    prerequisite_valid = _validate_git_commit(
        repo, prerequisite, "prerequisite_commit", "handoff.md", errors
    )
    result_valid = _validate_git_commit(repo, result_commit, "result_commit", "handoff.md", errors)
    expected_valid = _validate_git_commit(
        repo, expected_commit, "expected_commit", "command line", errors
    )
    approved_valid = True
    if approved_commit is not None:
        approved_valid = _validate_git_commit(
            repo, approved_commit, "approved_commit", "handoff.md", errors
        )

    if result_commit != expected_commit:
        errors.append("handoff.md: result_commit does not match the expected commit")
    head_result = _git(repo, ["rev-parse", "HEAD"])
    if head_result.returncode != 0 or head_result.stdout.strip() != result_commit:
        errors.append("handoff.md: result_commit must equal the repository current HEAD")
    if prerequisite_valid and result_valid:
        ancestry = _git(repo, ["merge-base", "--is-ancestor", prerequisite, result_commit])
        if ancestry.returncode != 0:
            errors.append("handoff.md: prerequisite_commit must be an ancestor of result_commit")
    if expected_valid and result_valid and expected_commit != result_commit:
        errors.append("command line: expected_commit must equal result_commit")
    if approved_commit is not None and approved_valid and approved_commit != result_commit:
        errors.append("handoff.md: approved_commit must equal result_commit")


def _validate_task_kind(metadata: dict[str, str], source: str, errors: list[str]) -> str:
    task_kind = _require(metadata, "task_kind", source, errors)
    if task_kind and task_kind not in TASK_KINDS:
        errors.append(f"{source}: task_kind must be 'code' or 'documentation'")
    return task_kind


def _validate_agent_roles(metadata: dict[str, str], source: str, errors: list[str]) -> None:
    implementers = _agent_ids(_require(metadata, "implementer_agent_ids", source, errors))
    fixers = _agent_ids(_require(metadata, "fixer_agent_ids", source, errors))
    root = _require(metadata, "root_agent_id", source, errors)
    spec = _require(metadata, "spec_reviewer_agent_id", source, errors)
    adversarial = _require(metadata, "adversarial_reviewer_agent_id", source, errors)
    roles = {
        "implementers": implementers,
        "fixers": fixers,
        "root": {root} if root else set(),
        "spec reviewer": _agent_ids(spec),
        "adversarial reviewer": _agent_ids(adversarial),
    }
    role_items = list(roles.items())
    for index, (left_name, left_ids) in enumerate(role_items):
        for right_name, right_ids in role_items[index + 1 :]:
            overlap = left_ids & right_ids
            same_documentation_reviewer = metadata.get("task_kind") == "documentation" and {
                left_name,
                right_name,
            } == {"spec reviewer", "adversarial reviewer"}
            if overlap and not same_documentation_reviewer:
                errors.append(
                    f"{source}: agent roles must be mutually exclusive; "
                    f"{left_name} and {right_name} overlap: {', '.join(sorted(overlap))}"
                )


def _validate_matching_review_metadata(
    handoff: dict[str, str], review: dict[str, str], errors: list[str]
) -> None:
    scalar_fields = (
        "workflow_version",
        "task",
        "task_kind",
        "prerequisite_commit",
        "root_agent_id",
        "spec_reviewer_agent_id",
        "adversarial_reviewer_agent_id",
        "manual_gate",
    )
    for field in scalar_fields:
        if handoff.get(field) != review.get(field):
            errors.append(f"handoff.md and review.md {field} values must match")
    for field in ("implementer_agent_ids", "fixer_agent_ids"):
        if _agent_ids(handoff.get(field, "")) != _agent_ids(review.get(field, "")):
            errors.append(f"handoff.md and review.md {field} values must match")


def _positive_integer(value: str, field: str, source: str, errors: list[str]) -> int | None:
    try:
        number = int(value)
    except ValueError:
        errors.append(f"{source}: {field} must be an integer")
        return None
    if number < 1:
        errors.append(f"{source}: {field} must be at least 1")
        return None
    return number


def _validate_review_round_count(
    review_file: Path,
    review: dict[str, str],
    errors: list[str],
) -> None:
    final_round = _positive_integer(
        _require(review, "final_round", "review.md", errors),
        "final_round",
        "review.md",
        errors,
    )
    recorded_rounds = [
        int(match)
        for match in re.findall(
            r"^### Round ([1-9][0-9]*)(?::|$)",
            review_file.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    ]
    if final_round is not None and recorded_rounds != list(range(1, final_round + 1)):
        errors.append(
            "review.md: final_round must match contiguous recorded review rounds starting at 1"
        )


def _validate_final_review(
    review_file: Path,
    review: dict[str, str],
    candidate: str,
    errors: list[str],
) -> None:
    _validate_review_round_count(review_file, review, errors)
    for phase in ("spec", "adversarial"):
        commit_field = f"final_{phase}_reviewed_commit"
        verdict_field = f"final_{phase}_verdict"
        if _require(review, commit_field, "review.md", errors) != candidate:
            errors.append(f"review.md: {commit_field} must match candidate_commit")
        if _require(review, verdict_field, "review.md", errors) != "approved":
            errors.append(f"review.md: {verdict_field} must be 'approved'")
    unresolved = _require(review, "unresolved_blocking_count", "review.md", errors)
    if unresolved != "0":
        errors.append("review.md: unresolved_blocking_count must be 0")
    manual_gate = _require(review, "manual_gate", "review.md", errors)
    if manual_gate not in {"passed", "not_required"}:
        errors.append("review.md: manual_gate must be 'passed' or 'not_required'")


def _validate_complete(
    directory: Path,
    handoff: dict[str, str],
    expected_commit: str | None,
    errors: list[str],
) -> Path | None:
    required_handoff_fields = (
        "task",
        "prerequisite_commit",
        "result_commit",
        "review_verdict",
        "approved_commit",
        "terminal_reason",
    )
    for field in required_handoff_fields:
        _require(handoff, field, "handoff.md", errors)
    _validate_task_kind(handoff, "handoff.md", errors)
    _validate_agent_roles(handoff, "handoff.md", errors)
    if handoff.get("review_verdict") != "approved":
        errors.append("handoff.md: review_verdict must be 'approved' for status complete")
    if handoff.get("manual_gate") not in {"passed", "not_required"}:
        errors.append("handoff.md: manual_gate must be 'passed' or 'not_required'")

    review_file = _configured_record_path(
        directory,
        _require(handoff, "review_path", "handoff.md", errors),
        "review.md",
        "handoff.md: review_path",
        errors,
    )
    if review_file is None:
        return None
    review = _front_matter(review_file, errors)
    for field in (
        "workflow_version",
        "task",
        "task_kind",
        "verdict",
        "prerequisite_commit",
        "candidate_commit",
        "approved_commit",
        "implementer_agent_ids",
        "fixer_agent_ids",
        "root_agent_id",
        "spec_reviewer_agent_id",
        "adversarial_reviewer_agent_id",
    ):
        _require(review, field, "review.md", errors)
    _validate_task_kind(review, "review.md", errors)
    _validate_agent_roles(review, "review.md", errors)
    _validate_matching_review_metadata(handoff, review, errors)

    result_commit = handoff.get("result_commit", "")
    candidate = review.get("candidate_commit", "")
    if review.get("verdict") != "approved":
        errors.append("review.md: verdict must be 'approved' for status complete")
    for source, value in (
        ("handoff.md: approved_commit", handoff.get("approved_commit", "")),
        ("review.md: candidate_commit", candidate),
        ("review.md: approved_commit", review.get("approved_commit", "")),
    ):
        if value != result_commit:
            errors.append(f"{source} must match handoff.md result_commit")
    _validate_final_review(review_file, review, candidate, errors)
    _validate_repository_state(
        directory,
        handoff.get("prerequisite_commit", ""),
        result_commit,
        handoff.get("approved_commit", ""),
        expected_commit,
        errors,
    )
    return review_file


def _validate_nonapproved_terminal(
    directory: Path,
    handoff: dict[str, str],
    expected_commit: str | None,
    errors: list[str],
) -> Path | None:
    status = handoff.get("status", "")
    for field in ("task", "prerequisite_commit", "result_commit", "terminal_reason"):
        _require(handoff, field, "handoff.md", errors)
    _validate_task_kind(handoff, "handoff.md", errors)
    if handoff.get("approved_commit") != "none":
        errors.append(f"handoff.md: approved_commit must be 'none' for status {status}")
    if handoff.get("manual_gate") not in {"pending", "failed", "not_required"}:
        errors.append(
            f"handoff.md: manual_gate must be pending, failed, or not_required for status {status}"
        )
    if handoff.get("next_task") in {None, "", "none"}:
        errors.append(
            f"handoff.md: status {status} must name a recovery or diagnosis task in next_task"
        )
    _validate_repository_state(
        directory,
        handoff.get("prerequisite_commit", ""),
        handoff.get("result_commit", ""),
        None,
        expected_commit,
        errors,
    )
    if status == "superseded":
        _validate_no_review_terminal(handoff, "not_applicable", status, errors)
        return None
    review_verdict = handoff.get("review_verdict")
    if review_verdict == "not_run":
        _validate_no_review_terminal(handoff, "not_run", status, errors)
        return None
    if review_verdict == "changes_requested":
        return _validate_blocked_review(directory, handoff, errors)
    errors.append("handoff.md: blocked review_verdict must be 'not_run' or 'changes_requested'")
    return None


def _validate_no_review_terminal(
    handoff: dict[str, str],
    expected_verdict: str,
    status: str,
    errors: list[str],
) -> None:
    if handoff.get("review_path") != "none":
        errors.append(f"handoff.md: review_path must be 'none' for {expected_verdict}")
    if handoff.get("review_verdict") != expected_verdict:
        errors.append(
            f"handoff.md: review_verdict must be {expected_verdict!r} for status {status}"
        )
    for field in ("spec_reviewer_agent_id", "adversarial_reviewer_agent_id"):
        if handoff.get(field) != "none":
            errors.append(f"handoff.md: {field} must be 'none' for {expected_verdict}")
    _validate_agent_roles(handoff, "handoff.md", errors)


def _validate_blocked_review(
    directory: Path,
    handoff: dict[str, str],
    errors: list[str],
) -> Path | None:
    review_file = _configured_record_path(
        directory,
        _require(handoff, "review_path", "handoff.md", errors),
        "review.md",
        "handoff.md: changes_requested requires retained review.md",
        errors,
    )
    _validate_agent_roles(handoff, "handoff.md", errors)
    if review_file is None:
        errors.append("handoff.md: changes_requested requires retained review.md")
        return None
    review = _front_matter(review_file, errors)
    for field in (
        "workflow_version",
        "task",
        "task_kind",
        "verdict",
        "prerequisite_commit",
        "candidate_commit",
        "approved_commit",
        "implementer_agent_ids",
        "fixer_agent_ids",
        "root_agent_id",
        "spec_reviewer_agent_id",
        "adversarial_reviewer_agent_id",
        "final_spec_reviewed_commit",
        "final_spec_verdict",
        "final_adversarial_reviewed_commit",
        "final_adversarial_verdict",
        "unresolved_blocking_count",
        "manual_gate",
    ):
        _require(review, field, "review.md", errors)
    _validate_task_kind(review, "review.md", errors)
    _validate_agent_roles(review, "review.md", errors)
    _validate_matching_review_metadata(handoff, review, errors)
    _validate_review_round_count(review_file, review, errors)

    candidate = review.get("candidate_commit", "")
    if review.get("verdict") != "changes_requested":
        errors.append("review.md: verdict must be 'changes_requested' for blocked post-review")
    if candidate != handoff.get("result_commit"):
        errors.append("review.md: candidate_commit must match handoff.md result_commit")
    if review.get("approved_commit") != "none":
        errors.append("review.md: approved_commit must be 'none' for changes_requested")
    for phase in ("spec", "adversarial"):
        commit_field = f"final_{phase}_reviewed_commit"
        verdict_field = f"final_{phase}_verdict"
        if review.get(commit_field) != candidate:
            errors.append(f"review.md: {commit_field} must match candidate_commit")
        verdict = review.get(verdict_field, "")
        if verdict not in {"approved", "changes_requested"}:
            errors.append(f"review.md: {verdict_field} must be 'approved' or 'changes_requested'")
    _positive_integer(
        review.get("unresolved_blocking_count", ""),
        "unresolved_blocking_count",
        "review.md",
        errors,
    )
    return review_file


def _validate_next_prompt(
    directory: Path,
    handoff: dict[str, str],
    review_file: Path | None,
    errors: list[str],
) -> None:
    next_task = _require(handoff, "next_task", "handoff.md", errors)
    next_task_kind = _require(handoff, "next_task_kind", "handoff.md", errors)
    prompt_required = next_task != "none"
    if not prompt_required:
        if next_task_kind != "none":
            errors.append("handoff.md: next_task_kind must be 'none' when next_task is 'none'")
        _record_file(directory, "next-session-prompt.md", required=False, errors=errors)
        return
    if next_task_kind not in TASK_KINDS:
        errors.append("handoff.md: next_task_kind must be 'code' or 'documentation'")
    prompt_file = _record_file(directory, "next-session-prompt.md", required=True, errors=errors)
    if prompt_file is None:
        return
    prompt = _front_matter(prompt_file, errors)
    for field in (
        "workflow_version",
        "prompt_mode",
        "previous_task",
        "task",
        "task_kind",
        "handoff_path",
        "prerequisite_commit",
        "review_path",
        "review_verdict",
    ):
        _require(prompt, field, "next-session-prompt.md", errors)
    expected_mode = {
        "complete": "implementation",
        "blocked": "recovery",
        "superseded": "diagnosis",
    }[handoff["status"]]
    matching_fields = {
        "workflow_version": handoff.get("workflow_version", ""),
        "previous_task": handoff.get("task", ""),
        "task": next_task,
        "task_kind": next_task_kind,
        "prerequisite_commit": handoff.get("result_commit", ""),
        "review_path": handoff.get("review_path", ""),
        "review_verdict": handoff.get("review_verdict", ""),
        "prompt_mode": expected_mode,
    }
    for field, expected in matching_fields.items():
        if prompt.get(field) != expected:
            errors.append(f"next-session-prompt.md: {field} does not match handoff.md")
    _configured_record_path(
        directory,
        prompt.get("handoff_path", ""),
        "handoff.md",
        "next-session-prompt.md: handoff_path",
        errors,
    )
    if review_file is not None:
        _configured_record_path(
            directory,
            prompt.get("review_path", ""),
            "review.md",
            "next-session-prompt.md: review_path",
            errors,
        )


def validate_handoff_directory(
    handoff_directory: Path,
    *,
    expected_commit: str | None = None,
) -> list[str]:
    """Return workflow contract violations for one terminal handoff directory."""
    directory = handoff_directory.resolve()
    errors: list[str] = []
    if not directory.is_dir():
        return [f"handoff directory does not exist: {directory}"]

    for path in sorted(directory.glob("*.md")):
        if path.is_symlink():
            errors.append(f"{path.name}: workflow records must not be symbolic links")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"{path.name}: cannot read file: {error}")
            continue
        if PLACEHOLDER_PATTERN.search(text):
            errors.append(f"{path.name}: unresolved placeholder")

    handoff_file = _record_file(directory, "handoff.md", required=True, errors=errors)
    if handoff_file is None:
        return errors
    handoff = _front_matter(handoff_file, errors)
    if _require(handoff, "workflow_version", "handoff.md", errors) != "2":
        errors.append("handoff.md: workflow_version must be 2")
    status = _require(handoff, "status", "handoff.md", errors)
    if status not in TERMINAL_STATUSES:
        errors.append(
            "handoff.md: status must be a terminal status: complete, blocked, or superseded"
        )
        return errors

    review_file: Path | None = None
    if status == "complete":
        review_file = _validate_complete(directory, handoff, expected_commit, errors)
    else:
        review_file = _validate_nonapproved_terminal(directory, handoff, expected_commit, errors)
    _validate_next_prompt(directory, handoff, review_file, errors)
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    """Run the validator CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff_directory", type=Path)
    parser.add_argument("--expected-commit", required=True)
    arguments = parser.parse_args(argv)
    errors = validate_handoff_directory(
        arguments.handoff_directory,
        expected_commit=arguments.expected_commit,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {arguments.handoff_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
