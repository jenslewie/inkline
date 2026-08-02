# Review-Gated Task Workflow Design

**Status:** Approved for repository-level implementation

**Date:** 2026-08-02

## Problem

Inkline's cross-session workflow currently requires baseline verification,
implementation, automated validation, a local commit, and a handoff. It does not
require an independent review before the task is marked `complete`.

That omission allows an implementation session to use its own tests as both the
work product and the acceptance decision. The BookGraph upstream contract-freeze
task demonstrated the failure mode: the native suite passed, but a later independent
adversarial review found contract, provenance, reverse-coverage, scope, and nested
immutability defects.

The workflow must distinguish "implemented and tested by its author" from
"independently reviewed and accepted". A task is complete only after both are true.

## Goals

- Make independent review a mandatory, blocking completion gate.
- Keep one user-visible Codex task as the normal unit of work.
- Allow the root agent to delegate bounded implementation work to subagents.
- Isolate reviewers from implementation reasoning and assumptions.
- Require both specification compliance and adversarial correctness review for code
  tasks.
- Persist the exact reviewed commit, findings, fixes, and final verdict.
- Invalidate approval whenever tracked implementation changes after review.
- Prevent the next artifact task from starting before the current task is approved.

## Non-goals

- This design does not repair the six open BookGraph contract findings.
- It does not require a separate user-visible conversation for every review.
- It does not replace user-required manual artifact checkpoints such as SectionMap
  Task 4.
- It does not require multiple implementation subagents when one bounded implementer
  is sufficient.
- It does not claim that review proves the software is free of all defects. Review
  proves that the declared scope and acceptance boundary passed the required gates.

## Chosen Approach

Use one user-visible task with a root orchestrator, bounded implementer or fixer
subagents, and independent reviewer subagents. Review is a state transition with the
authority to reject completion, not an advisory message appended after the task has
already been declared complete.

Two separate user-visible tasks remain an escalation path for context exhaustion,
user decisions, manual artifact review, or unusually large release boundaries. They
are not the default mechanism for reviewer independence.

## Roles

### Root orchestrator

The root agent owns the task boundary and workflow state. It:

- verifies the baseline and authority order;
- states the single objective, owned decisions, non-goals, and acceptance gate;
- decomposes implementation only where the subtasks have non-overlapping ownership;
- prevents concurrent writes to overlapping files;
- runs integration validation and produces a candidate commit;
- dispatches independent reviewers against an exact commit;
- routes blocking findings to a fixer;
- refuses to mark the task complete until the final review verdict is `approved`;
- writes the final review record, handoff, and next-session prompt.

The root agent does not edit tracked implementation, contract, test, or workflow
files. All such edits, including review fixes, belong to implementer or fixer
subagents. This strict separation applies even to small tasks. The root may write
generated local review and handoff records after approval because those files are
ignored task records rather than changes to the reviewed product commit.

If an appropriate subagent cannot be used, the task remains blocked or is handed to
a separate user-visible session. The root does not silently relax the role boundary.

### Implementer and fixer subagents

An implementer receives only the bounded subtask, authoritative interfaces,
constraints, tests, and file ownership it needs. A fixer receives an accepted review
finding and the evidence needed to reproduce it. They may edit files and run tests.

Independent subtasks may run concurrently only when they do not modify shared files
or depend on one another's uncommitted state. Overlapping work runs sequentially.

Implementers and fixers may produce `ready_for_review`; they cannot produce the
final `complete` state.

### Reviewer subagents

Reviewers are read-only with respect to tracked repository files. They receive a
fresh context containing:

- the exact prerequisite and candidate commits;
- the task specification and authoritative contracts;
- accepted upstream artifacts and regression samples;
- the declared validation requirements;
- the diff or commit range to review.

They do not inherit the implementation conversation. Their prompt must not contain
the implementer's defense of design choices or a claim that passing tests imply
correctness. Reviewers inspect the live repository and may run tests or create
temporary, untracked reproducers. They report findings to the root agent and do not
silently repair code.

## Review Phases

### Specification and contract review

This reviewer checks whether the candidate implements the complete declared task:

- dependencies, inputs, outputs, and public contracts agree;
- ownership and non-goals are respected;
- every required state, especially failure and unresolved states, is representable;
- documentation, schema, implementation, and tests do not contradict one another;
- no required acceptance item is missing merely because the current tests pass.

### Adversarial correctness review

This reviewer actively looks for invalid states that positive-path tests may accept:

