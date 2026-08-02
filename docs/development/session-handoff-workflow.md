# Cross-session Development Handoff Workflow

**Status:** Active

**Applies to:** Codex development tasks in this repository, including tasks executed
within one session and sequential tasks handed across sessions

## Purpose

Long implementation chains must not depend on an old conversation remaining in
context. Each session is bounded by one named artifact or acceptance gate, records
the facts it established, and produces an executable prompt for the immediately
following session.

This workflow separates:

- **independent acceptance evidence**, recorded in `review.md`;
- **facts**, recorded in `handoff.md`; and
- **instructions**, recorded in `next-session-prompt.md`.

A prompt is not a substitute for a handoff. It may direct the next session to inspect
facts, but it must not silently turn assumptions into facts.

## Authority order

When sources disagree, use this order:

1. live repository code and the actual runtime call chain;
2. committed architecture, schema, and contract documents;
3. the previous session's `handoff.md`;
4. accepted artifacts under `data/outputs/workspace/`;
5. the current session prompt;
6. earlier conversation text.

Do not continue implementation through an unexplained conflict. Record the conflict,
inspect the live state, and either reconcile the source of truth within the current
task's authority or stop with a recovery handoff.

## Persisted and generated files

The workflow itself is version controlled:

- `AGENTS.md`
- `docs/development/session-handoff-workflow.md`
- `docs/templates/session-review.md`
- `docs/templates/session-handoff.md`
- `docs/templates/next-session-prompt.md`
- `docs/templates/review-session-prompt.md`

Per-session results are local review artifacts and are not committed. During review,
the run directory may contain only `review.md` and an optional review-only prompt.
`handoff.md` is created only after the task reaches a terminal state:

```text
docs/handovers/session-handoffs/<run-id>/
├── review.md
├── handoff.md
└── next-session-prompt.md
```

This full layout describes `complete` with a successor and any terminal task after
review has started. A pre-review `blocked` or `superseded` directory has no
`review.md`. `review_path: none` requires that file to be absent. For
`next_task: none`, omit `next-session-prompt.md`; an existing prompt is an error. For
a task that must move its
still-active review to another session, instantiate
`docs/templates/review-session-prompt.md`; that prompt is not a handoff and does not
authorize terminal status. It belongs only to an active `ready_for_review` state and
may coexist with `review.md`, but never with terminal `handoff.md`. Remove it before
writing a `complete`, `blocked`, or `superseded` handoff; the terminal validator
rejects any leftover `review-session-prompt.md` for all three statuses.

Use a sortable run id such as:

```text
2026-07-31T153000-contract-freeze
```

Book-processing data, acceptance reports, and other user-reviewable data outputs
belong under:

```text
data/outputs/workspace/<task>/<run-id>/
```

Do not mix session handoffs into the data workspace. Do not place any review
artifacts in `/private/tmp`. Temporary caches and test intermediates that the user is
not expected to inspect may still use temporary directories.

## Roles and separation of authority

### Root orchestrator

The root agent owns orchestration, not tracked implementation edits. It verifies the
baseline, defines the task boundary and file ownership, dispatches implementer and
fixer subagents, runs integration checks, creates candidate commits, dispatches
reviewers, evaluates findings against repository evidence, and generates final local
records.

The root must not edit tracked implementation, contract, test, or workflow files,
including small fixes. If no suitable subagent is available, the task is `blocked` or
is handed to a separate user-visible session.

### Implementers and fixers

Implementer subagents own bounded, non-overlapping tracked changes. Fixer subagents
own changes required by accepted review findings. They may report
`ready_for_review`, but they cannot approve or complete their own work. Concurrent
subagents must not write the same files or rely on one another's uncommitted state.

### Reviewers

Reviewers are read-only with respect to tracked repository files. They receive fresh
context rather than the implementation conversation, and their prompt contains the
exact prerequisite and candidate commits, task specification, authoritative
contracts, accepted artifacts, regression samples, and validation requirements. It
must not contain an implementer's defense or assert that passing tests proves
correctness.

Code tasks require two different independent reviewer subagents:

1. a specification and contract reviewer; and
2. an adversarial correctness reviewer.

A documentation-only task may use one independent reviewer covering both phases.
No reviewer may be an implementer or fixer for the candidate under review. The root's
own inspection and validation do not replace an independent review.

