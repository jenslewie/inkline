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
fixer_agent_ids: "{{FIXER_AGENT_IDS}}"
root_agent_id: "{{ROOT_AGENT_ID}}"
spec_reviewer_agent_id: "{{SPEC_REVIEWER_AGENT_ID}}"
adversarial_reviewer_agent_id: "{{ADVERSARIAL_REVIEWER_AGENT_ID}}"
manual_gate: "{{MANUAL_GATE}}"
terminal_reason: "{{TERMINAL_REASON}}"
worktree_state: "{{WORKTREE_STATE}}"
generated_at: "{{GENERATED_AT}}"
next_task: "{{NEXT_TASK}}"
next_task_kind: "{{NEXT_TASK_KIND}}"
---

# Session handoff: {{TASK_NAME}}

## Outcome

{{OUTCOME}}

## Independent review

- Review record: `{{REVIEW_PATH}}`
- Final verdict: `{{REVIEW_VERDICT}}`
- Approved commit: `{{APPROVED_COMMIT}}`
- Implementer agent ids: `{{IMPLEMENTER_AGENT_IDS}}`
- Fixer agent ids: `{{FIXER_AGENT_IDS}}`
- Root orchestrator agent id: `{{ROOT_AGENT_ID}}`
- Specification reviewer agent id: `{{SPEC_REVIEWER_AGENT_ID}}`
- Adversarial reviewer agent id: `{{ADVERSARIAL_REVIEWER_AGENT_ID}}`
- Resolved findings: {{RESOLVED_FINDINGS}}
- Deferred non-blocking suggestions: {{DEFERRED_FINDINGS}}
- Manual gate: `{{MANUAL_GATE}}`
- Manual review evidence: {{MANUAL_REVIEW_RESULT}}

For `complete`, use `review_verdict: approved`, a real approved commit equal to the
result commit, and `manual_gate: passed|not_required`. A pre-review `blocked` record
uses `review_verdict: not_run`, `review_path: none`, and reviewer ids `none`. A
post-review `blocked` record uses `review_verdict: changes_requested`, retains
`review.md`, and records the actual reviewer ids. Both blocked forms use
`approved_commit: none` and `manual_gate: pending|failed|not_required`.
`superseded` uses `review_verdict: not_applicable`, `review_path: none`, no approved
commit, and reviewer ids `none`. `terminal_reason` must always state why this exact
terminal status is justified.

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
