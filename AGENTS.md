# Inkline Agent Instructions

These instructions are scoped to this repository and its descendants only.
They do not define behavior for other repositories or global Codex sessions.

## Root agent and subagents

1. The root agent owns scope, user communication, orchestration, integration,
   the final acceptance decision, and the final commit. It must state the
   allowed files and acceptance criteria before making changes.
2. Keep each task bounded to the requested artifact or behavior. Do not add
   scripts, dependencies, schemas, or adjacent features without user approval.
   A single-file documentation or configuration change may be completed directly
   by the root agent without delegation.
3. Delegate by role using the repository profiles under `.codex/agents/`:
   - implementation and author-owned tests: `inkline_worker`;
   - read-only exploration of code, contracts, call chains, and evidence:
     `inkline_explorer`;
   - independent read-only review of a bounded candidate: `inkline_reviewer`.
   Agent profiles must inherit the repository-wide subagent model and reasoning
   effort from `.codex/config.toml`; do not pin either setting in an individual
   profile. Do not silently substitute a built-in or default profile or override
   the configured model or effort level. If the required profile is unavailable,
   stop and report the configuration problem.
4. Code changes require the following implementation-review loop before
   completion:
   - `inkline_worker` implements the bounded change and runs the author-owned tests;
   - `inkline_reviewer` independently reviews the exact candidate and reports its
     findings without editing it;
   - `inkline_worker` evaluates every finding, fixes findings it accepts, and gives
     evidence-based reasons for findings it rejects;
   - `inkline_reviewer` reviews the updated candidate and the worker's responses;
   - after the initial review, run at most two remediation rounds, where one round
     is one worker response or fix followed by one reviewer re-review.
   The root agent orchestrates this loop and does not replace either role. Stop
   the subagent loop early if the same blocking finding is repeated without new
   evidence or resolving it would expand the accepted scope. If any blocking
   finding remains after the second re-review, the root agent must not launch
   another remediation round. The root agent then makes and records the final
   ruling, or asks the user if that ruling would change scope or acceptance
   criteria. Before proceeding, the root agent must confirm that the reviewed
   and accepted commit is the exact commit being delivered.
5. Do not continue into a subsequent task after the current acceptance boundary
   is complete. If the scope or acceptance criteria need to change, stop and ask
   the user.

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
   [`docs/templates`](docs/templates/).
8. The generated next-session prompt must contain the actual result commit and real
   paths, contain no unresolved placeholders, and require the next session to verify
   its baseline before acting.
