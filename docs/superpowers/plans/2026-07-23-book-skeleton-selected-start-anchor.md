# BookSkeleton Selected Start Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade BookSkeleton so every selected physical start page carries validated ObservedDocument provenance that SectionMap can consume directly.

**Architecture:** Preserve `candidate_start_pages` and `selected_start_page`, but carry private evidence through title location and monotonic selection before publishing `selected_start_anchor`. Direct title matches cite page-local observations; printed-page offset anchors cite TOC observations and two direct supporting anchors. PageReview remains behaviorally unchanged and SectionMap receives start evidence rather than membership conclusions.

**Tech Stack:** Python 3.12, pytest, Ruff, Pylint, JSON-compatible dictionaries

## Global Constraints

- BookSkeleton owns hierarchy and provenance-bearing start anchors, never section page ranges or membership.
- Use parser-neutral ObservedDocument observation ids; do not introduce MinerU fields or TextUnit ids.
- Keep TOC LLM output unchanged; the LLM cannot emit pages, anchors, offsets, or observation ids.
- `selected_start_page` remains the compatibility field used by PageReview.
- `selected_start_anchor` is null exactly when `selected_start_page` is null.
- Direct anchors are high confidence; printed-page offset anchors are medium confidence.
- PageReview output must not change because anchor provenance was added.
- Completion requires focused pytest, full pytest, Ruff, Pylint, format check, and `git diff --check`.

---

### Task 0: Restore the Existing Test Baseline

**Files:**
- Modify: `tests/test_canonical_architecture_policy.py`

**Interfaces:**
- Consumes: Current canonical subpackages under `canonical/bookgraph/` and `canonical/observed/`.
- Produces: Architecture policy tests that scan the current files instead of deleted pre-refactor modules.

- [ ] **Step 1: Reproduce the two stale-path failures**

Run:

```bash
.venv/bin/pytest -q tests/test_canonical_architecture_policy.py
```

Expected: two failures with `FileNotFoundError` for
`packages/inkline-canonical/src/inkline/canonical/bookgraph.py`.

- [ ] **Step 2: Replace the duplicated stale path lists with the current files**

Add one module-level constant and use it in both tests:

```python
CHECKED_CANONICAL_FILES = [
    ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph/schema.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph/audit.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph/projection.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph/from_observed.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/observed/schema.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/observed/text_unit_layout.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/observed/text_units.py",
]
```

Each test assigns `checked = CHECKED_CANONICAL_FILES`; do not weaken either
forbidden-term list.

- [ ] **Step 3: Verify the baseline repair**

Run:

```bash
.venv/bin/pytest -q tests/test_canonical_architecture_policy.py
```

Expected: `2 passed`.

- [ ] **Step 4: Commit the baseline repair separately**

```bash
git add tests/test_canonical_architecture_policy.py
git commit -m "test: follow canonical subpackage layout"
```

---

### Task 1: Preserve Observation Evidence During Title Location

**Files:**
- Modify: `packages/inkline-canonical/src/inkline/canonical/book_skeleton/pages.py`
- Modify: `tests/test_book_skeleton_title_location.py`

**Interfaces:**
- Consumes: `page_records(document)` and the existing title normalization, matching, and scoring rules.
- Produces: `locate_toc_entry_anchors(page_records_, entry, exclude_pages=...) -> list[dict[str, Any]]`; the existing `locate_toc_entry_pages(...) -> list[int]` remains a compatibility wrapper.

- [ ] **Step 1: Add a failing direct-evidence test**

Extend the existing `test_locates_split_short_title_blocks_before_notes()`
after it creates `document`, then assert the new locator returns evidence
rather than only a page:

```python
def test_locate_toc_entry_anchors_keeps_matching_observation_ids() -> None:
    document = _attila_document()
    records = page_records(document)

    anchors = locate_toc_entry_anchors(
        records,
        {"display_title": "第一章 阿提拉在当下"},
        exclude_pages=[1],
    )

    assert anchors[0]["page"] == 6
    assert anchors[0]["title_observation_ids"] == ["obs000002", "obs000003"]
    assert isinstance(anchors[0]["score"], float)
```

