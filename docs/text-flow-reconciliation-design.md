# TextFlow Cross-Page Reconciliation

## Status

Approved direction, pending written-spec review, 2026-07-29.

## Problem

TextFlow is intended to contain the one authoritative sequence of logical
TextUnits. SectionMap and BookGraph must consume that same sequence without
repairing its boundaries. The current implementation does not yet preserve
this invariant for two cross-page patterns that canonical v1 already handles:

1. A body paragraph continues on the next page while page-foot notes appear
   between the two body fragments in physical reading order.
2. A page-foot note explicitly continues onto the next page, sometimes with
   additional unmarked reference fragments on the continuation page.

In `丝绸之路新史`, physical pages 81 and 82 expose the first defect. The
paragraph ending with `大多数人改走塔克` and the next-page fragment beginning
with `拉玛干北道` are currently separate TextUnits because two footnote units
occur between them. The artifact-based BookGraph assembler creates two
paragraph nodes and does not merge them later.

The same book exposes the second defect on physical pages 162 and 163. A
reference beginning with marker `4` and ending in `（接下页）` is emitted as a
`list_item`; its `（接上页）` continuation and following unmarked fragments are
emitted as additional list items. Canonical v1 instead represents the complete
multi-page reference as one footnote with complete source spans.

These are TextFlow boundary defects, not SectionMap membership defects.
SectionMap currently assigns the incorrect but internally valid units to their
section. Deferring repair until BookGraph would invalidate SectionMap's
TextUnit references or create a second competing logical-unit identity.

## Requirements

1. Reconcile both patterns before final `tu...` ids are assigned.
2. Use parser-neutral structural evidence: unit type, role hints, page order,
   bbox/spans, page dimensions, first-line metrics, note-reference runs, and
   explicit continuation markers.
3. Do not import or invoke MinerU reconciliation code from
   `inkline-canonical`.
4. Preserve complete text, pages, spans, observation ids, parser payloads,
   inline runs, note refs, and auditable merge evidence.
5. Never cross a heading, Skeleton direct anchor, table/list boundary, or
   unrelated body unit.
6. Leave uncertain candidates separate. Reconciliation is conservative and
   deterministic; it does not infer continuity from topic or sentence meaning.
7. Regenerate TextFlow and every dependent SectionMap artifact after the
   behavior changes. Existing `tu...` ids after the first changed boundary are
   not stable and must not be migrated or aliased.

## Considered Approaches

### 1. Parser-neutral reconciliation inside TextFlow — selected

Add an explicit reconciliation phase to `finalize_text_units`, after initial
layout classification and logical splitting but before the final `tu...`
renumbering. It ports the useful structural behavior from canonical v1 without
copying parser-specific representations.

This keeps one TextUnit identity, gives SectionMap corrected input, and lets
BookGraph remain a pure assembler.

### 2. Reuse canonical v1 MinerU reconciliation before ObservedDocument — rejected

This would reproduce the accepted MinerU result quickly, but it would make
logical paragraph identity parser-dependent. Other adapters would need their
own equivalent repair, and the unified ObservedDocument contract would no
longer produce consistent downstream behavior.

V1 remains the behavioral reference and regression oracle, not a runtime
dependency of TextFlow.

### 3. Merge nodes in NoteResolution or BookGraph — rejected

At that point SectionMap already references final TextUnit ids. Removing or
combining nodes would either leave stale SectionMap references or require the
assembler to rewrite upstream artifacts. It would also make RAG and EPUB
projections depend on a second logical-boundary definition.

NoteResolution may link references and normalize note scope, but it must not
repair TextUnit boundaries.

## Target Data Flow

```text
ObservedDocument observations
  -> initial TextUnit aggregation and layout classification
  -> logical splitting
  -> explicit cross-page footnote reconciliation
  -> paragraph reconciliation across page-footnote interruptions
  -> final tu identity assignment
  -> validated TextFlow
  -> SectionMap membership
  -> NoteResolution relations
  -> BookGraph assembly
```

Footnote reconciliation runs before paragraph reconciliation, matching the
dependency that page-foot units must be reliably identified before they can be
treated as transparent interruptions in body flow.

## Component Design

### TextFlow reconciler

Introduce a focused internal module under `inkline.canonical.text_flow` rather
than continuing to grow `builder.py`. Its public entry point receives the
pre-final TextUnit list and page records and returns a reconciled list. It does
not assign ids and does not mutate ObservedDocument, Skeleton, PageReview, or
PageLayoutAnalysis.

The reconciler owns two independent passes.

### Explicit cross-page footnote pass

A left unit is an eligible start only when:

- it is already a `footnote`, or its role hints identify reference/footnote
  text;
- its text contains an explicit `接下页` continuation marker;
- its evidence begins in the page-foot region; and
- it does not belong to a visual/table continuation.

A right unit is an eligible continuation only when:

- it is on the immediately following physical page;
- it is a `footnote` or carries reference/footnote role evidence;
- its text contains the matching `接上页` marker; and
- its bbox remains in the page-foot/reference lane.

