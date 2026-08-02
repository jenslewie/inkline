from __future__ import annotations

import importlib.util
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

PREREQUISITE = "1" * 40
CANDIDATE = "2" * 40


def _write_records(
    directory: Path,
    *,
    task_kind: str = "code",
    status: str = "complete",
    handoff_prerequisite: str = PREREQUISITE,
    review_prerequisite: str = PREREQUISITE,
    result_commit: str = CANDIDATE,
    candidate_commit: str = CANDIDATE,
    handoff_approved_commit: str = CANDIDATE,
    review_approved_commit: str = CANDIDATE,
    handoff_verdict: str = "approved",
    review_verdict: str = "approved",
    handoff_implementers: str = "implementer-1,fixer-1",
    review_implementers: str = "implementer-1,fixer-1",
    handoff_root: str = "root-agent-1",
    review_root: str = "root-agent-1",
    spec_reviewer: str = "spec-reviewer-1",
    adversarial_reviewer: str = "adversarial-reviewer-1",
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "handoff.md").write_text(
        f"""---
workflow_version: 2
task: "workflow gate"
task_kind: "{task_kind}"
status: "{status}"
branch: "main"
prerequisite_commit: "{handoff_prerequisite}"
result_commit: "{result_commit}"
review_path: "review.md"
review_verdict: "{handoff_verdict}"
approved_commit: "{handoff_approved_commit}"
implementer_agent_ids: "{handoff_implementers}"
root_agent_id: "{handoff_root}"
generated_at: "2026-08-02T12:00:00+08:00"
next_task: "none"
---

# Session handoff: workflow gate

Complete and independently reviewed.
""",
        encoding="utf-8",
    )
    (directory / "review.md").write_text(
        f"""---
workflow_version: 2
task: "workflow gate"
task_kind: "{task_kind}"
verdict: "{review_verdict}"
prerequisite_commit: "{review_prerequisite}"
candidate_commit: "{candidate_commit}"
approved_commit: "{review_approved_commit}"
implementer_agent_ids: "{review_implementers}"
root_agent_id: "{review_root}"
spec_reviewer_agent_id: "{spec_reviewer}"
adversarial_reviewer_agent_id: "{adversarial_reviewer}"
reviewed_at: "2026-08-02T12:30:00+08:00"
---

# Review record: workflow gate

## Review rounds

No blocking findings.
""",
        encoding="utf-8",
    )


def _write_next_prompt(
    directory: Path,
    *,
    prerequisite_commit: str = CANDIDATE,
    review_path: str = "review.md",
) -> None:
    (directory / "next-session-prompt.md").write_text(
        f"""---
workflow_version: 2
previous_task: "workflow gate"
prerequisite_commit: "{prerequisite_commit}"
review_path: "{review_path}"
review_verdict: "approved"
---

# Task

Execute the next bounded task.
""",
        encoding="utf-8",
    )


def test_accepts_complete_code_handoff_with_matching_independent_approval(
    tmp_path: Path,
) -> None:
    _write_records(tmp_path)

    assert validator.validate_handoff_directory(tmp_path) == []


def test_accepts_one_independent_reviewer_for_both_documentation_phases(
    tmp_path: Path,
) -> None:
    _write_records(
        tmp_path,
        task_kind="documentation",
        spec_reviewer="documentation-reviewer-1",
        adversarial_reviewer="documentation-reviewer-1",
    )

    assert validator.validate_handoff_directory(tmp_path) == []


def test_rejects_complete_handoff_without_review(tmp_path: Path) -> None:
    _write_records(tmp_path)
    (tmp_path / "review.md").unlink()

    errors = validator.validate_handoff_directory(tmp_path)

    assert any("review.md" in error and "does not exist" in error for error in errors)


def test_rejects_unresolved_placeholder_in_generated_markdown(tmp_path: Path) -> None:
    _write_records(tmp_path)
    (tmp_path / "next-session-prompt.md").write_text(
        "# Next task\n\nCommit: {{PREREQUISITE_COMMIT}}\n",
        encoding="utf-8",
    )

    errors = validator.validate_handoff_directory(tmp_path)

    assert any("unresolved placeholder" in error for error in errors)