Agent identity fields are state-aware. `root_agent_id` and each reviewer id are
single scalar identities, never comma-separated lists. A completed task requires at
least one real implementer plus a real root, specification reviewer, and adversarial
reviewer; fixer ids may be `none` when no finding required a fix. A phase with verdict
`not_run` or `unavailable` has reviewer id `none`. All identities are mutually
exclusive except that one documentation reviewer may cover both review phases.
`implementer_agent_ids` and `fixer_agent_ids` are exactly `none` or a
comma-separated list of non-empty, unique identities. Empty entries, leading or
trailing commas, repeated identities, and mixing `none` with a real identity are
invalid in every workflow state, including optional pre-review implementers and a
no-fix completed task.

## Task lifecycle

### 1. Verify the baseline

Before editing:

```bash
git status --short --branch
git log -1 --oneline
git diff --stat
git diff --name-status
```

Then:

1. confirm that the current branch is `main`, unless the user explicitly requested
   otherwise;
2. confirm whether the worktree is clean;
3. verify that the prerequisite commit named by the prompt exists;
4. verify that the prerequisite commit is the expected `HEAD`, or inspect and explain
   every intervening commit;
5. open every authoritative contract and accepted-artifact path named by the prompt;
6. trace the real implementation entry point and downstream call chain.

If the prerequisite commit is not an ancestor of `HEAD`, the task baseline is
invalid. Do not implement against it. Produce a recovery report or ask for direction
when the mismatch cannot be resolved from the repository.

If unrelated worktree changes exist, preserve them. Do not overwrite, discard,
reformat, stage, or commit them as part of the current task.

### 2. Define and execute one bounded task

Every session prompt must define:

- one task name;
- one primary artifact or acceptance boundary;
- authoritative inputs;
- owned decisions;
- decisions the task must not own;
- explicit non-goals;
- accepted regression samples;
- required automated and manual validation;
- the stop condition.

Do not begin the next planned artifact merely because the current task finishes
early. The next task starts in the next session using the generated prompt.

The root delegates every tracked edit to implementer subagents with explicit file
ownership. A subagent that discovers work outside its boundary reports it rather than
editing unowned files. The root preserves unrelated worktree changes and serializes
tasks that would otherwise overlap.

Downstream consumers must not mutate upstream artifacts. If implementation reveals
that an upstream declaration is wrong, report the contract defect instead of hiding
the repair downstream.

### 3. Validate and commit a candidate

Run the checks appropriate to the actual change. Inkline code changes normally
require focused tests, Ruff, Pylint, and Pyright; meaningful cross-package changes
also require the full test suite. Documentation-only changes require at least link
and path inspection plus `git diff --check`.

Before committing:

```bash
git diff --check
git diff --cached --stat
git diff --cached --name-status
```

Stage only the files owned by the current task. Commit directly to `main` using a
functional Conventional Commit message. Do not push unless the user explicitly
asks.

After committing, capture:

```bash
git log -1 --oneline
git status --short --branch
```

This commit is only a candidate. It is not the next session's accepted baseline until
the independent review gate approves this exact commit.

### 4. Review the exact candidate

Set workflow state to `ready_for_review`. Instantiate
`docs/templates/session-review.md` as `review.md` in the run directory and append one
entry per review round. Do not create `handoff.md` yet. Never erase an earlier
rejected candidate or finding.

Every round heading is canonical and commit-bound:

```text
### Round 1: `<exact-40-character-commit>`
```

Round numbers are contiguous from 1. The validator ignores examples inside fenced
code blocks, rejects every other `### Round` form, checks each hash is a commit object
rather than a tag or another Git object, and requires the final heading to name the
structured final candidate and all phases that actually ran in that final round.
Fence detection follows the CommonMark boundary needed here: an opener or closer is
indented by at most three spaces, uses at least three matching backticks or tildes,
and a closer uses the same character with length at least that of its opener. Thus a
three-backtick line cannot close a four-backtick fence, while a four-space-indented
pseudo-fence cannot hide a real review-round heading.

Dispatch reviewer subagents with fresh context and read-only tracked-file authority.
The specification reviewer checks completeness against the task and contracts. The
adversarial reviewer constructs negative cases and looks for invalid states, missing
coverage, mutation, provenance errors, scope leakage, stale assets, weak assertions,
and regressions outside the focused tests.

Every finding records priority, evidence, affected scope, and disposition. A
correctness, contract, provenance, data-loss, mutation, or required-test defect in
scope blocks approval. An upstream defect that invalidates the task input also
blocks; downstream code must not hide it.

