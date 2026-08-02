from __future__ import annotations

import pytest
from session_handoff_test_support import (
    GitContext,
    _validate,
    _write_next_prompt,
    _write_records,
)


@pytest.mark.parametrize("escaped_line_break", [r"\n", r"\r", r"\N", r"\L", r"\P"])
def test_rejects_yaml_escaped_line_breaks_in_terminal_record_metadata(
    git_context: GitContext,
    escaped_line_break: str,
) -> None:
    _write_records(git_context)
    escaped_task = f"workflow{escaped_line_break}gate"
    for record_name in ("handoff.md", "review.md"):
        record = git_context.handoff_directory / record_name
        record.write_text(
            record.read_text(encoding="utf-8").replace(
                'task: "workflow gate"',
                f'task: "{escaped_task}"',
            ),
            encoding="utf-8",
        )

    errors = _validate(git_context)

    assert all(
        any(record_name in error and "single-line" in error and "task" in error for error in errors)
        for record_name in ("handoff.md", "review.md")
    )


@pytest.mark.parametrize("escaped_line_break", [r"\n", r"\r", r"\N", r"\L", r"\P"])
def test_rejects_yaml_escaped_line_breaks_in_successor_prompt_metadata(
    git_context: GitContext,
    escaped_line_break: str,
) -> None:
    escaped_task = f"next{escaped_line_break}task"
    _write_records(
        git_context,
        next_task=escaped_task,
        next_task_kind="code",
    )
    _write_next_prompt(git_context, task=escaped_task)

    errors = _validate(git_context)

    assert any(
        "next-session-prompt.md" in error and "single-line" in error and "task" in error
        for error in errors
    )


@pytest.mark.parametrize(
    ("field", "canonical", "record_names"),
    [
        ("final_round", "1", ("review.md",)),
        ("unresolved_blocking_count", "0", ("review.md",)),
        ("workflow_version", "2", ("handoff.md", "review.md")),
    ],
)
@pytest.mark.parametrize("escape_template", [r"\x3{}", r"\u003{}", r"\U0000003{}"])
def test_rejects_yaml_escaped_canonical_integer_metadata(
    git_context: GitContext,
    field: str,
    canonical: str,
    record_names: tuple[str, ...],
    escape_template: str,
) -> None:
    _write_records(git_context)
    escaped = escape_template.format(canonical)
    for record_name in record_names:
        record = git_context.handoff_directory / record_name
        record.write_text(
            record.read_text(encoding="utf-8").replace(
                f'{field}: "{canonical}"'
                if field != "workflow_version"
                else f"{field}: {canonical}",
                f'{field}: "{escaped}"',
            ),
            encoding="utf-8",
        )

    errors = _validate(git_context)

    assert all(
        any(
            record_name in error and field in error and "canonical ASCII decimal" in error
            for error in errors
        )
        for record_name in record_names
    )