@pytest.mark.parametrize("field", ["handoff", "review"])
def test_rejects_non_approved_verdict(tmp_path: Path, field: str) -> None:
    arguments = (
        {"handoff_verdict": "changes_requested"}
        if field == "handoff"
        else {"review_verdict": "changes_requested"}
    )
    _write_records(tmp_path, **arguments)

    errors = validator.validate_handoff_directory(tmp_path)

    assert any("approved" in error for error in errors)


@pytest.mark.parametrize(
    ("arguments", "expected_fragment"),
    [
        ({"review_prerequisite": "3" * 40}, "prerequisite_commit"),
        ({"candidate_commit": "3" * 40}, "candidate_commit"),
        ({"review_approved_commit": "3" * 40}, "approved_commit"),
        ({"handoff_approved_commit": "3" * 40}, "approved_commit"),
    ],
)
def test_rejects_commit_identity_mismatch(
    tmp_path: Path,
    arguments: dict[str, str],
    expected_fragment: str,
) -> None:
    _write_records(tmp_path, **arguments)

    errors = validator.validate_handoff_directory(tmp_path)

    assert any(expected_fragment in error for error in errors)


@pytest.mark.parametrize(
    ("arguments", "expected_fragment"),
    [
        ({"handoff_implementers": ""}, "implementer_agent_ids"),
        ({"review_implementers": ""}, "implementer_agent_ids"),
        ({"handoff_root": ""}, "root_agent_id"),
        ({"review_root": ""}, "root_agent_id"),
        ({"spec_reviewer": ""}, "spec_reviewer_agent_id"),
        ({"adversarial_reviewer": ""}, "adversarial_reviewer_agent_id"),
    ],
)
def test_rejects_missing_agent_identity(
    tmp_path: Path,
    arguments: dict[str, str],
    expected_fragment: str,
) -> None:
    _write_records(tmp_path, **arguments)

    errors = validator.validate_handoff_directory(tmp_path)

    assert any(expected_fragment in error for error in errors)


@pytest.mark.parametrize("reviewer_field", ["spec_reviewer", "adversarial_reviewer"])
def test_rejects_self_review(tmp_path: Path, reviewer_field: str) -> None:
    _write_records(tmp_path, **{reviewer_field: "implementer-1"})

    errors = validator.validate_handoff_directory(tmp_path)

    assert any("must be independent" in error for error in errors)


def test_rejects_root_self_review(tmp_path: Path) -> None:
    _write_records(tmp_path, spec_reviewer="root-agent-1")

    errors = validator.validate_handoff_directory(tmp_path)

    assert any("root orchestrator" in error for error in errors)


def test_rejects_code_task_without_distinct_reviewers(tmp_path: Path) -> None:
    _write_records(
        tmp_path,
        spec_reviewer="reviewer-1",
        adversarial_reviewer="reviewer-1",
    )

    errors = validator.validate_handoff_directory(tmp_path)

    assert any("distinct" in error for error in errors)


def test_rejects_expected_commit_that_is_not_the_approved_commit(tmp_path: Path) -> None:
    _write_records(tmp_path)

    errors = validator.validate_handoff_directory(tmp_path, expected_commit="3" * 40)

    assert any("expected commit" in error for error in errors)


def test_accepts_next_prompt_that_names_the_approved_baseline(tmp_path: Path) -> None:
    _write_records(tmp_path)
    _write_next_prompt(tmp_path)

    assert validator.validate_handoff_directory(tmp_path) == []


@pytest.mark.parametrize(
    ("arguments", "expected_fragment"),
    [
        ({"prerequisite_commit": "3" * 40}, "prerequisite_commit"),
        ({"review_path": "different-review.md"}, "review_path"),
    ],
)
def test_rejects_next_prompt_with_stale_approval_metadata(
    tmp_path: Path,
    arguments: dict[str, str],
    expected_fragment: str,
) -> None:
    _write_records(tmp_path)
    _write_next_prompt(tmp_path, **arguments)

    errors = validator.validate_handoff_directory(tmp_path)

    assert any("next-session-prompt.md" in error and expected_fragment in error for error in errors)