Extract the unchanged document construction currently inside
`test_locates_split_short_title_blocks_before_notes()` into
`_attila_document()`. Import `locate_toc_entry_anchors` and `page_records` from
`inkline.canonical.book_skeleton.pages`. Keep the original test using the same
helper so the fixture has one source of truth.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
uv run pytest -q tests/test_book_skeleton_title_location.py::test_locate_toc_entry_anchors_keeps_matching_observation_ids
```

Expected: collection failure because `locate_toc_entry_anchors` does not exist.

- [ ] **Step 3: Retain private observation views in `page_records()`**

Add these private keys to each page record while keeping all existing text
fields unchanged:

```python
"_title_location_observations": [
    *_title_context_observations(text_observations, title_location_observations),
    *visual_title_observations,
],
"_candidate_title_context_observations": (
    _candidate_title_context_observations(text_observations)
),
```

The keys are internal Python values and never enter BookSkeleton JSON.

- [ ] **Step 4: Implement the evidence-bearing locator**

Refactor the current `locate_title_pages` loop into:

```python
def locate_toc_entry_anchors(
    page_records_: list[dict[str, Any]],
    entry: dict[str, Any],
    *,
    exclude_pages: list[int],
) -> list[dict[str, Any]]:
    best_by_page: dict[int, dict[str, Any]] = {}
    for title in _location_titles_for_entry(entry):
        for candidate in locate_title_anchors(
            page_records_, title, exclude_pages=exclude_pages
        ):
            page = int(candidate["page"])
            existing = best_by_page.get(page)
            if existing is None or float(candidate["score"]) > float(existing["score"]):
                best_by_page[page] = candidate
    return sorted(
        best_by_page.values(),
        key=lambda candidate: (-float(candidate["score"]), int(candidate["page"])),
    )


def locate_toc_entry_pages(
    page_records_: list[dict[str, Any]],
    entry: dict[str, Any],
    *,
    exclude_pages: list[int],
) -> list[int]:
    return [
        int(candidate["page"])
        for candidate in locate_toc_entry_anchors(
            page_records_, entry, exclude_pages=exclude_pages
        )
    ]
```

`locate_title_anchors()` uses the existing `_title_matches_record()` and
`_title_location_score()` rules:

```python
def locate_title_anchors(
    page_records_: list[dict[str, Any]],
    title: str,
    *,
    exclude_pages: list[int],
) -> list[dict[str, Any]]:
    excluded = set(exclude_pages)
    title_key = normalize_title(title)
    if not title_key:
        return []
    candidates = []
    for record in page_records_:
        page = int(record["page"])
        if page in excluded:
            continue
        text = _title_location_text(record)
        page_key = normalize_title(text)
        if not _title_matches_record(record, title_key, page_key):
            continue
        evidence = [
            *record.get("_title_location_observations", []),
            *record.get("_candidate_title_context_observations", []),
        ]
        observation_ids = sorted(
            {
                str(observation["observation_id"])
                for observation in evidence
                if str(observation.get("text") or "").strip()
            }
        )
        candidates.append(
            {
                "page": page,
                "score": _title_location_score(record, title_key, text, page_key),
                "title_observation_ids": observation_ids,
            }
        )
    return sorted(
        candidates,
        key=lambda candidate: (-float(candidate["score"]), int(candidate["page"])),
    )
