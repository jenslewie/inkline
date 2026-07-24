# BookSkeleton ObservedDocument Output Design

## Goal

Persist the exact parser-neutral `ObservedDocument` used to build each
BookSkeleton so reviewers can resolve identifiers such as `obs000396` without
reconstructing the document in memory.

The accepted workspace layout is:

```text
data/outputs/workspace/observed/<book>_observed.json
data/outputs/workspace/skeleton/<book>_skeleton.json
```

The initial backfill covers the same 13 books currently present in the
workspace and golden Skeleton suites.

## CLI Contract

Extend `mineru-to-book-skeleton` with an optional argument:

```text
--observed-output PATH
```

When supplied, the CLI writes the same in-memory `ObservedDocument` that is
validated and passed to `build_book_skeleton_shadow()`. The document is not
rebuilt and no observation ids are reassigned.

`--output` remains the required BookSkeleton destination. The new option does
not change LLM behavior, Skeleton contents, title matching, or page selection.
Existing invocations that omit `--observed-output` remain unchanged.

The ObservedDocument is written immediately after
`validate_observed_document()` succeeds and before BookSkeleton construction.
This preserves a valid upstream artifact even if a later TOC LLM or Skeleton
stage fails.

## Artifact Contract

Each output must:

- use schema `inkline_observed_document` and the current shadow version;
- contain the deterministic observation ids used by the paired Skeleton;
- retain page, bbox, role hint, parser payload, spans, and observation text;
- include PDF-derived text-line metrics when the corresponding Skeleton run
  supplied a source PDF;
- be serialized as UTF-8, unescaped Unicode, and two-space-indented JSON;
- pass `validate_observed_document()` before it is written.

The paired workspace directories have the same depth. Existing relative
`metadata.source_file` values therefore resolve correctly from both
`workspace/observed` and `workspace/skeleton`; no metadata rewrite is needed.

## Existing 13-Book Backfill

Backfill uses each book's existing MinerU `content_list_v2`, `middle.json`, and
source PDF. It calls the same input loader and ObservedDocument builder used by
the CLI, validates the result, and writes only the observed artifact. It does
not invoke the TOC LLM and does not overwrite accepted Skeleton or golden
files.

After generation, each workspace Skeleton is validated against its paired
ObservedDocument with `validate_book_skeleton_against_observed()`.

For every `selected_start_anchor`, the audit also verifies that all
`title_observation_ids` and `toc_observation_ids` resolve in the persisted
ObservedDocument. This makes commands such as the following sufficient for
manual review:

```bash
rg -n -C 8 '"observation_id": "obs000396"' \
  data/outputs/workspace/observed/女王与苏丹_observed.json
```

## Failure Handling

- Invalid ObservedDocument: fail before writing either artifact.
- Unwritable observed path: fail explicitly; do not silently continue with a
  Skeleton whose review artifact is missing.
- Existing observed file: replace it only after the newly built document has
  passed validation.
- Missing source PDF: preserve current CLI behavior. Rule-only generation may
  proceed only when the existing flags allow it; LLM generation still requires
  a readable PDF.
- Backfill mismatch with an accepted Skeleton: stop and report the book; do not
  copy that observed artifact into the accepted workspace set.

## Tests and Acceptance

Add focused CLI tests proving that:

1. `--observed-output` is optional and existing invocations are unchanged.
2. The exact object passed to `build_book_skeleton_shadow()` is written.
3. The ObservedDocument is validated before writing.
4. Parent directories are created.
5. A failure while writing the observed artifact prevents later Skeleton work.

Repository acceptance requires:

- focused BookSkeleton CLI tests;
- all 13 persisted ObservedDocuments passing schema validation;
- all 13 Skeleton/Observed pairs passing cross-artifact validation;
- direct lookup of `女王与苏丹` `obs000396` returning text `争夺巴巴里` on
  physical page 72;
- Ruff, Ruff format, Pylint, Pyright, and the full pytest suite passing;
- no changes to the accepted Skeleton or golden files.

## Non-Goals

- Do not add TextUnits, PageReview, SectionMap, or BookGraph data to the
  ObservedDocument.
- Do not modify observation-id assignment.
- Do not repair the separately identified fuzzy-anchor evidence issue in this
  change.
- Do not make observed output mandatory for all CLI users.
- Do not commit generated `data/` artifacts, which remain local review data.
