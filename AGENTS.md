# Inkline Agent Instructions

## Repository scope and agent roles

These instructions are repository-scoped. They apply to every Codex agent working
inside this Inkline repository, including root agents and subagents. They do not
define behavior for unrelated repositories.

For any task that changes tracked implementation, contract, test, or workflow files:

1. The root agent is an orchestrator. It verifies the baseline, defines file
   ownership, dispatches subagents, runs integration checks, creates candidate
   commits, dispatches reviewers, and writes final review and handoff records.
2. Implementer and fixer subagents own all tracked edits. The root agent must not
   make tracked implementation or corrective edits, even for a small task. If an
   appropriate subagent cannot be used, the task remains blocked or is handed to a
   new session; the root must not silently bypass the role boundary.
3. An implementer or fixer cannot approve its own work. The root cannot substitute
   its own review for the required independent review.
4. Code tasks require two fresh-context, read-only, independent reviewer subagents:
   one for specification and contract compliance and a different one for
   adversarial correctness. A documentation-only task may use one fresh-context,
   read-only, independent reviewer covering both phases.
5. Review targets an exact candidate commit. Any later tracked change invalidates
   approval and requires validation, a new candidate commit, and review of that new
   commit.
6. A blocking finding must be assigned to a fixer subagent and then re-reviewed. A
   task cannot be called complete while a required check is unavailable, a blocking
   finding is unresolved, or a manual review gate is pending.
7. Final `complete` status requires a generated `review.md` whose approved commit,
   final-round phase commits and verdicts, zero-blocker count, manual gate, task
   metadata, and mutually exclusive agent identities agree with `handoff.md`, as
   verified by `scripts/validate_session_handoff.py` against the repository's real
   commit graph and current `HEAD`. The root, implementer, and each required reviewer
   must be real agent identities; `fixer_agent_ids` may be `none` when no fix round
   occurred. A `complete` handoff must declare and actually have a clean tracked
   index and worktree.
8. `handoff.md` is generated only for terminal status `complete`, `blocked`, or
   `superseded`. Review workflow states such as `ready_for_review` belong in
   `review.md`, never in handoff status. If review must continue in another session,
   use `docs/templates/review-session-prompt.md`; do not fabricate a terminal
   handoff. A pre-review blocker is recorded as `not_run` without reviewer evidence.
   A post-review blocker is `changes_requested` and retains every phase that ran;
   a phase that did not run or was unavailable records commit and reviewer as `none`.
   A task superseded after review started uses review verdict `superseded` and
   retains the same partial-review evidence instead of pretending review never ran.
9. Every recorded review round heading uses exactly
   "### Round N: `<40-character-commit>`" outside fenced code blocks. Round numbers
   are contiguous from 1, every round commit is a real commit object, and the final
   round names the terminal candidate.
10. Terminal workflow records must live below the current repository's
    `docs/handovers/session-handoffs/` directory without symlinked run directories,
    repository-relative parent directories, or record files. `review_path: none`
    requires `review.md` to be absent; `next_task: none` requires
    `next-session-prompt.md` to be absent.

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
7. After implementation validation, commit a candidate and complete the independent
   review gate defined by the workflow document. Do not treat the candidate commit
   as accepted before review.
8. After approval of the exact final local commit, write a factual review record and
   terminal handoff under
   `docs/handovers/session-handoffs/<run-id>/`, using the tracked templates in
   [`docs/templates`](docs/templates/). Write a next-session prompt when `next_task`
   is not `none`; omit it when no next task exists. A blocked or superseded terminal
   handoff instead requires an executable recovery or diagnosis prompt.
9. The generated next-session prompt must contain the actual result commit and real
   paths; for `complete` it must also contain the approved review metadata. It must
   contain no unresolved placeholders and require the next session to verify its
   baseline before acting.
10. Before reporting `complete`, run:

    ```bash
    uv run python scripts/validate_session_handoff.py \
      docs/handovers/session-handoffs/<run-id>/ \
      --expected-commit <approved-commit>
    ```
