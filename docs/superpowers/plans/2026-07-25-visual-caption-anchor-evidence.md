# Visual Caption Anchor Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BookSkeleton anchor evidence exact and materialize visual captions as independently traceable ObservedDocument text observations.

**Architecture:** The MinerU adapter appends caption observations without changing current raw IDs. BookSkeleton consumes them only through exact TOC-title evidence; SectionMap remains unchanged.

**Tech Stack:** Python, pytest, Ruff, Pylint, Pyright.

## Global Constraints

- Do not alter SectionMap or infer section membership.
- Preserve existing observation IDs for source raw observations.
- Do not hard-code book names or caption strings in production code.
- A caption becomes anchor evidence only through an exact ordered TOC match.

---

### Task 1: Exact direct-anchor evidence

**Files:**
- Modify: `packages/inkline-canonical/src/inkline/canonical/book_skeleton/pages.py`
- Modify: `tests/inkline/canonical/book_skeleton/test_book_skeleton_page_selection.py`

- [ ] Write failing tests for a fuzzy page containing title plus body text and for an exact split title; assert only exact ordered IDs are returned.
- [ ] Run the focused tests and observe that fuzzy fallback includes unrelated IDs.
- [ ] Require exact aggregate evidence for direct anchors, preserve evidence order, and deterministically choose the strongest exact same-page candidate.
- [ ] Run focused pytest, Ruff, Pylint; commit `fix(canonical): require exact anchor evidence`.

### Task 2: Independent visual-caption observations

**Files:**
- Modify: `packages/inkline-parser-mineru/src/inkline/parsers/mineru/normalize/observed_shadow.py`
- Modify/Create focused MinerU observed-shadow tests under `tests/inkline/parsers/mineru/`

- [ ] Write failing tests covering table and chart captions: resource survives, appended `caption_text` points at its visual parent, and existing raw observation IDs do not change.
- [ ] Run the focused tests and observe missing caption observations.
- [ ] Append caption observations using precise MinerU-middle caption geometry when available; mark imprecise region-derived captions ineligible for direct anchor use.
- [ ] Run focused pytest, Ruff, Pylint; commit `feat(mineru): materialize visual caption evidence`.

### Task 3: End-to-end reconstruction and regression proof

**Files:**
- Create locally: `data/outputs/workspace/observed/*_observed.json`
- Create locally: `data/outputs/workspace/skeleton/*_skeleton.json`
- Modify: integration tests only if required by a reproducible failing case.

- [ ] Add failing end-to-end fixtures for the four cited visual-caption titles and ordinary caption non-promotion.
- [ ] Rebuild affected books serially using existing raw MinerU inputs and source PDFs.
- [ ] Validate ObservedDocument/Skeleton pairs, direct-anchor exactness, unchanged raw IDs, and all existing focused tests.
- [ ] Run `make check` and `make typecheck`; commit only tracked code/tests/docs, never generated workspace artifacts.
