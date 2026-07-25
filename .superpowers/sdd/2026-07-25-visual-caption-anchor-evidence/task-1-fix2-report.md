# Task 1 Fix Round 2 Report: Exact Direct Evidence Boundary

## Scope

- Fixed Task 1 only.
- Did not modify Task 2 or SectionMap.
- Preserved ordinary printed-offset resolution, split-title direct evidence, and
  exact direct anchors.

## Root cause

The first fix limited direct page selection to exact candidates, but
`add_printed_page_offset_candidates()` deliberately adds a predicted page back
to the selection list. If that predicted page also has a fuzzy body-text
locator candidate, `_attach_direct_anchors()` accepted that candidate without
requiring exact aggregate evidence. It therefore emitted a high-confidence
`observed_title_match` anchor instead of the medium-confidence
`printed_page_offset` anchor.

The observed-document validator repeated the same boundary error: it compared
the supplied IDs to `title_observation_ids`, which is the locator fallback ID
list when an exact aggregate is absent. A crafted direct anchor could therefore
claim fuzzy body observations as direct title evidence.

## TDD RED evidence

Added focused repro tests:

- `test_build_book_skeleton_uses_printed_offset_for_predicted_page_with_fuzzy_body_text`
- `test_validate_book_skeleton_against_observed_rejects_fuzzy_direct_anchor_ids`

The fixture has exact direct supports at physical pages 15 and 43, both with
printed offset `+12`, and predicts the middle entry on page 27. Page 27 has
only fuzzy body text (`主教座堂导览的开场正文`) plus unrelated body text; neither
individual observation nor their ordered aggregate is an exact title match.

Before the production edit:

```console
UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run pytest -q \
  tests/inkline/canonical/book_skeleton/test_book_skeleton_page_selection.py

6 failed, 12 passed in 0.07s
```

The new builder repro received `observed_title_match`, `high`, and fallback
title IDs `['obs000004', 'obs000005']` instead of an offset anchor. The new
validator repro did not raise for that crafted direct anchor. The four existing
printed-offset checks using the same fixture also failed for the same incorrect
method selection.

## Minimal fix

- `_attach_direct_anchors()` now requires a non-null
  `exact_title_observation_ids` before publishing `observed_title_match`.
  A selected printed-offset prediction with only a fuzzy locator is left for
  `_attach_printed_offset_anchors()`, which emits empty title IDs, two supports,
  and medium confidence.
- `_validate_anchor_evidence_semantics()` now requires exact evidence and
  compares direct anchor IDs to the exact ordered aggregate list, never the
  fallback locator IDs.

## GREEN verification

```console
UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run pytest -q \
  tests/inkline/canonical/book_skeleton/test_book_skeleton_page_selection.py
18 passed in 0.03s

UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run pytest -q \
  tests/inkline/canonical/book_skeleton
112 passed in 0.43s

UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run ruff check \
  packages/inkline-canonical/src/inkline/canonical/book_skeleton/pages.py \
  packages/inkline-canonical/src/inkline/canonical/book_skeleton/validation.py \
  tests/inkline/canonical/book_skeleton/test_book_skeleton_page_selection.py
All checks passed!

UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run ruff format --check \
  packages/inkline-canonical/src/inkline/canonical/book_skeleton/pages.py \
  packages/inkline-canonical/src/inkline/canonical/book_skeleton/validation.py \
  tests/inkline/canonical/book_skeleton/test_book_skeleton_page_selection.py
3 files already formatted

UV_CACHE_DIR=/private/tmp/inkline-uv-cache PYLINTHOME=/private/tmp/inkline-pylint \
  uv run pylint \
  packages/inkline-canonical/src/inkline/canonical/book_skeleton/pages.py \
  packages/inkline-canonical/src/inkline/canonical/book_skeleton/validation.py \
  tests/inkline/canonical/book_skeleton/test_book_skeleton_page_selection.py
Your code has been rated at 10.00/10
```

## Pylint baseline

The wider focused Pylint invocation also includes the existing
`tests/inkline/canonical/book_skeleton/test_book_skeleton.py` module-size
warning: `C0302: Too many lines in module (1912/1000)`. It is pre-existing and
unrelated to this change; no other Pylint finding was reported.
