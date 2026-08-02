from __future__ import annotations

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
