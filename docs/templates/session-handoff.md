---
workflow_version: 1
task: "{{TASK_NAME}}"
status: "{{STATUS}}"
branch: "main"
prerequisite_commit: "{{PREREQUISITE_COMMIT}}"
result_commit: "{{RESULT_COMMIT}}"
worktree_state: "{{WORKTREE_STATE}}"
generated_at: "{{GENERATED_AT}}"
next_task: "{{NEXT_TASK}}"
---

# Session handoff: {{TASK_NAME}}

## Outcome

{{OUTCOME}}

## Authoritative contracts

{{AUTHORITATIVE_CONTRACTS}}

## Scope delivered

{{SCOPE_DELIVERED}}

## Changed files

{{CHANGED_FILES}}

## Accepted artifacts

{{ACCEPTED_ARTIFACTS}}

## Validation

### Commands

{{VALIDATION_COMMANDS}}

### Results

{{VALIDATION_RESULTS}}

## Regression samples checked

{{REGRESSION_SAMPLES}}

## Unresolved issues and risks

{{UNRESOLVED_ISSUES}}

## Next task prerequisites

{{NEXT_TASK_PREREQUISITES}}

## Context integrity notes

{{CONTEXT_INTEGRITY_NOTES}}