- dangling or fabricated ids and provenance;
- missing reverse coverage and partition checks;
- mutation of supposedly immutable upstream artifacts;
- invalid cross-artifact combinations;
- scope leakage and ambiguous ancestor or range logic;
- stale, missing, or unverified assets;
- regressions outside focused tests;
- test assertions that restate the implementation instead of the contract.

Code tasks require both phases, performed by two different reviewer subagents so the
second review is not anchored by the first review's conclusions. A documentation-only
task may use one independent reviewer that performs both phases.

User-mandated manual artifact review remains an additional gate after automated and
agent review; it is never replaced by them.

## State Machine

The task lifecycle is:

```text
in_progress
-> ready_for_review
-> approved
-> complete
```

When a reviewer finds an actionable defect within the task's acceptance boundary:

```text
ready_for_review
-> changes_requested
-> in_progress
-> ready_for_review
```

Additional terminal states remain:

- `blocked`: the task cannot pass without a user decision, new authority, or an
  unavailable prerequisite;
- `superseded`: the task or governing contract was replaced before acceptance.

Terminal records use explicit approval semantics. `complete` carries the approved
review path and commit. A pre-review `blocked` record carries `not_run` and no review
identity; a post-review `blocked` record carries `changes_requested` and retains the
review evidence and the identities of phases that actually ran. A pre-review
`superseded` record carries `not_applicable` and no review identity; a task superseded
after review began carries `superseded` and retains partial review evidence.
Non-complete states have no approved commit, must explain `terminal_reason`, and must
provide an executable `recovery` or `diagnosis` successor prompt. Active
`ready_for_review` work has no handoff at all; it continues through the review-only
prompt contract.

`ready_for_review`, `changes_requested`, and `approved` are review workflow states.
Only `complete`, `blocked`, and `superseded` are final handoff statuses.

## Candidate Commit and Approval Identity

Review always targets an exact local commit on `main`, consistent with the existing
direct-main workflow. The review record stores both the prerequisite commit and the
candidate commit.

If a fixer changes any tracked file, the previous approval is invalid. The root
creates a new commit and dispatches re-review against the new exact `HEAD`. Passing
tests after a fix do not restore approval automatically.

After approval:

- no tracked implementation or contract file may change before the task handoff;
- generated local review and handoff documents may be written because they do not
  alter the reviewed product commit;
- the approved commit becomes the prerequisite for the next task.

The workflow does not require squashing candidate and corrective commits. The final
reviewed `HEAD` is authoritative.

## Finding Classification and Blocking Rules

Every finding records priority, evidence, affected scope, and disposition.

- A correctness, contract, provenance, data-loss, mutation, or required-test defect
  inside the declared acceptance boundary blocks approval.
- A finding outside the task's owned decisions blocks when it invalidates an input or
  prerequisite. The task then becomes `blocked` or returns to the owning upstream
  task; downstream code may not hide the defect.
- A non-blocking suggestion must not be necessary to satisfy the declared objective.
  It is recorded explicitly and may be deferred without claiming it was fixed.
- A reviewer cannot approve with an unresolved blocking finding.
- The root cannot downgrade a finding merely to finish the session. It must provide
  repository evidence for disagreement and, when ambiguity remains, ask the user.

## Persisted Review Record

Each handoff directory contains:

```text
docs/handovers/session-handoffs/<run-id>/
├── review.md
├── handoff.md
└── next-session-prompt.md
```

`review.md` is a generated local development artifact. It records:

- task name and review status;
- prerequisite commit and every reviewed candidate commit;
- reviewer role and review phase;
- exact contracts, artifacts, and diff range reviewed;
- commands and reproducers used;
- findings with priority and evidence;
- the root's disposition of every finding;
- fix commits and re-review rounds;
- final verdict and approved commit.

The final decision is also machine-readable: `final_round`, each phase's reviewed
commit and verdict, `unresolved_blocking_count`, and `manual_gate`. Both phases must
approve the same final candidate. Narrative review rounds remain append-only, while
the structured final fields summarize the last recorded round for the completion
gate.

The review record is append-only across review rounds. A later approval must not
erase earlier findings or failed candidate commits.

Round headings use exactly "### Round N: `<40-character-commit>`" outside fenced
code blocks. Numbers are
contiguous from 1, each hash must name a commit object, and the final round commit
must equal the candidate and every phase commit that actually ran in that round.

The final `handoff.md` links to `review.md`, names the approved commit, and summarizes
resolved and deferred findings. It may use `status: complete` only when the review
record's final verdict is `approved` for the same commit. Handoff agent fields record
implementers, fixers, root, and both reviewers; those roles are mutually exclusive
except that one documentation reviewer may cover both review phases.

