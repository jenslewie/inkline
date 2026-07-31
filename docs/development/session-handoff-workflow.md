# Cross-session Development Handoff Workflow

**Status:** Active

**Applies to:** Sequential Inkline development tasks executed across multiple Codex
sessions

## Purpose

Long implementation chains must not depend on an old conversation remaining in
context. Each session is bounded by one named artifact or acceptance gate, records
the facts it established, and produces an executable prompt for the immediately
following session.

This workflow separates:

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
- `docs/templates/session-handoff.md`
- `docs/templates/next-session-prompt.md`

Per-session results are local review artifacts and are not committed:

```text
data/outputs/workspace/session-handoffs/<run-id>/
├── handoff.md
└── next-session-prompt.md
```

Use a sortable run id such as:

```text
2026-07-31T153000-contract-freeze
```

All other user-reviewable outputs belong under:

```text
data/outputs/workspace/<task>/<run-id>/
```

Do not place review artifacts in `/private/tmp`. Temporary caches and test
intermediates that the user is not expected to inspect may still use temporary
directories.

## Session lifecycle

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

### 2. Execute one bounded task

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

Downstream consumers must not mutate upstream artifacts. If implementation reveals
that an upstream declaration is wrong, report the contract defect instead of hiding
the repair downstream.

### 3. Validate and commit

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

The final commit hash, not the pre-task hash, is the baseline for the next session.

### 4. Generate the handoff

After the final commit, instantiate `docs/templates/session-handoff.md` in the
session-handoff run directory using `apply_patch`, and replace every placeholder with
a verified value.

The handoff records at minimum:

- task name and status;
- branch and prerequisite commit;
- result commit;
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

Do not report `complete` merely because changes were committed.

### 5. Generate the next-session prompt

After writing the handoff, instantiate `docs/templates/next-session-prompt.md` beside
it using `apply_patch`, and replace all placeholders.

The generated prompt must:

1. point to the exact handoff path;
2. name the actual result commit;
3. name every authoritative contract and accepted input artifact;
4. state one next task and its boundary;
5. reproduce unresolved issues that affect that task;
6. require live baseline and call-chain verification;
7. define validation and output paths;
8. forbid starting the following task;
9. contain no unresolved `{{PLACEHOLDER}}` tokens.

For a `blocked` handoff, generate a recovery or diagnosis prompt rather than an
implementation prompt. For a terminal task with no agreed successor, set
`next_task: none` in the handoff and do not invent more work.

Validate generated files before finishing:

```bash
rg -n '\{\{[A-Z0-9_]+\}\}' \
  data/outputs/workspace/session-handoffs/<run-id>/
```

The command must return no matches.

## Starting the next session

The user can paste `next-session-prompt.md` into a new conversation without copying
the old conversation. The new session must still read the referenced handoff,
contracts, and artifacts and verify the repository state before acting.

If `HEAD` has advanced:

- when the recorded result commit is still an ancestor, inspect every intervening
  commit and refresh the task baseline before editing;
- when it is not an ancestor, treat the prompt as stale and stop for reconciliation.

## Workflow changes

Changes to this workflow or its templates are normal repository changes. Update them
through a focused commit. Generated handoffs remain local workspace artifacts and
must not be promoted into contracts merely because a previous session wrote them.
