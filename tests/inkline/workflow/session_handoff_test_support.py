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
    _git(repo, "init", "-q", "-b", "main")
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
    branch: str = "main",
    worktree_state: str = "clean",
    generated_at: str = "2026-08-02T12:00:00+08:00",
    reviewed_at: str = "2026-08-02T12:30:00+08:00",
    next_task: str = "none",
    next_task_kind: str = "none",
    review_path: str = "review.md",
    rounds_text: str | None = None,
) -> None:
    prerequisite = prerequisite or context.prerequisite
    result_commit = result_commit or context.candidate
    handoff_approved_commit = handoff_approved_commit or context.candidate
    review_candidate = review_candidate or context.candidate
    review_approved_commit = review_approved_commit or context.candidate
    final_spec_commit = final_spec_commit or context.candidate
    final_adversarial_commit = final_adversarial_commit or context.candidate
    rounds_text = rounds_text or f"### Round 1: `{review_candidate}`"
    directory = context.handoff_directory
    (directory / "handoff.md").write_text(
        f"""---
workflow_version: 2
task: "workflow gate"
task_kind: "{task_kind}"
status: "{status}"
branch: "{branch}"
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
worktree_state: "{worktree_state}"
generated_at: "{generated_at}"
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
reviewed_at: "{reviewed_at}"
---

# Review record: workflow gate

## Review rounds

{rounds_text}

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
