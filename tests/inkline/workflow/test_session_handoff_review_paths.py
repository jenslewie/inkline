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


@pytest.mark.parametrize(
    "rounds_text",
    [
        "### Round 1",
        "### Round 1: ``",
        "```markdown\n### Round 1: `{candidate}`\n```",
        "### Round 1: `{prerequisite}`",
        "### Round 1: `ffffffffffffffffffffffffffffffffffffffff`",
    ],
)
def test_rejects_noncanonical_or_stale_final_round_heading(
    git_context: GitContext,
    rounds_text: str,
) -> None:
    _write_records(
        git_context,
        rounds_text=rounds_text.format(
            candidate=git_context.candidate,
            prerequisite=git_context.prerequisite,
        ),
    )

    errors = _validate(git_context)

    assert any("review round" in error.lower() for error in errors)


def test_accepts_contiguous_canonical_rounds_and_ignores_fenced_examples(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        final_round="2",
        rounds_text=(
            "```markdown\n"
            f"### Round 99: `{git_context.candidate}`\n"
            "```\n\n"
            f"### Round 1: `{git_context.prerequisite}`\n\n"
            f"### Round 2: `{git_context.candidate}`"
        ),
    )

    assert _validate(git_context) == []


def test_rejects_annotated_tag_object_as_commit(git_context: GitContext) -> None:
    _git(git_context.repo, "tag", "-a", "candidate-tag", "-m", "annotated")
    tag_object = _git(git_context.repo, "rev-parse", "candidate-tag^{tag}")
    _write_records(git_context, prerequisite=tag_object)

    errors = _validate(git_context)

    assert any("commit object" in error for error in errors)


def test_rejects_handoff_directory_symlink(git_context: GitContext) -> None:
    real_directory = git_context.handoff_directory.with_name("real-run")
    git_context.handoff_directory.rename(real_directory)
    git_context.handoff_directory.symlink_to(real_directory.name, target_is_directory=True)

    errors = _validate(git_context)

    assert any("handoff directory" in error and "symbolic link" in error for error in errors)


def test_rejects_repo_relative_parent_symlink(git_context: GitContext) -> None:
    handoffs = git_context.handoff_directory.parent
    real_handoffs = handoffs.with_name("real-session-handoffs")
    handoffs.rename(real_handoffs)
    handoffs.symlink_to(real_handoffs.name, target_is_directory=True)

    errors = _validate(git_context)

    assert any("parent" in error and "symbolic link" in error for error in errors)


def test_rejects_terminal_handoff_outside_repository_handoff_root(tmp_path: Path) -> None:
    context_root = tmp_path / "outer"
    context_root.mkdir()
    repo = context_root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "workflow-test@example.invalid")
    _git(repo, "config", "user.name", "Workflow Test")
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "first")
    prerequisite = _git(repo, "rev-parse", "HEAD")
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "second")
    candidate = _git(repo, "rev-parse", "HEAD")
    context = GitContext(repo, repo / "arbitrary" / "run", prerequisite, candidate)
    context.handoff_directory.mkdir(parents=True)
    _write_records(context)

    errors = _validate(context)

    assert any("docs/handovers/session-handoffs" in error for error in errors)


def test_review_path_none_requires_review_file_absent(git_context: GitContext) -> None:
    _write_records(
        git_context,
        status="blocked",
        handoff_approved_commit="none",
        handoff_verdict="not_run",
        review_path="none",
        handoff_spec_reviewer="none",
        handoff_adversarial_reviewer="none",
        terminal_reason="pre_review_blocker",
        next_task="recover prerequisite",
        next_task_kind="documentation",
    )
    _write_next_prompt(
        git_context,
        prompt_mode="recovery",
        task="recover prerequisite",
        task_kind="documentation",
        review_path="none",
        review_verdict="not_run",
    )

    errors = _validate(git_context)

    assert any("review.md must not exist" in error for error in errors)


def test_next_task_none_requires_prompt_file_absent(git_context: GitContext) -> None:
    _write_records(git_context)
    _write_next_prompt(git_context)

    errors = _validate(git_context)

    assert any("next-session-prompt.md must not exist" in error for error in errors)


@pytest.mark.parametrize("field", ["branch", "worktree_state", "generated_at"])
def test_all_terminal_handoffs_require_nonempty_session_metadata(
    git_context: GitContext,
    field: str,
) -> None:
    _write_records(git_context, **{field: ""})

    errors = _validate(git_context)

    assert any(field in error for error in errors)