The pass promotes eligible reference/list fragments to `footnote`, removes the
structural continuation markers from display text, and merges the pair. It may
then absorb consecutive same-page reference/footnote fragments in the same
page-foot lane until an independently marked note, a non-reference unit, or a
geometric lane break is encountered. This covers the unmarked tail belonging
to an explicitly continued note without turning unrelated reference-list
entries into the same note.

The merged unit records:

- `pages` in physical order;
- all source `spans`, `observation_ids`, and parser payloads;
- merged inline runs and note refs;
- `attrs.merge_reasons` containing
  `explicit_cross_page_footnote_continuation`; and
- provenance for every absorbed source fragment.

Ordinary same-page footnote deduplication and unmarked cross-page guessing are
outside this task. Only an explicit cross-page pair may activate tail-fragment
absorption.

### Paragraph-across-footnotes pass

The pass searches for this ordered pattern:

```text
paragraph on page N
  -> one or more footnotes on page N
  -> paragraph on page N+1
```

The footnotes are transparent for body continuity but remain independent
TextUnits in the output. A merge is allowed only when:

- the two paragraphs are on adjacent pages;
- every intervening unit is a page-foot `footnote` anchored on the left page;
  such a note may itself retain continuation spans on the next page;
- the left paragraph reaches the page-bottom body boundary, or ends directly
  above a page-foot band that itself reaches the page bottom;
- the right paragraph starts near the next page's body top;
- the two fragments occupy the same horizontal body lane;
- first-line metrics do not identify the right fragment as a new indented
  paragraph; and
- no heading, direct Skeleton anchor, display block, list item, table-related
  content, or unrelated body unit intervenes.

The merge keeps the left paragraph's position in TextFlow, removes the right
fragment, and leaves the intervening footnotes after the enlarged paragraph.
It concatenates body text without an inserted paragraph break, merges inline
runs so next-page note references remain attached, and records:

- `attrs.merge_reasons` containing
  `cross_page_paragraph_continuation_across_footnote`; and
- parser-neutral interruption evidence derived from the intervening footnote
  observation ids, pages, and spans.

No punctuation or lexical continuation rule is required. Geometry and explicit
structural roles must be sufficient.

### Final identity assignment

After both passes finish, `finalize_text_units` assigns `tu000001...` exactly
once. No downstream builder may delete, combine, or renumber TextUnits.

SectionMap is regenerated from the reconciled TextFlow. Its membership builder
does not need a compatibility path for old ids. BookGraph creates one node per
final TextUnit and NoteResolution links references to the already-reconciled
note units.

## Validation Invariants

Validation and tests must prove:

- every retained observation id occurs in exactly one final TextUnit;
- merging never drops or duplicates source spans, pages, parser payloads, or
  inline note-reference runs;
- output TextUnit order is deterministic;
- direct Skeleton anchor groups remain exact and cannot be crossed;
- every SectionMap TextUnit reference resolves against the regenerated
  TextFlow;
- SectionMap membership remains a continuous TextFlow slice;
- BookGraph contains one paragraph node for each reconciled paragraph and one
  note node for each reconciled footnote; and
- uncertain candidates remain separate rather than receiving a guessed merge.

## Verification Strategy

Implementation follows RED-GREEN TDD.

1. Add a synthetic failing TextFlow test for a paragraph split by two
   page-foot notes. Assert one paragraph, preserved footnotes, pages/spans,
   inline note refs, observation ids, merge reason, and interruption evidence.
2. Add negative tests for an indented next-page paragraph, a heading boundary,
   a non-footnote interruption, and insufficient geometry.
3. Add a synthetic failing test for an explicit cross-page footnote followed
   by unmarked same-lane reference fragments. Assert one footnote and a stop at
   the next independent marker.
4. Add a real-book regression for `丝绸之路新史`:
   - observations `obs000747` and `obs000752` form one paragraph TextUnit;
   - `obs000748` and `obs000749` remain independent footnotes;
   - the paragraph retains the page-82 marker-1 note reference;
   - observations `obs001399`, `obs001405`, and their continuation tail form
     one cross-page footnote matching the canonical v1 behavior.
5. Build BookGraph from the artifact bundle and assert the split paragraph is
   represented by one node and its note-reference edge remains resolved.
6. Regenerate all 13 PageReview-dependent TextFlows and SectionMaps. Compare
   counts, ownership, unresolved boundaries, observation coverage, and changed
   units against the immediately preceding accepted artifacts. Stop on any
   unexplained change.
7. Run focused pytest, the 13-book real-book suite, Ruff, Pylint, and Pyright.
8. Present the refreshed Task 4 manual checkpoint before committing the active
   SectionMap implementation.

## Non-goals

- Reusing MinerU canonical blocks as TextFlow input.
- Semantic sentence-completion or topic-based merging.
- Guessing unmarked cross-page footnote continuation.
- General table-continuation, figure-caption, or display-block reconciliation.
- Changing SectionMap membership rules.
- Implementing final BookGraph `contains` edges, RAG chunking, or EPUB
  rendering.
- Preserving old development `tu...` ids through aliases or migrations.
