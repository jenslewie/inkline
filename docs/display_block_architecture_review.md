# Display Block Architecture Review

Use this checklist for any MinerU `display_block` refactor or regression review.

## Invariants

- `display_block` vs `paragraph` classification must be layout/geometry-first.
- Do not use text punctuation, colons, attribution markers, or regex text forms as display classifiers.
- Do not promote a paragraph because the previous block is already `display_block`; continuation needs fresh lane/group geometry.
- Canonical reconciliation must compare canonical bboxes against scaled page/body metrics, not raw `LayoutStats` dimensions.
- Body-tail splitting from a display block needs line/source geometry evidence. Without that evidence, leave it for upstream parsing or manual correction.

## Required Checks

Run the architecture checker:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/check_display_block_architecture.py
```

Run the checker tests:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run pytest tests/test_display_block_architecture.py -q
```

Run the display-focused regression suite:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run pytest \
  tests/test_display_block_architecture.py \
  tests/test_display_block_reconciliation.py \
  tests/test_display_geometry.py \
  tests/test_mineru_text_extraction.py \
  tests/test_mineru_normalize.py \
  tests/test_silk_road_acceptance_checker.py \
  -q
```

Run the normal repo gates:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run ruff check .
git diff --check
```

## Review Procedure

1. Enumerate all display-producing entry points:
   - `make_display_block(...)`
   - `make_flush_right_terminal_block(...)`
   - `normalize/builders.py`, where `DISPLAY_BLOCK` objects are actually constructed
   - direct assignments to `DISPLAY_BLOCK`
   - every module under `reconcile/display_block/`
   - cross-page code that sets display-boundary attrs consumed by display
     reconciliation, such as `display_boundary_after_float_body_resume`
2. Confirm every display-producing module is covered by `tools/check_display_block_architecture.py`.
3. Search display-producing files for text gates:
   - `_ends_with_terminal(...)`
   - `ends_with_terminal_punctuation(...)`
   - `has_attribution_line(...)`
   - `ATTR_RE.match(...)`
   - `.endswith(...)` / `.startswith(...)`
4. Search for propagation and coordinate bugs:
   - `previous_display`
   - `prev_text.rstrip(...)`
   - unscaled `layout.page_*` or `layout.body_*` in canonical reconcile paths.
5. Treat any checker exception as explicit technical debt. Do not rely on implicit omissions from the checker path list.
6. Keep paragraph-merge text logic separate from display classification. For example,
   `cross_page.merge_cross_page_paragraphs()` may use terminal punctuation for
   paragraph continuation, but helpers that set display-boundary attrs must remain
   geometry-only.

## Checker Design Requirements

- The checker must auto-cover all modules under `reconcile/display_block/`.
- The checker must cover normalize display emitters, shared display layout helpers,
  and cross-page display-boundary code, not only the `display_block/` package.
- If a new display-producing module or display-boundary marker is added, add it to
  the checker or document why it is outside display classification.
- Add a failing checker test before adding a new invariant.
- Avoid allowlists unless the exception is documented and covered by tests.