```

Keep `locate_title_pages()` as a page-only wrapper around this function.

- [ ] **Step 5: Verify locator compatibility and evidence**

Run:

```bash
uv run pytest -q tests/test_book_skeleton_title_location.py tests/test_book_skeleton_page_selection.py
```

Expected: all tests pass; existing page ordering is unchanged.

- [ ] **Step 6: Commit evidence-preserving location**

```bash
git add packages/inkline-canonical/src/inkline/canonical/book_skeleton/pages.py tests/test_book_skeleton_title_location.py
git commit -m "feat(canonical): preserve skeleton title evidence"
```

---

### Task 2: Publish and Validate Selected Start Anchors

**Files:**
- Modify: `packages/inkline-canonical/src/inkline/canonical/book_skeleton/contract.py`
- Modify: `packages/inkline-canonical/src/inkline/canonical/book_skeleton/pages.py`
- Modify: `packages/inkline-canonical/src/inkline/canonical/book_skeleton/builder.py`
- Modify: `packages/inkline-canonical/src/inkline/canonical/book_skeleton/validation.py`
- Modify: `packages/inkline-canonical/src/inkline/canonical/book_skeleton/__init__.py`
- Modify: `packages/inkline-canonical/src/inkline/canonical/__init__.py`
- Modify: `tests/test_book_skeleton.py`
- Modify: `tests/test_book_skeleton_page_selection.py`

**Interfaces:**
- Consumes: Direct candidate records from Task 1, final monotonic page selections, printed-page values, and ObservedDocument observations.
- Produces: `selected_start_anchor`, schema version `0.2-shadow`, and `validate_book_skeleton_against_observed(skeleton, document) -> None`.

- [ ] **Step 1: Add failing contract tests for direct, null, and invalid anchors**

Add assertions to the standard `_document()` builder test for its third TOC
entry, `第一章 米兰达`:

```python
entries = {
    entry["display_title"]: entry
    for entry in build_book_skeleton_from_observed(_document())["toc_entries"]
}
entry = entries["第一章 米兰达"]
assert entry["selected_start_anchor"] == {
    "anchor_id": "sa000002",
    "page": 42,
    "resolution_method": "observed_title_match",
    "printed_page_offset": 0,
    "title_observation_ids": ["obs000004", "obs000005"],
    "toc_observation_ids": ["obs000001"],
    "supporting_anchor_ids": [],
    "confidence": "high",
}
```

Add mutation tests that reject page mismatch, duplicate evidence ids, an
invalid method, a non-null page with null anchor, and a null page with a
non-null anchor.

- [ ] **Step 2: Add a failing printed-offset anchor test**

Extend `test_add_printed_page_offset_candidates_fills_ocr_missed_title_page`
through a full `build_book_skeleton_from_observed()` fixture and assert:

```python
anchor = skeleton["toc_entries"][1]["selected_start_anchor"]
assert anchor["resolution_method"] == "printed_page_offset"
assert anchor["page"] == 27
assert anchor["printed_page_offset"] == 12
assert anchor["title_observation_ids"] == []
assert anchor["supporting_anchor_ids"] == ["sa000000", "sa000002"]
assert anchor["confidence"] == "medium"
```

- [ ] **Step 3: Run the contract tests and verify RED**

Run:

```bash
uv run pytest -q tests/test_book_skeleton.py tests/test_book_skeleton_page_selection.py
```

Expected: failures for missing `selected_start_anchor` and schema version
`0.2-shadow`.

- [ ] **Step 4: Define the anchor contract and version**

In `contract.py` set:

```python
BOOK_SKELETON_SCHEMA_VERSION = "0.2-shadow"
BOOK_SKELETON_ANCHOR_METHODS = {"observed_title_match", "printed_page_offset"}
BOOK_SKELETON_ANCHOR_CONFIDENCES = {"high", "medium"}
REQUIRED_START_ANCHOR_FIELDS = {
    "anchor_id": str,
    "page": int,
    "resolution_method": str,
    "printed_page_offset": (int, type(None)),
    "title_observation_ids": list,
    "toc_observation_ids": list,
    "supporting_anchor_ids": list,
    "confidence": str,
}
```

Add `"selected_start_anchor": (dict, type(None))` to
`REQUIRED_ENTRY_FIELDS`.

- [ ] **Step 5: Carry private direct and offset evidence through selection**

In `builder.py`, replace the page-only candidate assignment with:

```python
candidate_anchors = locate_toc_entry_anchors(records, entry, exclude_pages=toc_pages)
entry["candidate_start_pages"] = [
    int(candidate["page"]) for candidate in candidate_anchors
]
entry["_candidate_start_anchors"] = {
    int(candidate["page"]): candidate for candidate in candidate_anchors
}
entry["selected_start_page"] = None
```

Refactor printed-offset support in `pages.py` so the existing public function
also stores this private record when it appends a predicted candidate:

```python
entry["_printed_offset_candidate"] = {
    "page": predicted_page,
    "printed_page_offset": offset,
    "supporting_entry_indexes": [previous_index, next_index],
}
```

The supporting indexes come from a new
`_agreed_neighbor_offset_support(entries, index)` helper; preserve
`_agreed_neighbor_offset()` as a wrapper if tests import it indirectly.

- [ ] **Step 6: Materialize selected anchors after final selection**

Add this public builder helper in `pages.py`:

```python
def attach_selected_start_anchors(
    entries: list[dict[str, Any]],
    document: dict[str, Any],
    *,
    toc_pages: list[int],
) -> None:
    _attach_direct_anchors(entries, document, toc_pages=toc_pages)
    _attach_printed_offset_anchors(entries, document, toc_pages=toc_pages)
