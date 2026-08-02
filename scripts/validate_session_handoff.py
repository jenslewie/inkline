"""Validate a generated review-gated session handoff directory."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Sequence

PLACEHOLDER_PATTERN = re.compile(r"\{\{[^{}]+\}\}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


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
    return {agent_id.strip() for agent_id in value.split(",") if agent_id.strip()}


def _validate_commit(value: str, field: str, source: str, errors: list[str]) -> None:
    if value and COMMIT_PATTERN.fullmatch(value) is None:
        errors.append(f"{source}: {field} must be an exact 40-character lowercase commit id")


def _review_path(
    handoff_directory: Path,
    configured_path: str,
    errors: list[str],
) -> Path | None:
    if not configured_path:
        return None
    path = Path(configured_path)
    if not path.is_absolute():
        path = handoff_directory / path
    try:
        resolved = path.resolve()
        expected = (handoff_directory / "review.md").resolve()
    except OSError as error:
        errors.append(f"handoff.md: cannot resolve review_path: {error}")
        return None
    if resolved != expected:
        errors.append("handoff.md: review_path must resolve to review.md in the handoff directory")
        return None
    if not resolved.is_file():
        errors.append(f"review.md does not exist at {resolved}")
        return None
    return resolved


def _validate_complete_handoff(
    handoff_directory: Path,
    handoff: dict[str, str],
    errors: list[str],
    expected_commit: str | None,
) -> None:
    review_file = _review_path(
        handoff_directory,
        _require(handoff, "review_path", "handoff.md", errors),
        errors,
    )
    if review_file is None:
        return
    review = _front_matter(review_file, errors)

    handoff_fields = {
        field: _require(handoff, field, "handoff.md", errors)
        for field in (
            "task",
            "task_kind",
            "prerequisite_commit",
            "result_commit",
            "review_verdict",
            "approved_commit",
            "implementer_agent_ids",
            "root_agent_id",
        )
    }
    review_fields = {
        field: _require(review, field, "review.md", errors)
        for field in (
            "task",
            "task_kind",
            "verdict",
            "prerequisite_commit",
            "candidate_commit",
            "approved_commit",
            "implementer_agent_ids",
            "root_agent_id",
            "spec_reviewer_agent_id",
            "adversarial_reviewer_agent_id",
        )
    }

    _validate_matching_metadata(handoff_fields, review_fields, errors)
    result_commit = _validate_commit_identity(
        handoff_fields,
        review_fields,
        expected_commit,
        errors,
    )
    _validate_reviewer_identity(review_fields, errors)

    _validate_next_prompt(
        handoff_directory,
        handoff,
        review_file,
        result_commit,
        errors,
    )


def _validate_matching_metadata(
    handoff: dict[str, str],
    review: dict[str, str],
    errors: list[str],
) -> None:
    for field in ("task", "task_kind", "prerequisite_commit", "root_agent_id"):
        if handoff[field] != review[field]:
            errors.append(f"handoff.md and review.md {field} values must match")
    if _agent_ids(handoff["implementer_agent_ids"]) != _agent_ids(
        review["implementer_agent_ids"]
    ):
        errors.append("handoff.md and review.md implementer_agent_ids values must match")


def _validate_commit_identity(
    handoff: dict[str, str],
    review: dict[str, str],
    expected_commit: str | None,
    errors: list[str],
) -> str:
    for source, field, value in (
        ("handoff.md", "prerequisite_commit", handoff["prerequisite_commit"]),
        ("handoff.md", "result_commit", handoff["result_commit"]),
        ("handoff.md", "approved_commit", handoff["approved_commit"]),
        ("review.md", "candidate_commit", review["candidate_commit"]),
        ("review.md", "approved_commit", review["approved_commit"]),
    ):
        _validate_commit(value, field, source, errors)

    if handoff["review_verdict"] != "approved":
        errors.append("handoff.md: review_verdict must be 'approved' for status complete")
    if review["verdict"] != "approved":
        errors.append("review.md: verdict must be 'approved' for status complete")

    result_commit = handoff["result_commit"]
    if review["candidate_commit"] != result_commit:
        errors.append("review.md: candidate_commit must match handoff.md result_commit")
    if review["approved_commit"] != result_commit:
        errors.append("review.md: approved_commit must match handoff.md result_commit")
    if handoff["approved_commit"] != result_commit:
        errors.append("handoff.md: approved_commit must match result_commit")
    if expected_commit is not None and expected_commit != result_commit:
        errors.append("handoff.md: result_commit does not match the expected commit")
    return result_commit


def _validate_reviewer_identity(review: dict[str, str], errors: list[str]) -> None:
    implementers = _agent_ids(review["implementer_agent_ids"])
    root_agent = review["root_agent_id"]
    spec_reviewer = review["spec_reviewer_agent_id"]
    adversarial_reviewer = review["adversarial_reviewer_agent_id"]
    for field, reviewer in (
        ("spec_reviewer_agent_id", spec_reviewer),
        ("adversarial_reviewer_agent_id", adversarial_reviewer),
    ):
        if reviewer and reviewer in implementers:
            errors.append(f"review.md: {field} must be independent of every implementer")
        if reviewer and reviewer == root_agent:
            errors.append(f"review.md: {field} must be independent of the root orchestrator")

    task_kind = review["task_kind"]
    if task_kind not in {"code", "documentation"}:
        errors.append("review.md: task_kind must be 'code' or 'documentation'")
    if task_kind == "code" and spec_reviewer == adversarial_reviewer:
        errors.append("review.md: code tasks require distinct specification and adversarial reviewers")


def _validate_next_prompt(
    handoff_directory: Path,
    handoff: dict[str, str],
    review_file: Path,
    result_commit: str,
    errors: list[str],
) -> None:
    prompt_file = handoff_directory / "next-session-prompt.md"
    if not prompt_file.is_file():
        return
    prompt = _front_matter(prompt_file, errors)
    prompt_prerequisite = _require(
        prompt,
        "prerequisite_commit",
        "next-session-prompt.md",
        errors,
    )
    prompt_review_path = _require(prompt, "review_path", "next-session-prompt.md", errors)
    prompt_verdict = _require(prompt, "review_verdict", "next-session-prompt.md", errors)
    previous_task = _require(prompt, "previous_task", "next-session-prompt.md", errors)

    if prompt_prerequisite != result_commit:
        errors.append(
            "next-session-prompt.md: prerequisite_commit must match the approved result_commit"
        )
    if prompt_verdict != "approved":
        errors.append("next-session-prompt.md: review_verdict must be 'approved'")
    if previous_task != handoff.get("task", ""):
        errors.append("next-session-prompt.md: previous_task must match handoff.md task")

    configured_review = Path(prompt_review_path)
    if not configured_review.is_absolute():
        configured_review = handoff_directory / configured_review
    if configured_review.resolve() != review_file.resolve():
        errors.append("next-session-prompt.md: review_path must name the approved review.md")


def validate_handoff_directory(
    handoff_directory: Path,
    *,
    expected_commit: str | None = None,
) -> list[str]:
    """Return workflow contract violations for a generated handoff directory."""
    directory = handoff_directory.resolve()
    errors: list[str] = []
    if not directory.is_dir():
        return [f"handoff directory does not exist: {directory}"]

    markdown_files = sorted(directory.glob("*.md"))
    for path in markdown_files:
        if PLACEHOLDER_PATTERN.search(path.read_text(encoding="utf-8")):
            errors.append(f"{path.name}: unresolved placeholder")

    handoff_file = directory / "handoff.md"
    if not handoff_file.is_file():
        errors.append(f"handoff.md does not exist at {handoff_file}")
        return errors

    handoff = _front_matter(handoff_file, errors)
    status = _require(handoff, "status", "handoff.md", errors)
    if status == "complete":
        _validate_complete_handoff(directory, handoff, errors, expected_commit)
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    """Run the validator CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff_directory", type=Path)
    parser.add_argument("--expected-commit")
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
