# Inkline Agent Instructions

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
   `data/outputs/workspace/session-handoffs/<run-id>/`, using the tracked templates
   in [`docs/templates`](docs/templates/).
8. The generated next-session prompt must contain the actual result commit and real
   paths, contain no unresolved placeholders, and require the next session to verify
   its baseline before acting.