```

Direct anchors use the selected page's private candidate record, confidence
`high`, and no supporting ids. Offset anchors use the private offset record,
confidence `medium`, and exactly the two supporting direct anchor ids.
`toc_observation_ids` are observations with `role_hint=toc_text` on a detected
TOC page whose normalized text contains the normalized entry title. An
LLM-corrected title may produce an empty list.

Call `attach_selected_start_anchors()` after the second
`select_monotonic_start_pages()` and candidate pruning, before
`_public_toc_entry()`.

Publish the field in `_public_toc_entry()` and continue reconstructing the
public dictionary explicitly so no private underscore key leaks.

- [ ] **Step 7: Implement shape and cross-artifact validation**

`validate_book_skeleton()` checks anchor shape, `sa{entry_index:06d}` identity,
page equality, null pairing, method-specific evidence, confidence, and unique
ids.

Add and export:

```python
def validate_book_skeleton_against_observed(
    skeleton: dict[str, Any], document: dict[str, Any]
) -> None:
    validate_book_skeleton(skeleton)
    validate_observed_document(document)
    if skeleton["metadata"]["doc_id"] != document["metadata"]["doc_id"]:
        raise ValidationError("BookSkeleton and ObservedDocument doc_id values differ")
    observations = {
        str(observation["observation_id"]): observation
        for observation in document["observations"]
    }
    toc_pages = set(skeleton["toc_pages"])
    entries_by_anchor_id = {
        entry["selected_start_anchor"]["anchor_id"]: (index, entry)
        for index, entry in enumerate(skeleton["toc_entries"])
        if entry["selected_start_anchor"] is not None
    }
    for index, entry in enumerate(skeleton["toc_entries"]):
        anchor = entry["selected_start_anchor"]
        if anchor is None:
            continue
        for observation_id in anchor["title_observation_ids"]:
            observation = _required_anchor_observation(observations, observation_id)
            if observation["page"] != anchor["page"]:
                raise ValidationError(
                    f"toc_entries[{index}] title evidence is not on anchor page"
                )
        for observation_id in anchor["toc_observation_ids"]:
            observation = _required_anchor_observation(observations, observation_id)
            if observation["page"] not in toc_pages or observation["role_hint"] != "toc_text":
                raise ValidationError(
                    f"toc_entries[{index}] TOC evidence is not on a TOC page"
                )
        if anchor["resolution_method"] != "printed_page_offset":
            continue
        support = []
        for supporting_anchor_id in anchor["supporting_anchor_ids"]:
            supporting_entry = entries_by_anchor_id.get(supporting_anchor_id)
            if supporting_entry is None:
                raise ValidationError(
                    f"toc_entries[{index}] references unknown supporting anchor"
                )
            support.append(supporting_entry)
        support_indexes = [value[0] for value in support]
        support_anchors = [value[1]["selected_start_anchor"] for value in support]
        if not (min(support_indexes) < index < max(support_indexes)):
            raise ValidationError(
                f"toc_entries[{index}] offset supports must straddle the entry"
            )
        expected_offset = anchor["printed_page_offset"]
        if any(
            value["resolution_method"] != "observed_title_match"
            or value["printed_page_offset"] != expected_offset
            for value in support_anchors
        ):
            raise ValidationError(
                f"toc_entries[{index}] offset supports do not agree"
            )


def _required_anchor_observation(
    observations: dict[str, dict[str, Any]], observation_id: str
) -> dict[str, Any]:
    observation = observations.get(observation_id)
    if observation is None:
        raise ValidationError(f"anchor references unknown observation: {observation_id}")
    return observation
```

The function also rejects mismatched `metadata.doc_id` values. Call it from
`build_book_skeleton_from_observed()` after constructing the public skeleton.

- [ ] **Step 8: Verify the complete BookSkeleton slice**

Run:

```bash
uv run pytest -q tests/test_book_skeleton.py tests/test_book_skeleton_page_selection.py tests/test_book_skeleton_title_location.py tests/test_book_skeleton_experiment_tool.py
```

Expected: all focused BookSkeleton tests pass.

- [ ] **Step 9: Commit the public anchor contract**

```bash
git add packages/inkline-canonical/src/inkline/canonical/book_skeleton packages/inkline-canonical/src/inkline/canonical/__init__.py tests/test_book_skeleton.py tests/test_book_skeleton_page_selection.py
git commit -m "feat(canonical): add BookSkeleton start anchors"
```

---

### Task 3: Prove PageReview Behavior Is Unchanged

**Files:**
- Modify: `tests/test_page_review_contract.py`
- Modify: `tests/test_mineru_page_review_shadow.py`

**Interfaces:**
- Consumes: BookSkeleton `0.2-shadow` with `selected_start_anchor`.
- Produces: Regression evidence that PageReview still depends only on existing pages, boundaries, TOC pages, and section-start page numbers.

- [ ] **Step 1: Add a PageReview invariance test**

Build a valid anchored Skeleton, then create a compatibility projection that
removes only `selected_start_anchor` before calling the current PageReview plan
builder:

```python
anchored = build_book_skeleton_from_observed(document)
page_only = deepcopy(anchored)
for entry in page_only["toc_entries"]:
    entry.pop("selected_start_anchor")

