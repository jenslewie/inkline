---
workflow_version: 2
task: "{{TASK_NAME}}"
task_kind: "{{TASK_KIND}}"
verdict: "{{REVIEW_VERDICT}}"
prerequisite_commit: "{{PREREQUISITE_COMMIT}}"
candidate_commit: "{{FINAL_CANDIDATE_COMMIT}}"
approved_commit: "{{APPROVED_COMMIT}}"
implementer_agent_ids: "{{IMPLEMENTER_AGENT_IDS}}"
root_agent_id: "{{ROOT_AGENT_ID}}"
spec_reviewer_agent_id: "{{SPEC_REVIEWER_AGENT_ID}}"
adversarial_reviewer_agent_id: "{{ADVERSARIAL_REVIEWER_AGENT_ID}}"
reviewed_at: "{{REVIEWED_AT}}"
---

# Review record: {{TASK_NAME}}

## Review boundary

- Task specification: {{TASK_SPECIFICATION}}
- Authoritative contracts: {{AUTHORITATIVE_CONTRACTS}}
- Accepted upstream artifacts: {{ACCEPTED_UPSTREAM_ARTIFACTS}}
- Regression samples: {{REGRESSION_SAMPLES}}
- Prerequisite commit: `{{PREREQUISITE_COMMIT}}`
- Final candidate commit: `{{FINAL_CANDIDATE_COMMIT}}`

## Agent roles

- Implementer and fixer agent ids: `{{IMPLEMENTER_AGENT_IDS}}`
- Root orchestrator agent id: `{{ROOT_AGENT_ID}}`
- Specification reviewer agent id: `{{SPEC_REVIEWER_AGENT_ID}}`
- Adversarial reviewer agent id: `{{ADVERSARIAL_REVIEWER_AGENT_ID}}`

Reviewers used fresh context and remained read-only with respect to tracked files:
{{REVIEWER_INDEPENDENCE_EVIDENCE}}

## Review rounds

Append each round. Do not remove rejected candidates, findings, or earlier commands.

### Round {{ROUND_NUMBER}}: `{{ROUND_CANDIDATE_COMMIT}}`

#### Specification and contract review

- Reviewer: `{{ROUND_SPEC_REVIEWER_AGENT_ID}}`
- Scope and diff reviewed: {{ROUND_SPEC_SCOPE}}
- Commands and reproducers: {{ROUND_SPEC_COMMANDS}}
- Verdict: `{{ROUND_SPEC_VERDICT}}`
- Findings: {{ROUND_SPEC_FINDINGS}}

#### Adversarial correctness review

- Reviewer: `{{ROUND_ADVERSARIAL_REVIEWER_AGENT_ID}}`
- Scope and diff reviewed: {{ROUND_ADVERSARIAL_SCOPE}}
- Commands and reproducers: {{ROUND_ADVERSARIAL_COMMANDS}}
- Verdict: `{{ROUND_ADVERSARIAL_VERDICT}}`
- Findings: {{ROUND_ADVERSARIAL_FINDINGS}}

#### Finding dispositions and fixes

{{ROUND_FINDING_DISPOSITIONS}}

#### Re-validation

{{ROUND_REVALIDATION}}

## Manual review gate

{{MANUAL_REVIEW_RESULT}}

## Final verdict

- Verdict: `{{REVIEW_VERDICT}}`
- Approved commit: `{{APPROVED_COMMIT}}`
- Unresolved blocking findings: {{UNRESOLVED_BLOCKING_FINDINGS}}
- Deferred non-blocking suggestions: {{DEFERRED_NON_BLOCKING_SUGGESTIONS}}
