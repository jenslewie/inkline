# Phase 3 Text Unit Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first parser-neutral top-down aggregation layer between ObservedDocument observations and BookGraph nodes.

**Architecture:** Phase 3.1 introduces `TextUnit` as an internal shadow builder artifact. `ObservedDocument` remains the parser-neutral observation contract; `TextUnit` groups adjacent compatible observations using only explicit structure, reading order, page, bbox geometry, spacing, and alignment; `BookGraph` is then built from units rather than one node per observation. Existing v1 canonical generation, EPUB, and RAG remain unchanged.

**Tech Stack:** Python 3.11, TypedDict-style dictionaries, pytest, ruff, current `inkline-canonical` package.

---

### Task 1: Add TextUnit Aggregator

**Files:**
- Create: `packages/inkline-canonical/src/inkline/canonical/text_units.py`
- Test: `tests/test_text_units.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove:

```python
def test_adjacent_body_observations_merge_into_one_text_unit() -> None:
    document = make_observed_document(...)
    units, ignored = build_text_units(document)
    assert len(units) == 1
    assert units[0]["unit_type"] == "paragraph"
    assert units[0]["text"] == "First line\nSecond line"
    assert units[0]["observation_ids"] == ["obs000001", "obs000002"]
    assert units[0]["bbox"] == [100, 100, 700, 160]
```

```python
def test_large_vertical_gap_starts_new_text_unit() -> None:
    document = make_observed_document(...)
    units, ignored = build_text_units(document)
    assert [unit["text"] for unit in units] == ["First", "Second"]
```

```python
def test_incompatible_role_hints_do_not_merge() -> None:
    document = make_observed_document(...)
    units, ignored = build_text_units(document)
    assert [unit["unit_type"] for unit in units] == ["heading", "paragraph"]
```

```python
def test_non_text_observations_are_ignored_with_counts() -> None:
    document = make_observed_document(...)
    units, ignored = build_text_units(document)
    assert ignored == {"image_region": 1, "page_marker": 1}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run pytest tests/test_text_units.py -q
```

Expected: import failure because `inkline.canonical.text_units` does not exist.

- [ ] **Step 3: Implement minimal aggregator**

Create `text_units.py` with:

```python
TEXT_UNIT_TYPES = {"heading", "paragraph", "list_item", "footnote"}

def build_text_units(document: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    ...
```

Rules:

- Validate input with `validate_observed_document(document)`.
- Consider only observations that map by explicit `kind`/`role_hint`:
  - `title_text` -> `heading`
  - `body_text` -> `paragraph`
  - `list_text` -> `list_item`
  - `footnote_region` or `footnote_text` -> `footnote`
- Ignore all others and count them by `kind`.
- Merge only adjacent observations when:
  - same `unit_type`
  - same page
  - both have non-null bbox
  - vertical gap is non-negative and at most `max(24, previous_height * 1.5)`
  - left edges differ by at most `max(24, previous_width * 0.08)`
  - horizontal overlap ratio is at least `0.6`
- Never merge headings, list items, or footnotes in Phase 3.1 unless tests later require it.
- Unit fields:
  - `unit_id`
  - `unit_type`
  - `text`
  - `page`
  - `pages`
  - `bbox`
  - `spans`
  - `observation_ids`
  - `role_hints`
  - `attrs`
  - `parser_payloads`

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run pytest tests/test_text_units.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/inkline-canonical/src/inkline/canonical/text_units.py tests/test_text_units.py
git commit -m "feat(canonical): aggregate observed text units"
```

### Task 2: Build BookGraph From TextUnits

**Files:**
- Modify: `packages/inkline-canonical/src/inkline/canonical/observed_bookgraph.py`
- Modify: `packages/inkline-canonical/src/inkline/canonical/__init__.py`
- Test: `tests/test_observed_bookgraph.py`

- [ ] **Step 1: Write failing tests**

Add a test where two adjacent body observations produce one paragraph node:

```python
def test_build_bookgraph_from_observed_uses_text_unit_aggregation() -> None:
    graph = build_bookgraph_from_observed(document_with_two_adjacent_body_observations())
    assert [node["node_type"] for node in graph["nodes"]] == ["paragraph"]
    assert graph["nodes"][0]["text"] == "First line\nSecond line"
    assert graph["nodes"][0]["attrs"]["source_observation_ids"] == ["obs000001", "obs000002"]
    assert graph["evidence"][0]["source_kind"] == "text_unit"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run pytest tests/test_observed_bookgraph.py -q
```

Expected: two paragraph nodes are produced because the builder still maps one observation to one node.

- [ ] **Step 3: Modify builder**

Change `build_bookgraph_from_observed()` to call `build_text_units(document)` and generate nodes/evidence from units.

Preserve existing behavior:

- heading -> heading with `level=1`
- paragraph -> paragraph
- list_item -> list_item
- footnote -> footnote
- ignored counts now combine aggregator ignored counts under `metadata.shadow_ignored_observation_counts`
- `appears_on_page`, `reading_order`, `epub_flow`, and `rag_units` still work

Evidence:

- `source_kind="text_unit"`
- `source_id=unit["unit_id"]`
- `bbox`, `spans`, `page/pages` from unit
- `parser_payload={"observation_ids": [...], "parser_payloads": [...]}`

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run pytest tests/test_text_units.py tests/test_observed_bookgraph.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/inkline-canonical/src/inkline/canonical/observed_bookgraph.py packages/inkline-canonical/src/inkline/canonical/__init__.py tests/test_observed_bookgraph.py
git commit -m "feat(canonical): build bookgraph from text units"
```

### Task 3: Docs, Integration, Smoke

**Files:**
- Modify: `docs/canonical-v2-bookgraph.md`
- Test: existing observed shadow and normalize tests

- [ ] **Step 1: Document Phase 3.1**

Add a section explaining:

- `TextUnit` is an internal shadow aggregation layer.
- Aggregation is non-semantic and same-page only.
- `bbox=None` observations do not merge by geometry in Phase 3.1.
- v1 canonical, EPUB, and RAG remain unchanged.

- [ ] **Step 2: Run focused tests**

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run pytest \
  tests/test_text_units.py \
  tests/test_observed_bookgraph.py \
  tests/test_mineru_observed_shadow.py \
  tests/test_mineru_normalize.py \
  tests/test_bookgraph_shadow_path_compare.py \
  tests/test_canonical_architecture_policy.py \
  -q
```

- [ ] **Step 3: Run ruff and diff checks**

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run ruff check \
  packages/inkline-canonical/src/inkline/canonical/text_units.py \
  packages/inkline-canonical/src/inkline/canonical/observed_bookgraph.py \
  tests/test_text_units.py \
  tests/test_observed_bookgraph.py
git diff --check
```

- [ ] **Step 4: Real-book smoke**

Regenerate observed and observed BookGraph for one existing raw artifact and record:

- observed observations count
- observed BookGraph nodes count
- reading_order count
- ignored observation counts
- paragraph node count before/after compare helper

- [ ] **Step 5: Commit**

```bash
git add docs/canonical-v2-bookgraph.md
git commit -m "docs: document text unit aggregation phase"
```

---

## Non-Goals

- No v1 canonical changes.
- No EPUB/RAG switch.
- No cross-page aggregation.
- No semantic display_block classifier.
- No PaddleOCR/unlimitedocr adapter.
- No text meaning, keyword, or LLM rules.