Identities are state-aware. `root_agent_id` and each reviewer field are single
identities rather than lists. `complete` requires a real root, at least one real
implementer, and real required reviewers; fixer ids may be `none`. For an interrupted
post-review terminal record, each phase is `approved|changes_requested` with its
reviewer and candidate commit, or `not_run|unavailable` with reviewer and commit both
`none`. At least one phase must have run.

The next-session prompt names the exact handoff and result commit. For `complete`, it
also names the approved review; for post-review `blocked`, it retains rejection
evidence; pre-review `blocked` and `superseded` use `review_path: none`. It must refuse
a baseline where `HEAD` contains unexplained commits after the recorded result. No
prompt is required for `next_task: none`; otherwise prompt metadata must match the
handoff's successor task and kind.

Terminal records are accepted only from the current repository's
`docs/handovers/session-handoffs/` tree, with no symlinked run directory,
repository-relative parent, or record file. `review_path: none` means `review.md` is
absent; `next_task: none` means the next-session prompt is absent. Every terminal
handoff records non-empty branch, worktree state, and generation time, every retained
review records its review time, and the recorded branch matches the live branch.
Completed tasks additionally require both declared and actual clean tracked index
and worktree state; ignored and untracked local artifacts do not invalidate them.

## Updated Session Lifecycle

The revised lifecycle is:

1. Verify branch, `HEAD`, worktree, prerequisite ancestry, contracts, artifacts, and
   the real call chain.
2. Define one bounded task and its acceptance boundary.
3. Implement with tests, using bounded subagents where useful.
4. Run focused and integration validation.
5. Inspect scope and commit the candidate directly to local `main`.
6. Mark the task `ready_for_review` and dispatch fresh-context reviewers.
7. Persist reviewer findings in `review.md`.
8. If changes are requested, fix, validate, commit, and repeat review.
9. Run any separately required user manual checkpoint.
10. After approval of the exact final commit, generate the final handoff and next-task
    prompt.
11. Stop without beginning the following task.

## Failure and Recovery

- If a reviewer cannot run a required check, approval is withheld and the missing
  check is recorded.
- If reviewers disagree, the root evaluates both findings against repository
  evidence. An unresolved contract decision is escalated to the user.
- If context or time is insufficient for review, the task remains
  `ready_for_review`; a `prompt_mode: review_only` prompt is generated from
  `docs/templates/review-session-prompt.md`. It grants read-only tracked-file scope,
  is not a terminal handoff, and cannot mark the task `complete`.
- If the candidate commit is no longer an ancestor of `HEAD`, review stops until the
  baseline is reconciled.
- If implementation reveals an upstream contract defect, the current downstream
  task does not repair it. The handoff becomes `blocked` or the upstream task is
  reopened and reviewed.

## Workflow Files to Change During Implementation

The implementation of this design will update:

- `AGENTS.md` to make independent review mandatory for multi-session chains;
- `docs/development/session-handoff-workflow.md` to add roles, states, review rounds,
  invalidation, and escalation;
- `docs/templates/session-handoff.md` to record the review path, verdict, and approved
  commit;
- `docs/templates/next-session-prompt.md` to require review-baseline verification;
- a new tracked `docs/templates/session-review.md` template;
- a new tracked `docs/templates/review-session-prompt.md` template;
- focused documentation tests or validation scripts that reject `complete` handoffs
  without matching approval evidence and reject unresolved placeholders.

The implementation will not repair BookGraph contracts. Those corrections form the
first product task executed under the new review-gated workflow.

## Repository Scope

This workflow is defined by the root `AGENTS.md` and tracked files in this repository.
It governs Codex work performed in Inkline but does not change Codex behavior in other
repositories. A more specific nested `AGENTS.md` may add local constraints but must
not weaken this repository's independent-review completion gate.

## Acceptance Criteria

The workflow change is complete only when:

- repository instructions forbid an implementation agent from self-approving;
- code tasks require specification and adversarial review;
- reviewer context isolation and read-only behavior are explicit;
- review findings create a mandatory fix-and-re-review loop;
- approval is tied to an exact commit and invalidated by later tracked changes;
- `review.md` has a tracked template and a defined location;
- handoff `status: complete` requires a matching approved review record;
- next-session prompts validate the approved commit and review path;
- blocked, superseded, manual-review, and separate-session escalation paths are
  documented;
- the validator checks real Git commits, ancestry, expected commit, and current
  `HEAD`, plus symlink/path safety and structured final-round approval;
- changed documentation links and placeholders pass automated checks;
- the workflow itself receives an independent review before its implementation task
  is marked complete.
