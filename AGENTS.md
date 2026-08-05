# Inkline Agent Instructions

These instructions are scoped to this repository and its descendants only.
They do not define behavior for other repositories or global Codex sessions.

## Scope and ownership

1. Work toward one bounded outcome at a time. Do not add adjacent features,
   scripts, dependencies, schemas, migrations, or refactors unless required by
   the accepted outcome.
2. Before editing, the root records a concise task contract: outcome, allowed
   files or directories, acceptance criteria, verification, and out-of-scope
   items.
3. The root owns user communication, scope, orchestration, integration, final
   acceptance, and delivered commits.
4. Preserve unrelated worktree changes. Never reset, revert, overwrite, clean,
   stage, or commit files outside the accepted scope.
5. Stop when the acceptance boundary is complete. Ask before expanding scope or
   beginning another task.

## Agent roles

Use the profiles under `.codex/agents/`:

- `inkline_explorer`: read-only investigation of contracts, call chains,
  current behavior, and evidence;
- `inkline_worker`: implementation, self-review, and author-owned tests;
- `inkline_reviewer`: independent read-only review of the exact candidate.

Profiles inherit the repository-wide model and reasoning effort from
`.codex/config.toml`. Do not override them or substitute another profile. Spawn
repository profiles with `fork_turns="none"`. Subagents must not commit, amend,
rebase, merge, push, or change branches.

Give each subagent a self-contained task containing the task contract, baseline
commit, authoritative references, and known risks. Reports should normally be
under 1,000 tokens and contain only conclusions, changed files, verification,
findings, blockers, risks, and exact references. Do not return full logs, diffs,
or exploratory notes unless essential.

## Choose the lightest safe workflow

### Direct root change

The root may act directly only for documentation, configuration, metadata, or a
mechanical edit that leaves runtime behavior, public APIs, schemas, canonical
models, parser semantics, EPUB/RAG behavior, cross-module contracts, and test
assertions unchanged.

### Standard code change

1. `inkline_worker` implements the bounded candidate, runs author-owned tests,
   and self-reviews every acceptance criterion before returning. Do not hand off
   a knowingly incomplete candidate merely to obtain reviewer guidance.
2. `inkline_reviewer` performs one comprehensive initial review of the exact
   diff against the baseline and task contract. It reports all currently
   observable findings in one batch and classifies each as `blocking`,
   `non_blocking`, `scope_change`, or `invalid_or_duplicate`.
3. The root triages the batch. Only accepted, in-scope blocking findings drive
   remediation. Non-blocking findings do not keep the loop open. Scope changes
   require user approval before implementation.
4. The worker addresses the complete accepted blocker set in one consolidated
   pass, reruns relevant checks, and responds to every finding with evidence.
5. The same reviewer re-reviews only closure of existing blockers, regressions
   introduced by remediation, and evidence unavailable in the prior review. It
   must not add unrelated pre-existing issues or architectural preferences.
6. A remediation round is one worker pass over the full blocker set followed by
   one reviewer re-review. Individual findings or messages do not count as
   separate rounds.
7. Run at most two remediation rounds. Stop the loop early if the same blocking
   finding repeats without new evidence or resolving it expands the accepted
   scope. A verification-only confirmation with no new code changes is not
   another remediation round.
8. If a blocking finding remains after the second re-review, the root makes and
   records the final ruling from the task contract, authoritative contracts,
   tests, and diff. It may reject unsupported findings, but it must not relabel a
   verified acceptance-criterion breach as non-blocking. Ask the user if the
   ruling changes scope or acceptance criteria; otherwise stop delivery when a
   true blocker remains.
9. Reuse the same worker and reviewer threads for remediation. Do not spawn a
   fresh reviewer unless the prior reviewer failed or became unavailable.

### High-risk or cross-cutting change

Run `inkline_explorer` before the standard loop when work affects canonical
schemas, parser normalization, document structure, note/footnote semantics,
EPUB generation, RAG contracts, multiple subsystems, or an unclear call chain.
The explorer identifies authoritative contracts, current behavior, boundaries,
risks, and exact references. The root must not repeat that investigation.

## Review convergence

1. Review against the accepted task contract and authoritative repository
   contracts, not an idealized redesign.
2. The initial review must be comprehensive. Do not drip-feed independently
   observable findings across successive rounds.
3. A new blocking finding after the initial review is valid only if remediation
   introduced it, prior evidence hid it, or it could not reasonably have been
   observed earlier. Otherwise record it as non-blocking follow-up.
4. Repeated wording is not new evidence. After one evidence-based response from
   worker and reviewer, the root adjudicates before allowing another code change.
5. Ambiguity in the task contract is a scope/design question, not an
   implementation loop. Escalate it once rather than iterating on guesses.
6. Reviewer preferences, speculative future risks, cleanup, and unrelated
   pre-existing defects cannot block delivery unless explicitly required.

## Root orchestration efficiency

1. The root performs baseline, scope, dispatch, acceptance, adjudication, and
   integration only. Once exploration is delegated, do not reread the same
   contracts, call chains, or implementation files without a reported gap.
2. Give the worker one consolidated initial task. Do not send progress nudges or
   incremental requirements unless a blocker or material new evidence appears.
3. While a worker or reviewer runs:
   - do not inspect incomplete edits;
   - do not poll with `git status`, `git diff`, file counts, or `list_agents`;
   - use event-driven waiting when available; otherwise use the longest safe
     bounded wait allowed by the host's responsiveness limits;
   - after timeout, resume waiting without inspection or progress requests.
4. Avoid duplicate agents over the same files. Parallelize only independent,
   non-overlapping tasks.
5. Locate code with targeted search and read only relevant ranges. Do not
   concatenate large files or full logs into one tool result.
6. Compact only at a semantic phase boundary when root context is large and
   substantial orchestration remains, not merely because a new turn starts.

## Verification and commits

1. Verification must match risk and acceptance criteria. Run narrow checks first,
   then broader regression checks when warranted.
2. Report exact commands and results. Never claim a check passed unless run.
3. The reviewer evaluates the candidate diff; the root performs final acceptance.
4. Before committing, the root confirms that the staged candidate and resulting
   commit contain only reviewed, task-owned files. Preserve and leave unstaged
   any unrelated worktree changes.
5. The root creates the implementation commit and reports its exact ID.

## Multi-session development chains

For work that is explicitly split across sequential Codex sessions:

1. Read [`docs/development/session-handoff-workflow.md`](docs/development/session-handoff-workflow.md)
   before changing files.
2. Work directly on `main` unless the user explicitly requests another branch.
3. At the start, verify the branch, current `HEAD`, worktree state, prerequisite
   commit, authoritative contracts, and accepted upstream artifacts.
4. Treat the live code and call chain as authoritative, followed by committed
   contracts, the previous handoff, accepted workspace artifacts, and finally the
   session prompt. Report conflicts before implementing.
5. Keep the session within one named artifact or acceptance boundary. Do not begin
   the next task after finishing the current one.
6. Put user-reviewable outputs under
   `data/outputs/workspace/<task>/<run-id>/`. Do not use temporary directories for
   review artifacts.
7. After validation and the final local commit, write a factual handoff and the next
   session prompt under
   `docs/handovers/session-handoffs/<run-id>/`, using the tracked templates in
   [`docs/templates`](docs/templates/). Handoff artifacts remain local and are not
   committed.
8. The generated next-session prompt must contain the actual result commit and real
   paths, contain no unresolved placeholders, and require the next session to verify
   its baseline before acting.