assert build_page_review_plan(document, anchored, page_roles) == (
    build_page_review_plan(document, page_only, page_roles)
)
```

This intentionally tests PageReview's field consumption rather than validating
the compatibility projection as a current BookSkeleton artifact.

- [ ] **Step 2: Run PageReview tests**

```bash
uv run pytest -q tests/test_page_review_contract.py tests/test_mineru_page_review_shadow.py tests/test_mineru_page_review_checkpoint.py
```

Expected: all focused PageReview tests pass with unchanged page decisions and
checkpoint behavior.

- [ ] **Step 3: Commit the regression coverage**

```bash
git add tests/test_page_review_contract.py tests/test_mineru_page_review_shadow.py
git commit -m "test(canonical): keep PageReview independent of anchor provenance"
```

---

### Task 4: Update Contracts and SectionMap Documentation

**Files:**
- Modify: `docs/canonical-v2-bookgraph.md`
- Modify: `docs/superpowers/plans/2026-07-22-section-map.md`
- Modify: `packages/inkline-canonical/README.md`

**Interfaces:**
- Consumes: Implemented `selected_start_anchor` contract.
- Produces: Documentation that SectionMap consumes verified anchors but still owns membership.

- [ ] **Step 1: Update the BookSkeleton contract documentation**

Document schema `0.2-shadow`, both resolution methods, evidence fields,
confidence rules, and the distinction:

```text
selected_start_anchor proves where a section starts and why.
It does not prove that later pages or resources belong to that section.
```

- [ ] **Step 2: Update the SectionMap input contract**

Replace language requiring SectionMap to rediscover observed heading evidence
with language requiring it to map
`selected_start_anchor.title_observation_ids` to TextUnits/logical units.
Retain all `standalone` and `unresolved` rules.

- [ ] **Step 3: Verify documentation consistency**

Run:

```bash
rg -n "selected_start_anchor|observed_title_match|printed_page_offset" docs/canonical-v2-bookgraph.md packages/inkline-canonical/README.md docs/superpowers/plans/2026-07-22-section-map.md
git diff --check
```

Expected: every file names the same contract and no file claims that anchors
define section ranges.

- [ ] **Step 4: Commit documentation**

```bash
git add docs/canonical-v2-bookgraph.md docs/superpowers/plans/2026-07-22-section-map.md packages/inkline-canonical/README.md
git commit -m "docs(canonical): define start-anchor provenance"
```

---

### Task 5: Run Full Acceptance

**Files:**
- Verify only; modify files only if a failing check traces directly to the anchor implementation.

**Interfaces:**
- Consumes: Tasks 0 through 4.
- Produces: A clean, fully verified local commit series ready for SectionMap implementation.

- [ ] **Step 1: Run focused acceptance**

```bash
uv run pytest -q tests/test_book_skeleton.py tests/test_book_skeleton_page_selection.py tests/test_book_skeleton_title_location.py tests/test_book_skeleton_experiment_tool.py tests/test_page_review_contract.py tests/test_mineru_page_review_shadow.py tests/test_mineru_page_review_checkpoint.py tests/test_canonical_architecture_policy.py
```

Expected: all focused tests pass.

- [ ] **Step 2: Run repository quality gates**

```bash
make check
```

Expected: Ruff, Pylint `C0302`, Ruff format check, and the full pytest suite all
exit 0.

- [ ] **Step 3: Verify changed scope and schema leakage**

```bash
git diff HEAD~5 --check
git status --short
rg -n '_candidate_start_anchors|_printed_offset_candidate' packages/inkline-canonical/src
```

Expected: no whitespace errors; the worktree is clean after the planned
commits; private underscore fields appear only in BookSkeleton builder/location
internals and never in public serialized output.
