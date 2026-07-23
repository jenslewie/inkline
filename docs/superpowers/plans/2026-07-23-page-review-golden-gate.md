# PageReview Golden Evaluation Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evaluate generated PageReview artifacts against the thirteen verified golden books before publishing any result to workspace.

**Architecture:** A new runner discovers golden book names, invokes the existing PageReview builder into a unique staging root, validates and compares every staging artifact, then publishes only an all-green batch. The existing golden checker remains the single stable-field comparator; the runner orchestrates discovery, staging, reports, and publication.

**Tech Stack:** Python 3.12, existing MinerU PageReview builder, `pytest`, `ruff`, `pylint`.

## Global Constraints

- Golden baseline is `data/outputs/golden/page-review/` and is never modified by evaluation.
- Actual LLM evaluation is opt-in through the existing `--llm` and `--skeleton-llm` switches.
- A failed evaluation must preserve the prior workspace directory.
- All code changes run `pytest`, `ruff`, `pylint`, and `git diff --check`.

---

### Task 1: Golden suite discovery and staging report

**Files:**
- Create: `tools/run_page_review_golden_suite.py`
- Test: `tests/test_page_review_golden_suite.py`

**Interfaces:**
- Produces `discover_golden_books(golden_root: Path) -> list[str]`.
- Produces `evaluate_staged_page_reviews(golden_root: Path, staging_root: Path, books: list[str]) -> dict`.

- [x] Write tests for alphabetical golden discovery, missing staged artifacts, and a stable-field mismatch.
- [x] Implement discovery from `<golden_root>/<book>/<book>_page_review.json` and delegate stable comparison to `check_page_review_golden`.
- [x] Emit a JSON report with one result per book and an aggregate `pass` or `fail` status.

### Task 2: Transactional publish

**Files:**
- Modify: `tools/run_page_review_golden_suite.py`
- Test: `tests/test_page_review_golden_suite.py`

**Interfaces:**
- Produces `publish_staged_page_reviews(staging_root: Path, workspace_root: Path, books: list[str]) -> None`.

- [x] Write tests proving a failed suite never calls publish and a successful suite replaces each workspace book directory while preserving a recoverable backup during rename.
- [x] Implement same-filesystem staging under the workspace root and use rename-with-backup for each book only after all comparisons pass.
- [x] Preserve staging output and report on failure; clean only per-book backups after successful replacement.

### Task 3: Runner CLI and documentation

**Files:**
- Modify: `tools/run_page_review_golden_suite.py`
- Modify: `scripts/generate_page_review.sh`
- Modify: `packages/inkline-canonical/README.md`
- Test: `tests/test_page_review_golden_suite.py`

**Interfaces:**
- CLI accepts `--book` repeatedly for focused evaluation; no `--book` evaluates all golden books.
- CLI accepts raw/PDF roots and forwards existing LLM options to the PageReview builder.

- [x] Write argument parsing tests for full discovery and focused book selection.
- [x] Invoke the existing PageReview pipeline into staging, then evaluate and publish only on all-green results.
- [x] Make the helper shell script call the golden runner instead of deleting workspace output.
- [x] Document focused and full commands, staging paths, and the explicit human-only golden update policy.

### Task 4: Verification

**Files:**
- Test: `tests/test_page_review_golden_suite.py` and existing PageReview focused tests.

- [x] Run focused runner tests.
- [x] Run PageReview tests, `ruff`, `pylint`, and `git diff --check`.
- [x] Run one non-LLM staged smoke evaluation using a fixture or a mocked builder; do not claim a real multimodal golden pass without an authorized model run.
