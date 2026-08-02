"""Validate a generated review-gated session handoff directory."""

# pylint: disable=too-many-lines

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path
from typing import Sequence

import yaml
from yaml.events import AliasEvent, NodeEvent
from yaml.nodes import MappingNode, ScalarNode

PLACEHOLDER_PATTERN = re.compile(r"\{\{[^{}]+\}\}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
TERMINAL_STATUSES = {"complete", "blocked", "superseded"}
TASK_KINDS = {"code", "documentation"}
RUN_REVIEW_VERDICTS = {"approved", "changes_requested"}
UNRUN_REVIEW_VERDICTS = {"not_run", "unavailable"}
ROUND_HEADING_PATTERN = re.compile(r"### Round ([1-9][0-9]*): `([0-9a-f]{40})`")
AGENT_ID_PATTERN = re.compile(r"/?[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")
INTEGER_FRONT_MATTER_FIELDS = {
    "final_round",
    "unresolved_blocking_count",
    "workflow_version",
}


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

    front_matter = "\n".join(lines[1:closing_index])
    try:
        events = list(yaml.parse(front_matter, Loader=yaml.SafeLoader))
        root = yaml.compose(front_matter, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        problem_mark = getattr(error, "problem_mark", None)
        line_suffix = f":{problem_mark.line + 2}" if problem_mark is not None else ""
        errors.append(f"{path.name}{line_suffix}: invalid YAML front matter")
        return {}

    if root is None:
        return {}
    if not isinstance(root, MappingNode) or root.flow_style:
        errors.append(f"{path.name}: front matter must be a top-level block mapping")
        return {}

    for event in events:
        if isinstance(event, AliasEvent) or (
            isinstance(event, NodeEvent)
            and (event.anchor is not None or getattr(event, "tag", None) is not None)
        ):
            errors.append(
                f"{path.name}:{event.start_mark.line + 2}: "
                "front matter must not use YAML anchors, aliases, or explicit tags"
            )

    metadata: dict[str, str] = {}
    for key_node, value_node in root.value:
        line_number = key_node.start_mark.line + 2
        if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
            errors.append(
                f"{path.name}:{line_number}: front-matter keys must be top-level string scalars"
            )
            continue
        key = key_node.value
        if key in metadata:
            errors.append(f"{path.name}:{line_number}: duplicate front-matter key {key!r}")
            continue
        is_schema_integer = (
            isinstance(value_node, ScalarNode)
            and key in INTEGER_FRONT_MATTER_FIELDS
            and value_node.tag == "tag:yaml.org,2002:int"
            and re.fullmatch(r"[0-9]+", value_node.value) is not None
        )
        if (
            not isinstance(value_node, ScalarNode)
            or (value_node.tag != "tag:yaml.org,2002:str" and not is_schema_integer)
            or value_node.style in {"|", ">"}
            or value_node.start_mark.line != value_node.end_mark.line
        ):
            nesting_suffix = (
                "; nested mappings are invalid because front-matter fields must be top-level"
                if isinstance(value_node, MappingNode)
                else ""
            )
            errors.append(
                f"{path.name}:{value_node.start_mark.line + 2}: "
                f"front-matter field {key!r} must be a single-line string scalar"
                f"{nesting_suffix}"
            )
            continue
        metadata[key] = value_node.value
    return metadata


def _require(metadata: dict[str, str], field: str, source: str, errors: list[str]) -> str:
    value = metadata.get(field, "").strip()
    if not value:
        errors.append(f"{source}: required field {field!r} is missing or empty")
    return value


def _agent_ids(
    value: str,
    *,
    field: str | None = None,
    source: str | None = None,
    errors: list[str] | None = None,
) -> set[str]:
    stripped_value = value.strip()
    if stripped_value == "none":
        return set()
    agent_id_list = [agent_id.strip() for agent_id in stripped_value.split(",")]
    if any(not agent_id for agent_id in agent_id_list):
        if field is not None and source is not None and errors is not None:
            errors.append(
                f"{source}: {field} must be exactly 'none' or comma-separated non-empty agent ids"
            )
        return {agent_id for agent_id in agent_id_list if agent_id}
    if "none" in agent_id_list:
        if field is not None and source is not None and errors is not None:
            errors.append(
                f"{source}: 'none' must be the only value in {field}; "
                "agent ids cannot mix 'none' with real identities"
            )
        return {agent_id for agent_id in agent_id_list if agent_id != "none"}
    invalid_ids = [
        agent_id for agent_id in agent_id_list if AGENT_ID_PATTERN.fullmatch(agent_id) is None
    ]
    if invalid_ids and field is not None and source is not None and errors is not None:
        errors.append(
            f"{source}: {field} must contain valid agent identity tokens; "
            f"invalid: {', '.join(invalid_ids)}"
        )
    agent_ids = set(agent_id_list)
    if (
        len(agent_ids) != len(agent_id_list)
        and field is not None
        and source is not None
        and errors is not None
    ):
        errors.append(f"{source}: {field} agent ids must be unique")
    return agent_ids


def _list_agent_ids(
    metadata: dict[str, str],
    field: str,
    source: str,
    errors: list[str],
) -> set[str]:
    value = _require(metadata, field, source, errors)
    return _agent_ids(value, field=field, source=source, errors=errors)


def _single_agent_id(
    value: str,
    field: str,
    source: str,
    errors: list[str],
    *,
    allow_none: bool,
) -> set[str]:
    if "," in value:
        errors.append(f"{source}: {field} must contain a single agent id, not a list")
        return _agent_ids(value)
    if value == "none":
        if not allow_none:
            errors.append(f"{source}: {field} must identify a real agent, not 'none'")
        return set()
    if value and AGENT_ID_PATTERN.fullmatch(value) is None:
        errors.append(f"{source}: {field} must contain a valid agent identity token")
    return {value} if value else set()


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


def _require_record_absent(directory: Path, name: str, errors: list[str]) -> None:
    path = directory / name
    if path.exists() or path.is_symlink():
        errors.append(f"{name} must not exist for the declared terminal state")


def _configured_record_path(
    directory: Path,
    configured: str,
    expected_name: str,
    source: str,
    errors: list[str],
) -> Path | None:
    if not configured:
        return None
    expected = directory / expected_name
    if configured not in {expected_name, str(expected)}:
        errors.append(
            f"{source}: path must be the canonical {expected_name!r} basename or "
            "the current record's exact absolute lexical path"
        )
        return None
    return _record_file(directory, expected_name, required=True, errors=errors)


def _git(repo: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _validate_no_legacy_grafts(repo: Path, errors: list[str]) -> None:
    graft_path_result = _git(
        repo,
        ["rev-parse", "--path-format=absolute", "--git-path", "info/grafts"],
    )
    if graft_path_result.returncode != 0 or not graft_path_result.stdout.strip():
        errors.append("cannot inspect repository legacy graft metadata")
        return
    graft_path = Path(graft_path_result.stdout.strip())
    try:
        graft_path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        errors.append(f"cannot inspect repository legacy graft metadata: {error}")
        return
    errors.append(
        "repository legacy graft metadata must be absent before validating commit ancestry"
    )


def _validate_clean_tracked_state(repo: Path, errors: list[str]) -> None:
    status_result = _git(repo, ["status", "--porcelain", "--untracked-files=no"])
    if status_result.returncode != 0 or status_result.stdout.strip():
        errors.append("repository tracked worktree and index must be clean for status complete")
    flags_result = _git(repo, ["ls-files", "-v", "-z"])
    if flags_result.returncode != 0:
        errors.append("cannot inspect tracked index flags for status complete")
        return
    flagged = [
        entry
        for entry in flags_result.stdout.split("\0")
        if entry and (entry[0].islower() or entry[0].upper() == "S")
    ]
    if flagged:
        errors.append(
            "repository tracked index must not contain assume-unchanged or "
            "skip-worktree index flags for status complete"
        )


def _prepare_handoff_directory(
    handoff_directory: Path,
    errors: list[str],
) -> tuple[Path, Path] | None:
    raw_directory = handoff_directory.expanduser().absolute()
    if raw_directory.is_symlink():
        errors.append("handoff directory must not be a symbolic link")
        return None
    if not raw_directory.is_dir():
        errors.append(f"handoff directory does not exist: {raw_directory}")
        return None

    repository_result = _git(raw_directory, ["rev-parse", "--show-toplevel"])
    if repository_result.returncode != 0:
        errors.append("handoff directory is not inside a Git repository")
        return None
    repository = Path(repository_result.stdout.strip()).resolve()
    try:
        relative_directory = raw_directory.relative_to(repository)
    except ValueError:
        errors.append("handoff directory must be lexically inside its Git repository")
        return None

    current = repository
    for component in relative_directory.parts:
        current /= component
        if current.is_symlink():
            errors.append(
                "handoff directory has a repository-relative parent that is a symbolic link: "
                f"{current}"
            )
            return None

    required_root = repository / "docs" / "handovers" / "session-handoffs"
    if raw_directory.parent != required_root:
        errors.append(
            "terminal handoff directory must be a single direct child of "
            "docs/handovers/session-handoffs/"
        )
        return None
    try:
        raw_directory.relative_to(required_root)
    except ValueError:
        errors.append(
            "terminal handoff directory must be under the repository "
            "docs/handovers/session-handoffs/ directory"
        )
        return None
    resolved_directory = raw_directory.resolve()
    try:
        resolved_directory.relative_to(required_root.resolve())
    except ValueError:
        errors.append(
            "resolved terminal handoff directory must remain under docs/handovers/session-handoffs/"
        )
        return None
    return resolved_directory, repository


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
    result = _git(repo, ["cat-file", "-t", value])
    if result.returncode != 0 or result.stdout.strip() != "commit":
        errors.append(f"{source}: {field} does not name a commit object in the repository")
        return False
    return True


def _validate_repository_state(
    repo: Path,
    prerequisite: str,
    result_commit: str,
    approved_commit: str | None,
    expected_commit: str | None,
    declared_branch: str,
    require_clean: bool,
    errors: list[str],
) -> None:
    if expected_commit is None:
        errors.append("expected_commit is required for terminal handoff validation")
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
    branch_result = _git(repo, ["branch", "--show-current"])
    if branch_result.returncode != 0 or branch_result.stdout.strip() != declared_branch:
        errors.append("handoff.md: branch must match the repository current branch")
    if require_clean:
        _validate_clean_tracked_state(repo, errors)


def _validate_task_kind(metadata: dict[str, str], source: str, errors: list[str]) -> str:
    task_kind = _require(metadata, "task_kind", source, errors)
    if task_kind and task_kind not in TASK_KINDS:
        errors.append(f"{source}: task_kind must be 'code' or 'documentation'")
    return task_kind


def _validate_agent_roles(
    metadata: dict[str, str],
    source: str,
    errors: list[str],
    *,
    require_implementer: bool,
    phase_verdicts: dict[str, str] | None,
) -> None:
    implementers = _list_agent_ids(metadata, "implementer_agent_ids", source, errors)
    fixers = _list_agent_ids(metadata, "fixer_agent_ids", source, errors)
    root = _require(metadata, "root_agent_id", source, errors)
    spec = _require(metadata, "spec_reviewer_agent_id", source, errors)
    adversarial = _require(metadata, "adversarial_reviewer_agent_id", source, errors)
    if require_implementer and not implementers:
        errors.append(f"{source}: status complete requires at least one implementer agent id")

    reviewer_values = {"spec": spec, "adversarial": adversarial}
    reviewers: dict[str, set[str]] = {}
    for phase, value in reviewer_values.items():
        verdict = phase_verdicts.get(phase, "") if phase_verdicts is not None else ""
        allow_none = phase_verdicts is None or verdict in UNRUN_REVIEW_VERDICTS
        reviewers[phase] = _single_agent_id(
            value,
            f"{phase}_reviewer_agent_id",
            source,
            errors,
            allow_none=allow_none,
        )
        if phase_verdicts is not None:
            if verdict in RUN_REVIEW_VERDICTS and not reviewers[phase]:
                errors.append(
                    f"{source}: {phase} phase evidence requires a real {phase}_reviewer_agent_id"
                )
            if verdict in UNRUN_REVIEW_VERDICTS and value != "none":
                errors.append(f"{source}: {phase}_reviewer_agent_id must be 'none' for {verdict}")

    roles = {
        "implementers": implementers,
        "fixers": fixers,
        "root": _single_agent_id(
            root,
            "root_agent_id",
            source,
            errors,
            allow_none=False,
        ),
        "spec reviewer": reviewers["spec"],
        "adversarial reviewer": reviewers["adversarial"],
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


def _nonnegative_integer(value: str, field: str, source: str, errors: list[str]) -> int | None:
    try:
        number = int(value)
    except ValueError:
        errors.append(f"{source}: {field} must be an integer")
        return None
    if number < 0:
        errors.append(f"{source}: {field} must be at least 0")
        return None
    return number


def _unfenced_lines(text: str) -> list[str]:
    lines: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines():
        if fence_character is not None:
            closing_match = re.fullmatch(r" {0,3}(`+|~+)[\t ]*", line)
            if closing_match is not None:
                marker = closing_match.group(1)
                if marker[0] == fence_character and len(marker) >= fence_length:
                    fence_character = None
                    fence_length = 0
            continue
        opening_match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if opening_match is not None:
            marker = opening_match.group(1)
            info_string = opening_match.group(2)
            if marker[0] != "`" or "`" not in info_string:
                fence_character = marker[0]
                fence_length = len(marker)
                continue
        lines.append(line)
    return lines


def _validate_review_rounds(
    review_file: Path,
    review: dict[str, str],
    candidate: str,
    repo: Path,
    errors: list[str],
) -> None:
    final_round = _positive_integer(
        _require(review, "final_round", "review.md", errors),
        "final_round",
        "review.md",
        errors,
    )
    round_headings = [
        line
        for line in _unfenced_lines(review_file.read_text(encoding="utf-8"))
        if re.match(r"^ {0,3}###(?!#)[\t ]+Round(?:[\t ]|$)", line) is not None
    ]
    parsed_rounds: list[tuple[int, str]] = []
    commits_valid = True
    for heading in round_headings:
        match = ROUND_HEADING_PATTERN.fullmatch(heading)
        if match is None:
            errors.append(
                "review.md: review round headings must use canonical "
                "'### Round N: `<40-sha>`' syntax"
            )
            continue
        number = int(match.group(1))
        commit = match.group(2)
        parsed_rounds.append((number, commit))
        commits_valid = (
            _validate_git_commit(repo, commit, f"round_{number}_commit", "review.md", errors)
            and commits_valid
        )
    recorded_numbers = [number for number, _commit in parsed_rounds]
    if final_round is not None and recorded_numbers != list(range(1, final_round + 1)):
        errors.append(
            "review.md: final_round must match contiguous recorded review rounds "
            "using canonical headings and starting at 1"
        )
    if final_round is not None and parsed_rounds:
        final_heading_number, final_heading_commit = parsed_rounds[-1]
        if final_heading_number == final_round and final_heading_commit != candidate:
            errors.append("review.md: final review round commit must match candidate_commit")
    prerequisite = review.get("prerequisite_commit", "")
    prerequisite_is_commit = _git(repo, ["cat-file", "-t", prerequisite]).stdout.strip() == "commit"
    if commits_valid and prerequisite_is_commit:
        previous_commit = prerequisite
        previous_label = "prerequisite_commit"
        for number, commit in parsed_rounds:
            if _git(repo, ["merge-base", "--is-ancestor", previous_commit, commit]).returncode != 0:
                errors.append(
                    f"review.md: {previous_label} must be an ancestor of round {number} commit"
                )
            previous_commit = commit
            previous_label = f"round {number} commit"


def _validate_final_review(
    review_file: Path,
    review: dict[str, str],
    candidate: str,
    repo: Path,
    errors: list[str],
) -> None:
    _validate_review_rounds(review_file, review, candidate, repo, errors)
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


def _phase_verdicts(review: dict[str, str]) -> dict[str, str]:
    return {phase: review.get(f"final_{phase}_verdict", "") for phase in ("spec", "adversarial")}


def _validate_partial_phase_evidence(
    review: dict[str, str],
    candidate: str,
    errors: list[str],
) -> dict[str, str]:
    verdicts = _phase_verdicts(review)
    ran_phase = False
    for phase, verdict in verdicts.items():
        commit_field = f"final_{phase}_reviewed_commit"
        commit = review.get(commit_field, "")
        if verdict in RUN_REVIEW_VERDICTS:
            ran_phase = True
            if commit != candidate:
                errors.append(
                    f"review.md: {phase} phase evidence must name candidate_commit when run"
                )
        elif verdict in UNRUN_REVIEW_VERDICTS:
            if commit != "none":
                errors.append(
                    f"review.md: {phase} phase evidence commit must be 'none' for {verdict}"
                )
        else:
            errors.append(
                f"review.md: final_{phase}_verdict must be approved, changes_requested, "
                "not_run, or unavailable"
            )
    if not ran_phase:
        errors.append("review.md: at least one review phase must have run for post-review status")
    return verdicts


def _validate_complete(
    directory: Path,
    repo: Path,
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
    complete_verdicts = {"spec": "approved", "adversarial": "approved"}
    _validate_agent_roles(
        handoff,
        "handoff.md",
        errors,
        require_implementer=True,
        phase_verdicts=complete_verdicts,
    )
    if handoff.get("review_verdict") != "approved":
        errors.append("handoff.md: review_verdict must be 'approved' for status complete")
    if handoff.get("manual_gate") not in {"passed", "not_required"}:
        errors.append("handoff.md: manual_gate must be 'passed' or 'not_required'")
    if handoff.get("worktree_state") != "clean":
        errors.append("handoff.md: worktree_state must be 'clean' for status complete")

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
        "reviewed_at",
    ):
        _require(review, field, "review.md", errors)
    _validate_task_kind(review, "review.md", errors)
    _validate_agent_roles(
        review,
        "review.md",
        errors,
        require_implementer=True,
        phase_verdicts=complete_verdicts,
    )
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
    _validate_final_review(review_file, review, candidate, repo, errors)
    _validate_repository_state(
        repo,
        handoff.get("prerequisite_commit", ""),
        result_commit,
        handoff.get("approved_commit", ""),
        expected_commit,
        handoff.get("branch", ""),
        True,
        errors,
    )
    return review_file


def _validate_nonapproved_terminal(
    directory: Path,
    repo: Path,
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
        repo,
        handoff.get("prerequisite_commit", ""),
        handoff.get("result_commit", ""),
        None,
        expected_commit,
        handoff.get("branch", ""),
        False,
        errors,
    )
    if status == "superseded":
        if handoff.get("review_verdict") == "not_applicable":
            _validate_no_review_terminal(directory, handoff, "not_applicable", status, errors)
            return None
        if handoff.get("review_verdict") == "superseded":
            return _validate_post_review_terminal(directory, repo, handoff, "superseded", errors)
        errors.append(
            "handoff.md: superseded review_verdict must be 'not_applicable' or 'superseded'"
        )
        return None
    review_verdict = handoff.get("review_verdict")
    if review_verdict == "not_run":
        _validate_no_review_terminal(directory, handoff, "not_run", status, errors)
        return None
    if review_verdict == "changes_requested":
        return _validate_post_review_terminal(
            directory,
            repo,
            handoff,
            "changes_requested",
            errors,
        )
    errors.append("handoff.md: blocked review_verdict must be 'not_run' or 'changes_requested'")
    return None


def _validate_no_review_terminal(
    directory: Path,
    handoff: dict[str, str],
    expected_verdict: str,
    status: str,
    errors: list[str],
) -> None:
    if handoff.get("review_path") != "none":
        errors.append(f"handoff.md: review_path must be 'none' for {expected_verdict}")
    else:
        _require_record_absent(directory, "review.md", errors)
    if handoff.get("review_verdict") != expected_verdict:
        errors.append(
            f"handoff.md: review_verdict must be {expected_verdict!r} for status {status}"
        )
    for field in ("spec_reviewer_agent_id", "adversarial_reviewer_agent_id"):
        if handoff.get(field) != "none":
            errors.append(f"handoff.md: {field} must be 'none' for {expected_verdict}")
    if handoff.get("fixer_agent_ids") != "none":
        errors.append(f"handoff.md: fixer_agent_ids must be 'none' for {expected_verdict}")
    _validate_agent_roles(
        handoff,
        "handoff.md",
        errors,
        require_implementer=False,
        phase_verdicts={"spec": "not_run", "adversarial": "not_run"},
    )


def _validate_post_review_terminal(
    directory: Path,
    repo: Path,
    handoff: dict[str, str],
    expected_verdict: str,
    errors: list[str],
) -> Path | None:
    review_file = _configured_record_path(
        directory,
        _require(handoff, "review_path", "handoff.md", errors),
        "review.md",
        "handoff.md: changes_requested requires retained review.md",
        errors,
    )
    if review_file is None:
        errors.append("handoff.md: post-review terminal status requires retained review.md")
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
        "reviewed_at",
    ):
        _require(review, field, "review.md", errors)
    _validate_task_kind(review, "review.md", errors)
    _validate_matching_review_metadata(handoff, review, errors)

    candidate = review.get("candidate_commit", "")
    if review.get("verdict") != expected_verdict:
        errors.append(
            f"review.md: verdict must be {expected_verdict!r} for this post-review terminal state"
        )
    if candidate != handoff.get("result_commit"):
        errors.append("review.md: candidate_commit must match handoff.md result_commit")
    if review.get("approved_commit") != "none":
        errors.append("review.md: approved_commit must be 'none' for changes_requested")
    phase_verdicts = _validate_partial_phase_evidence(review, candidate, errors)
    _validate_agent_roles(
        handoff,
        "handoff.md",
        errors,
        require_implementer=False,
        phase_verdicts=phase_verdicts,
    )
    _validate_agent_roles(
        review,
        "review.md",
        errors,
        require_implementer=False,
        phase_verdicts=phase_verdicts,
    )
    _validate_review_rounds(review_file, review, candidate, repo, errors)
    if expected_verdict == "changes_requested":
        _positive_integer(
            review.get("unresolved_blocking_count", ""),
            "unresolved_blocking_count",
            "review.md",
            errors,
        )
    else:
        _nonnegative_integer(
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
        _require_record_absent(directory, "next-session-prompt.md", errors)
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
    errors: list[str] = []
    prepared = _prepare_handoff_directory(handoff_directory, errors)
    if prepared is None:
        return errors
    directory, repo = prepared
    _validate_no_legacy_grafts(repo, errors)

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
    _require_record_absent(directory, "review-session-prompt.md", errors)
    handoff = _front_matter(handoff_file, errors)
    if _require(handoff, "workflow_version", "handoff.md", errors) != "2":
        errors.append("handoff.md: workflow_version must be 2")
    status = _require(handoff, "status", "handoff.md", errors)
    if status not in TERMINAL_STATUSES:
        errors.append(
            "handoff.md: status must be a terminal status: complete, blocked, or superseded"
        )
        return errors
    for field in ("branch", "worktree_state", "generated_at"):
        _require(handoff, field, "handoff.md", errors)

    review_file: Path | None = None
    if status == "complete":
        review_file = _validate_complete(directory, repo, handoff, expected_commit, errors)
    else:
        review_file = _validate_nonapproved_terminal(
            directory,
            repo,
            handoff,
            expected_commit,
            errors,
        )
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
