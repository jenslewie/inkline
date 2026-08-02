---
workflow_version: 2
task: "{{TASK_NAME}}"
task_kind: "{{TASK_KIND}}"
status: "{{STATUS}}"
branch: "main"
prerequisite_commit: "{{PREREQUISITE_COMMIT}}"
result_commit: "{{RESULT_COMMIT}}"
review_path: "{{REVIEW_PATH}}"
review_verdict: "{{REVIEW_VERDICT}}"
approved_commit: "{{APPROVED_COMMIT}}"
implementer_agent_ids: "{{IMPLEMENTER_AGENT_IDS}}"
root_agent_id: "{{ROOT_AGENT_ID}}"
worktree_state: "{{WORKTREE_STATE}}"
generated_at: "{{GENERATED_AT}}"
next_task: "{{NEXT_TASK}}"
---

# Session handoff: {{TASK_NAME}}

## Outcome

{{OUTCOME}}

## Independent review

- Review record: `{{REVIEW_PATH}}`
- Final verdict: `{{REVIEW_VERDICT}}`
- Approved commit: `{{APPROVED_COMMIT}}`
- Implementer and fixer agent ids: `{{IMPLEMENTER_AGENT_IDS}}`
- Root orchestrator agent id: `{{ROOT_AGENT_ID}}`
- Specification reviewer agent id: `{{SPEC_REVIEWER_AGENT_ID}}`
- Adversarial reviewer agent id: `{{ADVERSARIAL_REVIEWER_AGENT_ID}}`
- Resolved findings: {{RESOLVED_FINDINGS}}
- Deferred non-blocking suggestions: {{DEFERRED_FINDINGS}}
- Manual review result: {{MANUAL_REVIEW_RESULT}}

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
