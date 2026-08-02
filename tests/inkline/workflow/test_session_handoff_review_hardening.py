from __future__ import annotations

from pathlib import Path

import pytest
from session_handoff_test_support import (
    GitContext,
    _git,
    _validate,
    _write_next_prompt,
    _write_records,
)


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_complete_rejects_hidden_tracked_index_flags(
    git_context: GitContext,
    index_flag: str,
) -> None:
    _write_records(git_context)
    _git(git_context.repo, "update-index", index_flag, "tracked.txt")

    errors = _validate(git_context)

    assert any("index flag" in error for error in errors)


def test_complete_with_ordinary_clean_index_still_ignores_local_files(
    git_context: GitContext,
) -> None:
    _write_records(git_context)
    (git_context.repo / "ordinary-untracked.txt").write_text("local\n", encoding="utf-8")
    (git_context.repo / ".git" / "info" / "exclude").write_text(
        "ignored-local.txt\n",
        encoding="utf-8",
    )
    (git_context.repo / "ignored-local.txt").write_text("ignored\n", encoding="utf-8")

    assert _validate(git_context) == []


def test_complete_rejects_dirty_submodule_hidden_by_repository_config(
    git_context: GitContext,
) -> None:
    submodule_origin = git_context.repo.parent / "submodule-origin"
    submodule_origin.mkdir()
    _git(submodule_origin, "init", "-q", "-b", "main")
    _git(submodule_origin, "config", "user.email", "workflow-test@example.invalid")
    _git(submodule_origin, "config", "user.name", "Workflow Test")
    submodule_file = submodule_origin / "tracked.txt"
    submodule_file.write_text("first\n", encoding="utf-8")
    _git(submodule_origin, "add", "tracked.txt")
    _git(submodule_origin, "commit", "-q", "-m", "test: first submodule commit")

    _git(
        git_context.repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(submodule_origin),
        "child-module",
    )
    _git(git_context.repo, "commit", "-q", "-am", "test: add submodule")
    parent_candidate = _git(git_context.repo, "rev-parse", "HEAD")
    submodule_context = GitContext(
        repo=git_context.repo,
        handoff_directory=git_context.handoff_directory,
        prerequisite=git_context.candidate,
        candidate=parent_candidate,
    )
    _write_records(submodule_context)

    submodule_file.write_text("second\n", encoding="utf-8")
    _git(submodule_origin, "add", "tracked.txt")
    _git(submodule_origin, "commit", "-q", "-m", "test: second submodule commit")
    child_checkout = git_context.repo / "child-module"
    _git(child_checkout, "fetch", "-q", "origin")
    _git(child_checkout, "checkout", "-q", _git(submodule_origin, "rev-parse", "HEAD"))
    _git(git_context.repo, "config", "submodule.child-module.ignore", "all")

    errors = _validate(submodule_context)

    assert any("tracked worktree and index must be clean" in error for error in errors)