def test_reviewed_terminal_requires_nonempty_reviewed_at(git_context: GitContext) -> None:
    _write_records(git_context, reviewed_at="")

    errors = _validate(git_context)

    assert any("reviewed_at" in error for error in errors)


def test_terminal_branch_must_match_current_branch(git_context: GitContext) -> None:
    _write_records(git_context, branch="different-branch")

    errors = _validate(git_context)

    assert any("branch must match" in error for error in errors)


@pytest.mark.parametrize(
    ("phase", "phase_status"),
    [("spec", "not_run"), ("spec", "unavailable"), ("adversarial", "not_run")],
)
def test_accepts_post_review_blocked_with_one_unrun_or_unavailable_phase(
    git_context: GitContext,
    phase: str,
    phase_status: str,
) -> None:
    arguments: dict[str, str] = {
        "status": "blocked",
        "handoff_approved_commit": "none",
        "handoff_verdict": "changes_requested",
        "review_approved_commit": "none",
        "review_verdict": "changes_requested",
        "unresolved_blocking_count": "1",
        "manual_gate": "pending",
        "terminal_reason": "review_could_not_complete",
        "next_task": "resume independent review",
        "next_task_kind": "code",
    }
    if phase == "spec":
        arguments.update(
            handoff_spec_reviewer="none",
            review_spec_reviewer="none",
            final_spec_commit="none",
            final_spec_verdict=phase_status,
            final_adversarial_verdict="changes_requested",
        )
    else:
        arguments.update(
            handoff_adversarial_reviewer="none",
            review_adversarial_reviewer="none",
            final_adversarial_commit="none",
            final_adversarial_verdict=phase_status,
            final_spec_verdict="changes_requested",
        )
    _write_records(git_context, **arguments)
    _write_next_prompt(
        git_context,
        prompt_mode="recovery",
        task="resume independent review",
        review_verdict="changes_requested",
    )

    assert _validate(git_context) == []


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "handoff_spec_reviewer": "none",
            "review_spec_reviewer": "none",
            "final_spec_commit": "none",
            "final_spec_verdict": "not_run",
            "handoff_adversarial_reviewer": "none",
            "review_adversarial_reviewer": "none",
            "final_adversarial_commit": "none",
            "final_adversarial_verdict": "unavailable",
        },
        {
            "handoff_spec_reviewer": "none",
            "review_spec_reviewer": "none",
            "final_spec_verdict": "changes_requested",
        },
        {
            "final_adversarial_commit": "none",
            "final_adversarial_verdict": "approved",
        },
        {
            "handoff_adversarial_reviewer": "none",
            "review_adversarial_reviewer": "none",
            "final_adversarial_verdict": "approved",
        },
    ],
)
def test_rejects_inconsistent_post_review_phase_evidence(
    git_context: GitContext,
    arguments: dict[str, str],
) -> None:
    defaults: dict[str, str] = {
        "status": "blocked",
        "handoff_approved_commit": "none",
        "handoff_verdict": "changes_requested",
        "review_approved_commit": "none",
        "review_verdict": "changes_requested",
        "final_spec_verdict": "changes_requested",
        "unresolved_blocking_count": "1",
        "manual_gate": "pending",
        "terminal_reason": "review_found_blocker",
        "next_task": "resolve review blocker",
        "next_task_kind": "code",
    }
    defaults.update(arguments)
    _write_records(git_context, **defaults)
    _write_next_prompt(
        git_context,
        prompt_mode="recovery",
        task="resolve review blocker",
        review_verdict="changes_requested",
    )

    errors = _validate(git_context)

    assert any(
        "phase evidence" in error or "at least one review phase" in error for error in errors
    )


def test_accepts_post_review_superseded_with_retained_partial_review(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        status="superseded",
        handoff_approved_commit="none",
        handoff_verdict="superseded",
        review_approved_commit="none",
        review_verdict="superseded",
        final_spec_verdict="approved",
        handoff_adversarial_reviewer="none",
        review_adversarial_reviewer="none",
        final_adversarial_commit="none",
        final_adversarial_verdict="not_run",
        unresolved_blocking_count="0",
        manual_gate="not_required",
        terminal_reason="governing_contract_was_replaced",
        next_task="diagnose replacement contract",
        next_task_kind="documentation",
    )
    _write_next_prompt(
        git_context,
        prompt_mode="diagnosis",
        task="diagnose replacement contract",
        task_kind="documentation",
        review_verdict="superseded",
    )

    assert _validate(git_context) == []