The review state machine is:

```text
in_progress -> ready_for_review -> approved -> complete
```

Blocking findings force the loop:

```text
ready_for_review -> changes_requested -> in_progress -> ready_for_review
```

The root assigns accepted findings to a fixer subagent, re-runs validation, and
creates a new candidate commit. Any tracked change invalidates every earlier
approval. Both review phases must review the new exact commit before it may be
approved; passing tests do not restore approval.

If reviewers disagree, the root compares both claims to repository evidence. It may
reject a finding only with recorded evidence. An unresolved contract decision is
escalated to the user and approval is withheld.

If review cannot fit safely in the current session, instantiate
`docs/templates/review-session-prompt.md` and leave the review state
`ready_for_review`. The prompt uses `prompt_mode: review_only`, names the exact
candidate and one review phase, and grants no tracked-file write authority. Do not
generate `handoff.md` or mark the task `complete`. When the task becomes terminal,
delete the review-only prompt before creating `handoff.md`; the two records are
mutually exclusive.

User-mandated manual inspection is an additional blocking gate. It runs after
automated and agent review at the point declared by the task, and cannot be replaced
by either. A task with pending manual review remains incomplete.

### 5. Generate the handoff

Instantiate `docs/templates/session-handoff.md` only when the session reaches one of
the terminal statuses below. For `complete`, this occurs after approval of the exact
final commit and any required manual gate. Use `apply_patch` and replace every
placeholder with a verified value.

The handoff records at minimum:

- task name and status;
- branch and prerequisite commit;
- result commit;
- task kind and root/implementer/fixer agent ids;
- specification and adversarial reviewer agent ids;
- review path, final verdict, and approved commit;
- manual gate state and terminal reason;
- final worktree state;
- authoritative contracts;
- changed files and owned behavior;
- accepted artifacts;
- exact validation commands and results;
- regressions checked;
- unresolved issues and risks;
- the next task and its prerequisites.

Statuses are:

- `complete`: the task passed its declared gate;
- `blocked`: the task did not pass and cannot continue safely;
- `superseded`: the planned task or contract was replaced before completion.

`complete` requires `review.md` to name the same task, task kind, prerequisite,
implementer/fixer/reviewer identities, and exact commit. Its structured final round
must record both required phases as `approved` for the same final candidate,
`unresolved_blocking_count: 0`, and `manual_gate: passed|not_required`. Its
`worktree_state` must be `clean`, and the validator independently rejects staged or
unstaged tracked changes while ignoring untracked and ignored local artifacts.

Pre-review `blocked` uses `review_verdict: not_run`, `review_path: none`, and reviewer
ids `none`. Post-review `blocked` uses `review_verdict: changes_requested`, retains
the append-only `review.md`, and records actual evidence for every phase that ran.
Each phase is either `approved|changes_requested` with its reviewer and the result
candidate, or `not_run|unavailable` with commit and reviewer both `none`; at least one
phase must have run. It has a positive `unresolved_blocking_count`. Both phases may
be approved when `terminal_reason` identifies a separate user or manual blocker.

A pre-review `superseded` task uses `review_verdict: not_applicable`,
`review_path: none`, and reviewer ids `none`. If supersession happens after review
started, it uses `review_verdict: superseded`, retains `review.md`, records the same
run/unrun phase evidence, and may have a zero blocking count because replacement—not
a defect—ended the task. All non-complete forms use `approved_commit: none`, a
non-empty `terminal_reason`, and an executable successor (`recovery` for blocked,
`diagnosis` for superseded). Their `result_commit` records the real current `HEAD`,
not an approved product baseline.
Do not report `complete` merely because changes were committed or tests passed.

### 6. Generate the next-session prompt

When `next_task` is not `none`, instantiate
`docs/templates/next-session-prompt.md` beside the terminal handoff using
`apply_patch`, and replace all placeholders. When `next_task: none`, also set
`next_task_kind: none` and omit the prompt.

The generated prompt must:

1. point to the exact handoff path;
2. for `complete`, name the approved result commit and final review path; for
   `blocked` or `superseded`, name the unapproved current result and reproduce its
   review path (`review.md` after a real blocked review, otherwise `none`);