def test_complete_ignores_hostile_git_index_file_environment(
    git_context: GitContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_records(git_context)
    clean_index = tmp_path / "clean-index"
    clean_index.write_bytes((git_context.repo / ".git" / "index").read_bytes())
    tracked = git_context.repo / "tracked.txt"
    tracked.write_text("staged but hidden\n", encoding="utf-8")
    _git(git_context.repo, "add", "tracked.txt")
    tracked.write_text("candidate\n", encoding="utf-8")
    monkeypatch.setenv("GIT_INDEX_FILE", str(clean_index))

    errors = _validate(git_context)

    assert any("tracked worktree and index must be clean" in error for error in errors)


def test_complete_ignores_hostile_git_repository_environment(
    git_context: GitContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    foreign_repo = tmp_path / "foreign-repo"
    foreign_repo.mkdir()
    _git(foreign_repo, "init", "-q", "-b", "main")
    _git(foreign_repo, "config", "user.email", "workflow-test@example.invalid")
    _git(foreign_repo, "config", "user.name", "Workflow Test")
    foreign_tracked = foreign_repo / "tracked.txt"
    foreign_tracked.write_text("prerequisite\n", encoding="utf-8")
    _git(foreign_repo, "add", "tracked.txt")
    _git(foreign_repo, "commit", "-q", "-m", "test: foreign prerequisite")
    foreign_prerequisite = _git(foreign_repo, "rev-parse", "HEAD")
    foreign_tracked.write_text("candidate\n", encoding="utf-8")
    _git(foreign_repo, "add", "tracked.txt")
    _git(foreign_repo, "commit", "-q", "-m", "test: foreign candidate")
    foreign_candidate = _git(foreign_repo, "rev-parse", "HEAD")
    _write_records(
        git_context,
        prerequisite=foreign_prerequisite,
        result_commit=foreign_candidate,
        handoff_approved_commit=foreign_candidate,
        review_candidate=foreign_candidate,
        review_approved_commit=foreign_candidate,
        final_spec_commit=foreign_candidate,
        final_adversarial_commit=foreign_candidate,
    )
    monkeypatch.setenv("GIT_DIR", str(foreign_repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(git_context.repo))

    errors = _validate(git_context, expected_commit=foreign_candidate)

    assert any("does not name a commit object" in error for error in errors)


def test_complete_ignores_git_config_environment_injection(
    git_context: GitContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_records(git_context)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "not-an-integer")

    assert _validate(git_context) == []


@pytest.mark.parametrize(
    "review_path",
    [
        "./review.md",
        "nested/../review.md",
        "review-alias.md",
    ],
)
def test_rejects_noncanonical_relative_review_path(
    git_context: GitContext,
    review_path: str,
) -> None:
    _write_records(git_context, review_path=review_path)
    if review_path == "review-alias.md":
        (git_context.handoff_directory / review_path).symlink_to("review.md")

    errors = _validate(git_context)

    assert any("review_path" in error and "canonical" in error for error in errors)


def test_rejects_noncanonical_absolute_review_path(git_context: GitContext) -> None:
    aliased_path = git_context.handoff_directory / "nested" / ".." / "review.md"
    _write_records(git_context, review_path=str(aliased_path))

    errors = _validate(git_context)

    assert any("review_path" in error and "canonical" in error for error in errors)


@pytest.mark.parametrize(
    ("field", "canonical_value"),
    [
        ("workflow_version", "2"),
        ("task_kind", "code"),
        ("root_agent_id", "root-agent-1"),
    ],
)
def test_rejects_surrounding_whitespace_in_matching_handoff_and_review_machine_fields(
    git_context: GitContext,
    field: str,
    canonical_value: str,
) -> None:
    _write_records(git_context)
    for record_name in ("handoff.md", "review.md"):
        record = git_context.handoff_directory / record_name
        original = (
            "workflow_version: 2"
            if field == "workflow_version"
            else f'{field}: "{canonical_value}"'
        )
        record.write_text(
            record.read_text(encoding="utf-8").replace(
                original,
                f'{field}: " {canonical_value} "',
            ),
            encoding="utf-8",
        )

    errors = _validate(git_context)

    assert any(
        record_name in error and field in error and "surrounding whitespace" in error
        for record_name in ("handoff.md", "review.md")
        for error in errors
    )


@pytest.mark.parametrize(
    ("field", "canonical_value"),
    [
        ("status", "complete"),
        ("review_path", "review.md"),
    ],
)
def test_rejects_surrounding_whitespace_in_handoff_machine_fields(
    git_context: GitContext,
    field: str,
    canonical_value: str,
) -> None:
    _write_records(git_context)
    handoff = git_context.handoff_directory / "handoff.md"
    handoff.write_text(
        handoff.read_text(encoding="utf-8").replace(
            f'{field}: "{canonical_value}"',
            f'{field}: " {canonical_value} "',
        ),
        encoding="utf-8",
    )

    errors = _validate(git_context)

    assert any(field in error and "surrounding whitespace" in error for error in errors)


def test_rejects_surrounding_whitespace_in_next_prompt_machine_field(
    git_context: GitContext,
) -> None:
    _write_records(git_context, next_task="next bounded task", next_task_kind="code")
    _write_next_prompt(
        git_context,
        prompt_mode=" implementation ",
    )

    errors = _validate(git_context)

    assert any(
        "next-session-prompt.md" in error
        and "prompt_mode" in error
        and "surrounding whitespace" in error
        for error in errors
    )


@pytest.mark.parametrize("status", ["blocked", "superseded"])
@pytest.mark.parametrize("padded_none", [" none ", "\tnone\t", "\u00a0none\u00a0"])
def test_pre_review_terminal_rejects_padded_none_as_missing_recovery_task(
    git_context: GitContext,
    status: str,
    padded_none: str,
) -> None:
    verdict = "not_run" if status == "blocked" else "not_applicable"
    _write_records(
        git_context,
        status=status,
        handoff_approved_commit="none",
        handoff_verdict=verdict,
        review_path="none",
        handoff_fixers="none",
        handoff_spec_reviewer="none",
        handoff_adversarial_reviewer="none",
        terminal_reason="pre_review_terminal",
        next_task=padded_none,
        next_task_kind=padded_none,
    )
    (git_context.handoff_directory / "review.md").unlink()

    errors = _validate(git_context)

    assert any("must name a recovery or diagnosis task" in error for error in errors)


@pytest.mark.parametrize("status", ["blocked", "superseded"])
def test_post_review_terminal_rejects_padded_none_as_missing_recovery_task(
    git_context: GitContext,
    status: str,
) -> None:
    verdict = "changes_requested" if status == "blocked" else "superseded"
    _write_records(
        git_context,
        status=status,
        handoff_approved_commit="none",
        handoff_verdict=verdict,
        review_approved_commit="none",
        review_verdict=verdict,
        final_spec_verdict="changes_requested" if status == "blocked" else "approved",
        unresolved_blocking_count="1" if status == "blocked" else "0",
        manual_gate="pending" if status == "blocked" else "not_required",
        terminal_reason="post_review_terminal",
        next_task=" none ",
        next_task_kind=" none ",
    )

    errors = _validate(git_context)

    assert any("must name a recovery or diagnosis task" in error for error in errors)


def test_agent_lists_explicitly_allow_whitespace_after_commas(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        handoff_implementers="implementer-1, implementer-2",
        review_implementers="implementer-2, implementer-1",
    )

    assert _validate(git_context) == []


def test_rejects_outside_symlink_alias_to_current_review(git_context: GitContext) -> None:
    outside_alias = git_context.handoff_directory.parent / "review-alias.md"
    outside_alias.symlink_to(git_context.handoff_directory / "review.md")
    _write_records(git_context, review_path=str(outside_alias))

    errors = _validate(git_context)

    assert any("review_path" in error and "canonical" in error for error in errors)


@pytest.mark.parametrize("handoff_path", ["./handoff.md", "nested/../handoff.md"])
def test_rejects_noncanonical_handoff_path(
    git_context: GitContext,
    handoff_path: str,
) -> None:
    _write_records(git_context, next_task="next bounded task", next_task_kind="code")
    _write_next_prompt(git_context, handoff_path=handoff_path)

    errors = _validate(git_context)

    assert any("handoff_path" in error and "canonical" in error for error in errors)


def test_accepts_exact_absolute_record_paths(git_context: GitContext) -> None:
    review_path = str(git_context.handoff_directory / "review.md")
    handoff_path = str(git_context.handoff_directory / "handoff.md")
    _write_records(
        git_context,
        review_path=review_path,
        next_task="next bounded task",
        next_task_kind="code",
    )
    _write_next_prompt(
        git_context,
        handoff_path=handoff_path,
        review_path=review_path,
    )

    assert _validate(git_context) == []


@pytest.mark.parametrize("indent", [" ", "  ", "   "])
def test_rejects_space_indented_unfenced_round_heading_candidate(
    git_context: GitContext,
    indent: str,
) -> None:
    _write_records(
        git_context,
        rounds_text=(
            f"### Round 1: `{git_context.candidate}`\n\n"
            f"{indent}### Round 2: `{git_context.candidate}`"
        ),
    )

    errors = _validate(git_context)

    assert any("review round headings" in error for error in errors)


@pytest.mark.parametrize("heading_separator", ["\t", "  "])
def test_rejects_noncanonical_commonmark_round_heading_whitespace(
    git_context: GitContext,
    heading_separator: str,
) -> None:
    _write_records(
        git_context,
        rounds_text=(
            f"### Round 1: `{git_context.candidate}`\n\n"
            f"###{heading_separator}Round 2: `{git_context.candidate}`"
        ),
    )

    errors = _validate(git_context)

    assert any("review round headings" in error for error in errors)


def test_ignores_four_space_indented_round_heading_candidate(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        rounds_text=(
            f"    ### Round 99: `{git_context.prerequisite}`\n\n"
            f"### Round 1: `{git_context.candidate}`"
        ),
    )

    assert _validate(git_context) == []


def test_rejects_review_round_commit_from_side_branch(git_context: GitContext) -> None:
    _git(git_context.repo, "switch", "-q", "-c", "review-side", git_context.prerequisite)
    (git_context.repo / "tracked.txt").write_text("side\n", encoding="utf-8")
    _git(git_context.repo, "add", "tracked.txt")
    _git(git_context.repo, "commit", "-q", "-m", "test: side candidate")
    side_commit = _git(git_context.repo, "rev-parse", "HEAD")
    _git(git_context.repo, "switch", "-q", "main")
    _write_records(
        git_context,
        final_round="2",
        rounds_text=(f"### Round 1: `{side_commit}`\n\n### Round 2: `{git_context.candidate}`"),
    )

    errors = _validate(git_context)

    assert any("ancestor" in error and "round" in error for error in errors)


def test_rejects_review_round_before_prerequisite(git_context: GitContext) -> None:
    tree = _git(git_context.repo, "rev-parse", f"{git_context.prerequisite}^{{tree}}")
    unrelated_commit = _git(
        git_context.repo,
        "commit-tree",
        tree,
        "-m",
        "test: unrelated review candidate",
    )
    _write_records(
        git_context,
        final_round="2",
        rounds_text=(
            f"### Round 1: `{unrelated_commit}`\n\n### Round 2: `{git_context.candidate}`"
        ),
    )

    errors = _validate(git_context)

    assert any("prerequisite_commit" in error and "round 1" in error for error in errors)


def test_rejects_ancestry_fabricated_by_replace_ref(git_context: GitContext) -> None:
    tree = _git(git_context.repo, "rev-parse", f"{git_context.candidate}^{{tree}}")
    unrelated_prerequisite = _git(
        git_context.repo,
        "commit-tree",
        tree,
        "-m",
        "test: unrelated prerequisite",
    )
    replacement_commit = _git(
        git_context.repo,
        "commit-tree",
        tree,
        "-p",
        unrelated_prerequisite,
        "-m",
        "test: replacement candidate",
    )
    _git(git_context.repo, "replace", git_context.candidate, replacement_commit)
    _write_records(git_context, prerequisite=unrelated_prerequisite)

    errors = _validate(git_context)

    assert any("prerequisite_commit" in error and "ancestor" in error for error in errors)


def test_rejects_ancestry_fabricated_by_legacy_graft(git_context: GitContext) -> None:
    tree = _git(git_context.repo, "rev-parse", f"{git_context.candidate}^{{tree}}")
    unrelated_prerequisite = _git(
        git_context.repo,
        "commit-tree",
        tree,
        "-m",
        "test: unrelated prerequisite",
    )
    grafts = git_context.repo / ".git" / "info" / "grafts"
    grafts.write_text(
        f"{git_context.candidate} {unrelated_prerequisite}\n",
        encoding="utf-8",
    )
    _write_records(git_context, prerequisite=unrelated_prerequisite)

    errors = _validate(git_context)

    assert any("graft" in error for error in errors)


def test_rejects_legacy_graft_in_linked_worktree_common_dir(
    git_context: GitContext,
    tmp_path: Path,
) -> None:
    linked_repo = tmp_path / "linked-repo"
    _git(
        git_context.repo,
        "worktree",
        "add",
        "-q",
        "-b",
        "linked-review",
        str(linked_repo),
        git_context.candidate,
    )
    linked_context = GitContext(
        linked_repo,
        linked_repo / "docs" / "handovers" / "session-handoffs" / "run",
        git_context.prerequisite,
        git_context.candidate,
    )
    linked_context.handoff_directory.mkdir(parents=True)
    tree = _git(linked_repo, "rev-parse", f"{git_context.candidate}^{{tree}}")
    unrelated_prerequisite = _git(
        linked_repo,
        "commit-tree",
        tree,
        "-m",
        "test: unrelated prerequisite",
    )
    grafts = git_context.repo / ".git" / "info" / "grafts"
    grafts.write_text(
        f"{git_context.candidate} {unrelated_prerequisite}\n",
        encoding="utf-8",
    )
    _write_records(
        linked_context,
        prerequisite=unrelated_prerequisite,
        branch="linked-review",
    )

    errors = _validate(linked_context)

    assert any("graft" in error for error in errors)


def test_rejects_required_metadata_nested_under_yaml_mapping(
    git_context: GitContext,
) -> None:
    _write_records(git_context)
    for record_name in ("handoff.md", "review.md"):
        record = git_context.handoff_directory / record_name
        text = record.read_text(encoding="utf-8")
        record.write_text(
            text.replace(
                'root_agent_id: "root-agent-1"',
                'agents:\n  root_agent_id: "root-agent-1"',
            ),
            encoding="utf-8",
        )

    errors = _validate(git_context)

    assert any("top-level" in error for error in errors)


def test_rejects_duplicate_semantic_front_matter_key(
    git_context: GitContext,
) -> None:
    _write_records(git_context)
    handoff = git_context.handoff_directory / "handoff.md"
    handoff.write_text(
        handoff.read_text(encoding="utf-8").replace(
            'status: "complete"',
            'status: "complete"\n"status": "blocked"',
        ),
        encoding="utf-8",
    )

    errors = _validate(git_context)

    assert any("duplicate front-matter key 'status'" in error for error in errors)


def test_accepts_quoted_front_matter_key_with_same_yaml_semantics(
    git_context: GitContext,
) -> None:
    _write_records(git_context)
    for record_name in ("handoff.md", "review.md"):
        record = git_context.handoff_directory / record_name
        record.write_text(
            record.read_text(encoding="utf-8").replace(
                'task: "workflow gate"',
                '"task": "workflow gate"',
            ),
            encoding="utf-8",
        )

    assert _validate(git_context) == []


def test_rejects_yaml_escaped_placeholder_in_matching_record_metadata(
    git_context: GitContext,
) -> None:
    _write_records(git_context)
    escaped_placeholder = r"\u007b\u007bTASK_NAME\u007d\u007d"
    for record_name in ("handoff.md", "review.md"):
        record = git_context.handoff_directory / record_name
        record.write_text(
            record.read_text(encoding="utf-8").replace(
                'task: "workflow gate"',
                f'task: "{escaped_placeholder}"',
            ),
            encoding="utf-8",
        )

    errors = _validate(git_context)

    assert all(
        any(
            record_name in error and "unresolved placeholder" in error and "task" in error
            for error in errors
        )
        for record_name in ("handoff.md", "review.md")
    )


def test_rejects_yaml_escaped_placeholder_in_successor_prompt_metadata(
    git_context: GitContext,
) -> None:
    escaped_placeholder = r"\u007b\u007bNEXT_TASK\u007d\u007d"
    _write_records(
        git_context,
        next_task=escaped_placeholder,
        next_task_kind="code",
    )
    _write_next_prompt(git_context, task=escaped_placeholder)

    errors = _validate(git_context)

    assert any(
        "next-session-prompt.md" in error and "unresolved placeholder" in error and "task" in error
        for error in errors
    )


def test_rejects_yaml_escaped_placeholder_in_metadata_key(
    git_context: GitContext,
) -> None:
    _write_records(git_context)
    handoff = git_context.handoff_directory / "handoff.md"
    escaped_placeholder = r"\u007b\u007bUNKNOWN_FIELD\u007d\u007d"
    handoff.write_text(
        handoff.read_text(encoding="utf-8").replace(
            'task: "workflow gate"',
            f'task: "workflow gate"\n"{escaped_placeholder}": "unused"',
        ),
        encoding="utf-8",
    )

    errors = _validate(git_context)

    assert any(
        "handoff.md" in error
        and "unresolved placeholder" in error
        and "decoded front-matter key" in error
        for error in errors
    )


def test_accepts_ordinary_unicode_metadata_and_permitted_agent_lists(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        next_task="下一项有界任务",
        next_task_kind="code",
        handoff_implementers="/root/workflow_impl_1,/root/implementer-2",
        review_implementers="/root/implementer-2,/root/workflow_impl_1",
    )
    for record_name in ("handoff.md", "review.md"):
        record = git_context.handoff_directory / record_name
        record.write_text(
            record.read_text(encoding="utf-8").replace(
                'task: "workflow gate"',
                'task: "工作流门禁"',
            ),
            encoding="utf-8",
        )
    _write_next_prompt(
        git_context,
        previous_task="工作流门禁",
        task="下一项有界任务",
    )

    assert _validate(git_context) == []


@pytest.mark.parametrize("noncanonical", ["01", "+1", "١"])
def test_rejects_noncanonical_ascii_final_round(
    git_context: GitContext,
    noncanonical: str,
) -> None:
    _write_records(git_context, final_round=noncanonical)

    errors = _validate(git_context)

    assert any("final_round" in error and "canonical ASCII decimal" in error for error in errors)


@pytest.mark.parametrize("noncanonical", ["00", "+0", "٠"])
def test_rejects_noncanonical_ascii_unresolved_blocking_count(
    git_context: GitContext,
    noncanonical: str,
) -> None:
    _write_records(git_context, unresolved_blocking_count=noncanonical)

    errors = _validate(git_context)

    assert any(
        "unresolved_blocking_count" in error and "canonical ASCII decimal" in error
        for error in errors
    )


@pytest.mark.parametrize("noncanonical", ["02", "+2", "٢"])
def test_rejects_noncanonical_ascii_workflow_version(
    git_context: GitContext,
    noncanonical: str,
) -> None:
    _write_records(git_context)
    for record_name in ("handoff.md", "review.md"):
        record = git_context.handoff_directory / record_name
        record.write_text(
            record.read_text(encoding="utf-8").replace(
                "workflow_version: 2",
                f'workflow_version: "{noncanonical}"',
            ),
            encoding="utf-8",
        )

    errors = _validate(git_context)

    assert any(
        "workflow_version" in error and "canonical ASCII decimal" in error for error in errors
    )


@pytest.mark.parametrize("invalid_value", ["[]", "{}", "true", "42", "null"])
def test_rejects_nonstring_front_matter_values(
    git_context: GitContext,
    invalid_value: str,
) -> None:
    _write_records(git_context)
    handoff = git_context.handoff_directory / "handoff.md"
    handoff.write_text(
        handoff.read_text(encoding="utf-8").replace(
            'task: "workflow gate"',
            f"task: {invalid_value}",
        ),
        encoding="utf-8",
    )

    errors = _validate(git_context)

    assert any("field 'task' must be a single-line string scalar" in error for error in errors)


@pytest.mark.parametrize(
    "replacement",
    [
        "task: |\n  workflow gate",
        "task: >\n  workflow gate",
        'task: "workflow\n  gate"',
    ],
)
def test_rejects_multiline_front_matter_scalars(
    git_context: GitContext,
    replacement: str,
) -> None:
    _write_records(git_context)
    handoff = git_context.handoff_directory / "handoff.md"
    handoff.write_text(
        handoff.read_text(encoding="utf-8").replace('task: "workflow gate"', replacement),
        encoding="utf-8",
    )

    errors = _validate(git_context)

    assert any("field 'task' must be a single-line string scalar" in error for error in errors)


@pytest.mark.parametrize(
    "replacement",
    [
        'task: &task "workflow gate"',
        'task: !!str "workflow gate"',
        'task_alias: &task "workflow gate"\ntask: *task',
    ],
)
def test_rejects_yaml_anchors_aliases_and_explicit_tags(
    git_context: GitContext,
    replacement: str,
) -> None:
    _write_records(git_context)
    handoff = git_context.handoff_directory / "handoff.md"
    handoff.write_text(
        handoff.read_text(encoding="utf-8").replace('task: "workflow gate"', replacement),
        encoding="utf-8",
    )

    errors = _validate(git_context)

    assert any("anchors, aliases, or explicit tags" in error for error in errors)


def test_rejects_complex_front_matter_mapping_key(git_context: GitContext) -> None:
    _write_records(git_context)
    handoff = git_context.handoff_directory / "handoff.md"
    handoff.write_text(
        handoff.read_text(encoding="utf-8").replace(
            'task: "workflow gate"',
            '? [task]\n: "workflow gate"',
        ),
        encoding="utf-8",
    )

    errors = _validate(git_context)

    assert any("keys must be top-level string scalars" in error for error in errors)


def test_rejects_malformed_yaml_front_matter(git_context: GitContext) -> None:
    _write_records(git_context)
    handoff = git_context.handoff_directory / "handoff.md"
    handoff.write_text(
        handoff.read_text(encoding="utf-8").replace(
            'terminal_reason: "all_declared_gates_passed"',
            'terminal_reason: "unterminated',
        ),
        encoding="utf-8",
    )

    errors = _validate(git_context)

    assert any("invalid YAML front matter" in error for error in errors)


def test_rejects_nonmonotonic_review_round_chain(git_context: GitContext) -> None:
    _write_records(
        git_context,
        final_round="3",
        rounds_text=(
            f"### Round 1: `{git_context.candidate}`\n\n"
            f"### Round 2: `{git_context.prerequisite}`\n\n"
            f"### Round 3: `{git_context.candidate}`"
        ),
    )

    errors = _validate(git_context)

    assert any("ancestor" in error and "round 1" in error for error in errors)


@pytest.mark.parametrize("invalid_agent_id", ["[]", "{}", "a b", "agent!"])
def test_rejects_invalid_single_agent_identity_token(
    git_context: GitContext,
    invalid_agent_id: str,
) -> None:
    _write_records(
        git_context,
        handoff_root=invalid_agent_id,
        review_root=invalid_agent_id,
    )

    errors = _validate(git_context)

    assert any("valid agent identity token" in error for error in errors)


@pytest.mark.parametrize("invalid_agent_id", ["[]", "{}", "a b", "agent!"])
def test_rejects_invalid_list_agent_identity_token(
    git_context: GitContext,
    invalid_agent_id: str,
) -> None:
    value = f"implementer-1,{invalid_agent_id}"
    _write_records(
        git_context,
        handoff_implementers=value,
        review_implementers=value,
    )

    errors = _validate(git_context)

    assert any("valid agent identity token" in error for error in errors)


def test_accepts_canonical_agent_task_paths(git_context: GitContext) -> None:
    _write_records(
        git_context,
        handoff_implementers="/root/workflow_impl,/root/workflow_impl_2",
        review_implementers="/root/workflow_impl_2,/root/workflow_impl",
        handoff_fixers="/root/workflow_fix",
        review_fixers="/root/workflow_fix",
        handoff_root="/root",
        review_root="/root",
        handoff_spec_reviewer="/root/workflow_spec",
        review_spec_reviewer="/root/workflow_spec",
        handoff_adversarial_reviewer="/root/workflow_adversarial",
        review_adversarial_reviewer="/root/workflow_adversarial",
    )

    assert _validate(git_context) == []


@pytest.mark.parametrize(
    ("status", "verdict", "prompt_mode"),
    [
        ("blocked", "not_run", "recovery"),
        ("superseded", "not_applicable", "diagnosis"),
    ],
)
def test_pre_review_terminal_rejects_fixer_identity(
    git_context: GitContext,
    status: str,
    verdict: str,
    prompt_mode: str,
) -> None:
    _write_records(
        git_context,
        status=status,
        handoff_approved_commit="none",
        handoff_verdict=verdict,
        review_path="none",
        handoff_spec_reviewer="none",
        handoff_adversarial_reviewer="none",
        terminal_reason="pre_review_terminal",
        next_task="recover workflow task",
        next_task_kind="documentation",
    )
    (git_context.handoff_directory / "review.md").unlink()
    _write_next_prompt(
        git_context,
        prompt_mode=prompt_mode,
        task="recover workflow task",
        task_kind="documentation",
        review_path="none",
        review_verdict=verdict,
    )

    errors = _validate(git_context)

    assert any("fixer_agent_ids" in error and "none" in error for error in errors)


@pytest.mark.parametrize("directory_kind", ["handoff-root", "nested-run"])
def test_rejects_terminal_directory_that_is_not_single_direct_run_child(
    git_context: GitContext,
    directory_kind: str,
) -> None:
    handoff_root = git_context.handoff_directory.parent
    target = handoff_root if directory_kind == "handoff-root" else handoff_root / "run" / "nested"
    target.mkdir(parents=True, exist_ok=True)
    context = GitContext(
        git_context.repo,
        target,
        git_context.prerequisite,
        git_context.candidate,
    )
    _write_records(context)

    errors = _validate(context)

    assert any("single direct child" in error for error in errors)
