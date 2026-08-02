from __future__ import annotations

import importlib.util
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).parents[3]
VALIDATOR_PATH = PROJECT_ROOT / "scripts" / "validate_session_handoff.py"


def _load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_session_handoff", VALIDATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def _git(repo: Path, *arguments: str, input_text: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
        input=input_text,
    ).stdout.strip()


@dataclass(frozen=True)
class GitContext:
    repo: Path
    handoff_directory: Path
    prerequisite: str
    candidate: str


@pytest.fixture
def git_context(tmp_path: Path) -> GitContext:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "workflow-test@example.invalid")
    _git(repo, "config", "user.name", "Workflow Test")
    tracked = repo / "tracked.txt"
    tracked.write_text("prerequisite\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "test: prerequisite")
    prerequisite = _git(repo, "rev-parse", "HEAD")
    tracked.write_text("candidate\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "test: candidate")
    candidate = _git(repo, "rev-parse", "HEAD")
    handoff_directory = repo / "docs" / "handovers" / "session-handoffs" / "run"
    handoff_directory.mkdir(parents=True)
    return GitContext(repo, handoff_directory, prerequisite, candidate)


def _write_records(
    context: GitContext,
    *,
    task_kind: str = "code",
    status: str = "complete",
    prerequisite: str | None = None,
    result_commit: str | None = None,
    handoff_approved_commit: str | None = None,
    handoff_verdict: str = "approved",
    review_candidate: str | None = None,
    review_approved_commit: str | None = None,
    review_verdict: str = "approved",
    final_round: str = "1",
    final_spec_commit: str | None = None,
    final_spec_verdict: str = "approved",
    final_adversarial_commit: str | None = None,
    final_adversarial_verdict: str = "approved",
    unresolved_blocking_count: str = "0",
    manual_gate: str = "not_required",
    handoff_implementers: str = "implementer-1",
    review_implementers: str = "implementer-1",
    handoff_fixers: str = "fixer-1",
    review_fixers: str = "fixer-1",
    handoff_root: str = "root-agent-1",
    review_root: str = "root-agent-1",
    handoff_spec_reviewer: str = "spec-reviewer-1",
    review_spec_reviewer: str = "spec-reviewer-1",
    handoff_adversarial_reviewer: str = "adversarial-reviewer-1",
    review_adversarial_reviewer: str = "adversarial-reviewer-1",
    terminal_reason: str = "all_declared_gates_passed",
    next_task: str = "none",
    next_task_kind: str = "none",
    review_path: str = "review.md",
) -> None:
    prerequisite = prerequisite or context.prerequisite
    result_commit = result_commit or context.candidate
    handoff_approved_commit = handoff_approved_commit or context.candidate
    review_candidate = review_candidate or context.candidate
    review_approved_commit = review_approved_commit or context.candidate
    final_spec_commit = final_spec_commit or context.candidate
    final_adversarial_commit = final_adversarial_commit or context.candidate
    directory = context.handoff_directory
    (directory / "handoff.md").write_text(
        f"""---
workflow_version: 2
task: "workflow gate"
task_kind: "{task_kind}"
status: "{status}"
branch: "main"
prerequisite_commit: "{prerequisite}"
result_commit: "{result_commit}"
review_path: "{review_path}"
review_verdict: "{handoff_verdict}"
approved_commit: "{handoff_approved_commit}"
implementer_agent_ids: "{handoff_implementers}"
fixer_agent_ids: "{handoff_fixers}"
root_agent_id: "{handoff_root}"
spec_reviewer_agent_id: "{handoff_spec_reviewer}"
adversarial_reviewer_agent_id: "{handoff_adversarial_reviewer}"
manual_gate: "{manual_gate}"
terminal_reason: "{terminal_reason}"
generated_at: "2026-08-02T12:00:00+08:00"
next_task: "{next_task}"
next_task_kind: "{next_task_kind}"
---

# Session handoff: workflow gate

Terminal workflow record.
""",
        encoding="utf-8",
    )
    (directory / "review.md").write_text(
        f"""---
workflow_version: 2
task: "workflow gate"
task_kind: "{task_kind}"
verdict: "{review_verdict}"
prerequisite_commit: "{prerequisite}"
candidate_commit: "{review_candidate}"
approved_commit: "{review_approved_commit}"
implementer_agent_ids: "{review_implementers}"
fixer_agent_ids: "{review_fixers}"
root_agent_id: "{review_root}"
spec_reviewer_agent_id: "{review_spec_reviewer}"
adversarial_reviewer_agent_id: "{review_adversarial_reviewer}"
final_round: "{final_round}"
final_spec_reviewed_commit: "{final_spec_commit}"
final_spec_verdict: "{final_spec_verdict}"
final_adversarial_reviewed_commit: "{final_adversarial_commit}"
final_adversarial_verdict: "{final_adversarial_verdict}"
unresolved_blocking_count: "{unresolved_blocking_count}"
manual_gate: "{manual_gate}"
reviewed_at: "2026-08-02T12:30:00+08:00"
---

# Review record: workflow gate

## Review rounds

### Round 1

Both phases approved the final candidate.
""",
        encoding="utf-8",
    )


def _write_next_prompt(
    context: GitContext,
    *,
    prompt_mode: str = "implementation",
    workflow_version: str = "2",
    previous_task: str = "workflow gate",
    task: str = "next bounded task",
    task_kind: str = "code",
    handoff_path: str = "handoff.md",
    prerequisite_commit: str | None = None,
    review_path: str = "review.md",
    review_verdict: str = "approved",
) -> None:
    prerequisite_commit = prerequisite_commit or context.candidate
    (context.handoff_directory / "next-session-prompt.md").write_text(
        f"""---
workflow_version: {workflow_version}
prompt_mode: "{prompt_mode}"
previous_task: "{previous_task}"
task: "{task}"
task_kind: "{task_kind}"
handoff_path: "{handoff_path}"
prerequisite_commit: "{prerequisite_commit}"
review_path: "{review_path}"
review_verdict: "{review_verdict}"
---

# Task

Execute the next bounded task.
""",
        encoding="utf-8",
    )


def _validate(context: GitContext, expected_commit: str | None = None) -> list[str]:
    return validator.validate_handoff_directory(
        context.handoff_directory,
        expected_commit=expected_commit or context.candidate,
    )


def test_accepts_complete_code_handoff_with_structured_final_approval(
    git_context: GitContext,
) -> None:
    _write_records(git_context)

    assert _validate(git_context) == []


def test_accepts_one_reviewer_for_both_documentation_phases(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        task_kind="documentation",
        handoff_spec_reviewer="documentation-reviewer-1",
        review_spec_reviewer="documentation-reviewer-1",
        handoff_adversarial_reviewer="documentation-reviewer-1",
        review_adversarial_reviewer="documentation-reviewer-1",
    )

    assert _validate(git_context) == []


@pytest.mark.parametrize(
    ("arguments", "expected_fragment"),
    [
        ({"final_round": "0"}, "final_round"),
        ({"final_round": "not-an-integer"}, "final_round"),
        ({"final_spec_commit": "prerequisite"}, "final_spec_reviewed_commit"),
        ({"final_adversarial_commit": "prerequisite"}, "final_adversarial_reviewed_commit"),
        ({"final_spec_verdict": "changes_requested"}, "final_spec_verdict"),
        ({"final_adversarial_verdict": "changes_requested"}, "final_adversarial_verdict"),
        ({"unresolved_blocking_count": "1"}, "unresolved_blocking_count"),
        ({"manual_gate": "pending"}, "manual_gate"),
    ],
)
def test_rejects_incomplete_structured_final_review(
    git_context: GitContext,
    arguments: dict[str, str],
    expected_fragment: str,
) -> None:
    if arguments.get("final_spec_commit") == "prerequisite":
        arguments["final_spec_commit"] = git_context.prerequisite
    if arguments.get("final_adversarial_commit") == "prerequisite":
        arguments["final_adversarial_commit"] = git_context.prerequisite
    _write_records(git_context, **arguments)

    errors = _validate(git_context)

    assert any(expected_fragment in error for error in errors)


def test_rejects_final_round_that_does_not_match_recorded_rounds(
    git_context: GitContext,
) -> None:
    _write_records(git_context, final_round="2")

    errors = _validate(git_context)

    assert any("final_round" in error and "recorded review rounds" in error for error in errors)


def test_cli_requires_expected_commit(git_context: GitContext) -> None:
    _write_records(git_context)

    with pytest.raises(SystemExit) as error:
        validator.main([str(git_context.handoff_directory)])

    assert error.value.code == 2


@pytest.mark.parametrize("field", ["prerequisite", "result", "approved"])
def test_rejects_commit_ids_that_do_not_exist_in_repository(
    git_context: GitContext,
    field: str,
) -> None:
    nonexistent = "f" * 40
    arguments: dict[str, str] = {}
    if field == "prerequisite":
        arguments["prerequisite"] = nonexistent
    elif field == "result":
        arguments.update(
            result_commit=nonexistent,
            handoff_approved_commit=nonexistent,
            review_candidate=nonexistent,
            review_approved_commit=nonexistent,
            final_spec_commit=nonexistent,
            final_adversarial_commit=nonexistent,
        )
    else:
        arguments["handoff_approved_commit"] = nonexistent
        arguments["review_approved_commit"] = nonexistent
    _write_records(git_context, **arguments)

    errors = _validate(git_context, expected_commit=nonexistent if field == "result" else None)

    assert any("does not name a commit" in error for error in errors)


def test_rejects_prerequisite_that_is_not_result_ancestor(git_context: GitContext) -> None:
    side_commit = _git(
        git_context.repo,
        "commit-tree",
        f"{git_context.candidate}^{{tree}}",
        "-p",
        git_context.prerequisite,
        input_text="side candidate\n",
    )
    _write_records(git_context, prerequisite=side_commit)

    errors = _validate(git_context)

    assert any("ancestor" in error for error in errors)


def test_rejects_result_that_is_not_current_head(git_context: GitContext) -> None:
    _write_records(git_context)
    (git_context.repo / "tracked.txt").write_text("later\n", encoding="utf-8")
    _git(git_context.repo, "add", "tracked.txt")
    _git(git_context.repo, "commit", "-q", "-m", "test: later")

    errors = _validate(git_context)

    assert any("current HEAD" in error for error in errors)


def test_rejects_complete_handoff_without_required_expected_commit(
    git_context: GitContext,
) -> None:
    _write_records(git_context)

    errors = validator.validate_handoff_directory(git_context.handoff_directory)

    assert any("expected_commit is required" in error for error in errors)


def test_next_task_requires_prompt(git_context: GitContext) -> None:
    _write_records(git_context, next_task="next bounded task", next_task_kind="code")

    errors = _validate(git_context)

    assert any("next-session-prompt.md" in error and "required" in error for error in errors)


def test_next_task_none_allows_no_prompt(git_context: GitContext) -> None:
    _write_records(git_context)

    assert _validate(git_context) == []


@pytest.mark.parametrize(
    ("arguments", "expected_fragment"),
    [
        ({"workflow_version": "3"}, "workflow_version"),
        ({"previous_task": "wrong task"}, "previous_task"),
        ({"task": "wrong next task"}, "task"),
        ({"task_kind": "documentation"}, "task_kind"),
        ({"handoff_path": "different-handoff.md"}, "handoff_path"),
        ({"prerequisite_commit": "prerequisite"}, "prerequisite_commit"),
        ({"review_path": "different-review.md"}, "review_path"),
        ({"review_verdict": "changes_requested"}, "review_verdict"),
        ({"prompt_mode": "recovery"}, "prompt_mode"),
    ],
)
def test_rejects_prompt_metadata_mismatch(
    git_context: GitContext,
    arguments: dict[str, str],
    expected_fragment: str,
) -> None:
    _write_records(git_context, next_task="next bounded task", next_task_kind="code")
    if arguments.get("prerequisite_commit") == "prerequisite":
        arguments["prerequisite_commit"] = git_context.prerequisite
    _write_next_prompt(git_context, **arguments)

    errors = _validate(git_context)

    assert any("next-session-prompt.md" in error and expected_fragment in error for error in errors)


@pytest.mark.parametrize("status", ["in_progress", "ready_for_review", "approved", "unknown"])
def test_rejects_nonterminal_or_unknown_handoff_status(
    git_context: GitContext,
    status: str,
) -> None:
    _write_records(git_context, status=status)

    errors = _validate(git_context)

    assert any("terminal status" in error for error in errors)


@pytest.mark.parametrize(
    ("status", "prompt_mode", "verdict"),
    [
        ("blocked", "recovery", "not_run"),
        ("superseded", "diagnosis", "not_applicable"),
    ],
)
def test_accepts_nonapproved_terminal_handoff_with_executable_prompt(
    git_context: GitContext,
    status: str,
    prompt_mode: str,
    verdict: str,
) -> None:
    _write_records(
        git_context,
        status=status,
        handoff_approved_commit="none",
        handoff_verdict=verdict,
        terminal_reason="cannot_safely_continue",
        next_task="recover workflow task",
        next_task_kind="documentation",
        review_path="none",
        handoff_spec_reviewer="none",
        handoff_adversarial_reviewer="none",
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

    assert _validate(git_context) == []


@pytest.mark.parametrize("status", ["blocked", "superseded"])
def test_nonapproved_terminal_handoff_requires_reason_and_prompt(
    git_context: GitContext,
    status: str,
) -> None:
    verdict = "not_run" if status == "blocked" else "not_applicable"
    _write_records(
        git_context,
        status=status,
        handoff_approved_commit="none",
        handoff_verdict=verdict,
        terminal_reason="",
        next_task="recover workflow task",
        next_task_kind="documentation",
        review_path="none",
        handoff_spec_reviewer="none",
        handoff_adversarial_reviewer="none",
    )
    (git_context.handoff_directory / "review.md").unlink()

    errors = _validate(git_context)

    assert any("terminal_reason" in error for error in errors)
    assert any("next-session-prompt.md" in error for error in errors)


@pytest.mark.parametrize("status", ["blocked", "superseded"])
def test_nonapproved_terminal_handoff_cannot_omit_successor(
    git_context: GitContext,
    status: str,
) -> None:
    verdict = "not_run" if status == "blocked" else "not_applicable"
    _write_records(
        git_context,
        status=status,
        handoff_approved_commit="none",
        handoff_verdict=verdict,
        terminal_reason="cannot_safely_continue",
        review_path="none",
        handoff_spec_reviewer="none",
        handoff_adversarial_reviewer="none",
    )
    (git_context.handoff_directory / "review.md").unlink()

    errors = _validate(git_context)

    assert any("must name a recovery or diagnosis task" in error for error in errors)


def test_nonapproved_terminal_handoff_rejects_root_as_implementer(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        status="blocked",
        handoff_approved_commit="none",
        handoff_verdict="not_run",
        terminal_reason="cannot_safely_continue",
        next_task="recover workflow task",
        next_task_kind="documentation",
        review_path="none",
        handoff_implementers="root-agent-1",
        handoff_spec_reviewer="none",
        handoff_adversarial_reviewer="none",
    )
    (git_context.handoff_directory / "review.md").unlink()
    _write_next_prompt(
        git_context,
        prompt_mode="recovery",
        task="recover workflow task",
        task_kind="documentation",
        review_path="none",
        review_verdict="not_run",
    )

    errors = _validate(git_context)

    assert any("agent roles must be mutually exclusive" in error for error in errors)


def test_accepts_blocked_post_review_with_retained_blocker_evidence(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        status="blocked",
        handoff_approved_commit="none",
        handoff_verdict="changes_requested",
        review_approved_commit="none",
        review_verdict="changes_requested",
        final_spec_verdict="changes_requested",
        unresolved_blocking_count="2",
        manual_gate="pending",
        terminal_reason="review_found_contract_blockers",
        next_task="resolve review blockers",
        next_task_kind="code",
    )
    _write_next_prompt(
        git_context,
        prompt_mode="recovery",
        task="resolve review blockers",
        review_verdict="changes_requested",
    )

    assert _validate(git_context) == []


def test_rejects_blocked_changes_requested_without_review_evidence(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        status="blocked",
        handoff_approved_commit="none",
        handoff_verdict="changes_requested",
        terminal_reason="review_found_contract_blockers",
        next_task="resolve review blockers",
        next_task_kind="code",
        review_path="none",
        handoff_spec_reviewer="none",
        handoff_adversarial_reviewer="none",
    )
    (git_context.handoff_directory / "review.md").unlink()
    _write_next_prompt(
        git_context,
        prompt_mode="recovery",
        task="resolve review blockers",
        review_verdict="changes_requested",
        review_path="none",
    )

    errors = _validate(git_context)

    assert any("changes_requested requires retained review.md" in error for error in errors)


def test_rejects_blocked_post_review_without_structured_blocker_evidence(
    git_context: GitContext,
) -> None:
    record_arguments = {
        "status": "blocked",
        "handoff_approved_commit": "none",
        "handoff_verdict": "changes_requested",
        "review_approved_commit": "none",
        "review_verdict": "changes_requested",
        "final_spec_verdict": "changes_requested",
        "unresolved_blocking_count": "1",
        "manual_gate": "pending",
        "terminal_reason": "review_found_contract_blockers",
        "next_task": "resolve review blockers",
        "next_task_kind": "code",
    }
    record_arguments["unresolved_blocking_count"] = "0"
    _write_records(git_context, **record_arguments)
    _write_next_prompt(
        git_context,
        prompt_mode="recovery",
        task="resolve review blockers",
        review_verdict="changes_requested",
    )

    errors = _validate(git_context)

    assert any("unresolved_blocking_count" in error for error in errors)


def test_accepts_post_review_user_decision_blocker_after_approved_phases(
    git_context: GitContext,
) -> None:
    _write_records(
        git_context,
        status="blocked",
        handoff_approved_commit="none",
        handoff_verdict="changes_requested",
        review_approved_commit="none",
        review_verdict="changes_requested",
        unresolved_blocking_count="1",
        manual_gate="pending",
        terminal_reason="awaiting_user_contract_decision",
        next_task="resolve user decision",
        next_task_kind="documentation",
    )
    _write_next_prompt(
        git_context,
        prompt_mode="recovery",
        task="resolve user decision",
        task_kind="documentation",
        review_verdict="changes_requested",
    )

    assert _validate(git_context) == []


@pytest.mark.parametrize(
    ("field", "agent_id"),
    [
        ("handoff_implementers", "root-agent-1"),
        ("handoff_fixers", "root-agent-1"),
        ("handoff_fixers", "implementer-1"),
        ("handoff_spec_reviewer", "fixer-1"),
        ("handoff_adversarial_reviewer", "spec-reviewer-1"),
    ],
)
def test_rejects_overlapping_agent_roles(
    git_context: GitContext,
    field: str,
    agent_id: str,
) -> None:
    arguments = {field: agent_id}
    matching_review_field = {
        "handoff_implementers": "review_implementers",
        "handoff_fixers": "review_fixers",
        "handoff_spec_reviewer": "review_spec_reviewer",
        "handoff_adversarial_reviewer": "review_adversarial_reviewer",
    }[field]
    arguments[matching_review_field] = agent_id
    _write_records(git_context, **arguments)

    errors = _validate(git_context)

    assert any("agent roles must be mutually exclusive" in error for error in errors)


def test_rejects_handoff_review_reviewer_metadata_mismatch(git_context: GitContext) -> None:
    _write_records(git_context, review_spec_reviewer="different-reviewer")

    errors = _validate(git_context)

    assert any("spec_reviewer_agent_id" in error for error in errors)


@pytest.mark.parametrize("filename", ["handoff.md", "review.md", "next-session-prompt.md"])
def test_rejects_symlinked_workflow_records(git_context: GitContext, filename: str) -> None:
    _write_records(git_context, next_task="next bounded task", next_task_kind="code")
    _write_next_prompt(git_context)
    record = git_context.handoff_directory / filename
    target = git_context.handoff_directory / f"real-{filename}"
    record.rename(target)
    record.symlink_to(target.name)

    errors = _validate(git_context)

    assert any(filename in error and "symbolic link" in error for error in errors)


@pytest.mark.parametrize("review_path", ["../review.md", "/tmp/review.md"])
def test_rejects_review_path_escape(git_context: GitContext, review_path: str) -> None:
    _write_records(git_context, review_path=review_path)

    errors = _validate(git_context)

    assert any("review_path" in error for error in errors)


def test_rejects_unresolved_placeholder_in_generated_markdown(
    git_context: GitContext,
) -> None:
    _write_records(git_context)
    (git_context.handoff_directory / "extra.md").write_text(
        "# Extra\n\n{{UNRESOLVED}}\n",
        encoding="utf-8",
    )

    errors = _validate(git_context)

    assert any("unresolved placeholder" in error for error in errors)


@pytest.mark.parametrize(
    ("template_name", "required_fields"),
    [
        (
            "session-handoff.md",
            {
                "fixer_agent_ids",
                "spec_reviewer_agent_id",
                "adversarial_reviewer_agent_id",
                "manual_gate",
                "terminal_reason",
                "next_task_kind",
            },
        ),
        (
            "session-review.md",
            {
                "final_round",
                "final_spec_reviewed_commit",
                "final_spec_verdict",
                "final_adversarial_reviewed_commit",
                "final_adversarial_verdict",
                "unresolved_blocking_count",
                "manual_gate",
            },
        ),
        (
            "next-session-prompt.md",
            {"prompt_mode", "handoff_path", "task", "task_kind"},
        ),
        (
            "review-session-prompt.md",
            {
                "prompt_mode",
                "review_phase",
                "candidate_commit",
                "review_path",
                "reviewer_agent_id",
            },
        ),
    ],
)
def test_templates_expose_validator_contract_fields(
    template_name: str,
    required_fields: set[str],
) -> None:
    errors: list[str] = []
    metadata = validator._front_matter(
        PROJECT_ROOT / "docs" / "templates" / template_name,
        errors,
    )

    assert errors == []
    assert required_fields <= metadata.keys()


def test_review_only_template_is_explicitly_read_only() -> None:
    template = (PROJECT_ROOT / "docs" / "templates" / "review-session-prompt.md").read_text(
        encoding="utf-8"
    )

    assert 'prompt_mode: "review_only"' in template
    assert "不得修改、stage 或 commit tracked 文件" in template
    assert "不得生成 `handoff.md`" in template