3. require the next root agent to use the repository's strict subagent roles;
4. name every authoritative contract and accepted input artifact;
5. state one next task and its boundary;
6. reproduce unresolved issues that affect that task;
7. require live baseline and call-chain verification;
8. define validation and output paths;
9. forbid starting the following task;
10. contain no unresolved `{{PLACEHOLDER}}` tokens.

The prompt front matter includes the exact `handoff_path` and must reproduce the
handoff's workflow version, previous task, `next_task`, `next_task_kind`, result
commit, review path, and verdict. Prompt modes are fixed by terminal status:

- `complete -> implementation`;
- `blocked -> recovery`;
- `superseded -> diagnosis`.

For a `blocked` handoff, generate a recovery prompt; for `superseded`, generate a
diagnosis prompt. Only a `complete` terminal task with no agreed successor may set
`next_task: none` and omit the prompt; blocked and superseded records must name the
task that can resolve or replace them.

Validate generated files before finishing. This command is a mandatory completion
gate, not an optional lint:

```bash
uv run python scripts/validate_session_handoff.py \
  docs/handovers/session-handoffs/<run-id>/ \
  --expected-commit <result-commit>
```

`--expected-commit` is required. The command finds the enclosing Git repository and
must exit zero. For `complete`, the result commit is also the approved commit. For
`blocked` and `superseded`, it is the current unapproved `HEAD` recorded by the
terminal handoff. The validator rejects unresolved placeholders, nonterminal or
unknown handoff statuses, missing successor prompts, symlinked records, path escape,
stale review evidence, overlapping or state-inappropriate roles, incomplete or
noncanonical final-round metadata, non-approved manual gates, nonexistent or
non-commit Git objects, invalid ancestry, a result different from the supplied commit
or current `HEAD`, branch drift, and cross-file metadata mismatches. It accepts only
terminal run directories below the current repository's
`docs/handovers/session-handoffs/` root and rejects a symlinked run directory, any
repository-relative symlinked parent, and symlinked record files. Every terminal
handoff has non-empty `branch`, `worktree_state`, and `generated_at`; every retained
review has non-empty `reviewed_at`.

This validator is a static consistency gate. It cannot prove that an agent id maps to
the claimed process, that reviewer context was genuinely fresh, that a reviewer was
actually read-only, that narrative findings are exhaustive, or that a human really
performed a declared manual inspection. Agent transcripts and recorded evidence
remain necessary for those claims; the validator deliberately does not parse or
over-constrain free-text review prose.

## Starting the next session

The user can paste `next-session-prompt.md` into a new conversation without copying
the old conversation. The new session must still read the referenced handoff,
contracts, and artifacts and verify the repository state before acting.

For `complete`, the next session reads `review.md` as acceptance evidence and verifies
that its approved commit equals the handoff result commit. For post-review `blocked`,
it reads `review.md` as rejection and blocker evidence, not acceptance. A
post-review `superseded` task retains review history as interruption evidence, not
acceptance. Pre-review `blocked` and `superseded` have `review_path: none` and
therefore no review record to consume. In every case, if `HEAD` has advanced:

- when the recorded result commit is still an ancestor, inspect every intervening
  commit and refresh the task baseline before editing;
- when it is not an ancestor, treat the prompt as stale and stop for reconciliation.

For `complete`, even when the approved commit remains an ancestor, any intervening
tracked change that affects the accepted artifact invalidates reuse of that approval
for the altered artifact. For non-complete recovery, intervening commits must be
reconciled against the recorded unapproved result before acting.

## Failure, recovery, and terminal states

- `blocked`: a user decision, missing authority, unavailable prerequisite, required
  check, reviewer, or manual gate prevents approval. Its successor prompt uses
  `prompt_mode: recovery`.
- `superseded`: the task or governing contract was replaced before acceptance.
- A superseded successor prompt uses `prompt_mode: diagnosis` to establish the
  replacement contract and baseline before implementation.
- `complete`: all declared validation, independent reviews, and required manual gates
  approved the exact result commit.

If the candidate is no longer an ancestor of `HEAD`, stop review and reconcile the
baseline. If implementation exposes an upstream contract defect, reopen the upstream
task or block the downstream task. If context is exhausted, preserve factual state
and generate a separate recovery or review prompt instead of weakening the gate.

## Workflow changes

Changes to this workflow or its templates are normal repository changes and are
themselves subject to this review gate. Generated handoffs remain local workspace
artifacts and must not be promoted into contracts merely because a previous session
wrote them.
