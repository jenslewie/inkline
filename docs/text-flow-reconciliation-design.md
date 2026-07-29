# TextFlow Cross-Page Reconciliation

## Status

Approved direction, pending written-spec review, 2026-07-29.

## Problem

TextFlow is intended to contain the one authoritative sequence of logical
TextUnits. SectionMap and BookGraph must consume that same sequence without
repairing its boundaries. The current implementation does not yet preserve
this invariant for three cross-page patterns that canonical v1 already handles:

1. A body paragraph continues on the next page while page-foot notes appear
   between the two body fragments in physical reading order.
2. A page-foot note explicitly continues onto the next page, sometimes with
   additional unmarked reference fragments on the continuation page.
3. A display block continues across one or more page boundaries, optionally
   with page-foot notes between its physical fragments.

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

1. Reconcile all three patterns before final `tu...` ids are assigned.
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
8. A logical paragraph or display block may span any number of pages. Physical
   adjacency is evaluated independently at every `N -> N+1` boundary; it is
   not a two-page limit.
9. Cross-page content merging is type-homogeneous: only
   `paragraph -> paragraph` and `display_block -> display_block` are eligible.
   `paragraph -> display_block` and `display_block -> paragraph` must never be
   merged in either direction.
10. TextFlow reconciliation must not promote a paragraph to a display block or
    demote a display block to a paragraph. A type mismatch is an upstream
    layout-classification defect and must remain visible until that classifier
    is corrected and the artifacts are regenerated.

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
  -> homogeneous paragraph/display reconciliation across page boundaries
  -> final tu identity assignment
  -> validated TextFlow
  -> SectionMap membership
```

This task's integration boundary ends at SectionMap. NoteResolution, BookGraph,
RAG, and EPUB will consume the corrected artifacts in later tasks, but are not
implemented or acceptance-tested here.

Footnote reconciliation runs before content reconciliation, matching the
dependency that page-foot units must be reliably identified before they can be
treated as transparent interruptions in paragraph or display-block flow.

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

### Homogeneous cross-page content pass

The pass handles paragraph and display-block continuity through the same
boundary traversal, but with separate type-specific policies. It searches for
either of these ordered patterns:

```text
paragraph on page N
  -> zero or more page-foot footnotes
  -> paragraph on page N+1

display_block on page N
  -> zero or more page-foot footnotes
  -> display_block on page N+1
```

The footnotes are transparent for content continuity but remain independent
TextUnits in the output. The two endpoint units must have exactly the same
`unit_type`. A `paragraph` and `display_block` are a hard boundary even when
their geometry otherwise looks continuous.

For either type, a merge is allowed only when:

- the right fragment begins on the physical page immediately following the
  last physical page of the left fragment;
- every intervening unit is a page-foot `footnote` anchored on the left page;
  such a note may itself retain continuation spans on the next page;
- the left fragment reaches its page-bottom content boundary, or ends directly
  above a page-foot band that itself reaches the page bottom;
- the right fragment starts near the next page's content top;
- the fragments occupy compatible horizontal lanes for their type; and
- no heading, direct Skeleton anchor, differently typed content unit, list
  item, table-related content, or unrelated unit intervenes.

Paragraph-specific eligibility additionally requires:

- both endpoint types are `paragraph`;
- both fragments occupy the same body-text lane; and
- first-line metrics do not identify the right fragment as a new indented
  paragraph.

Display-block-specific eligibility additionally requires:

- both endpoint types are `display_block` before this pass begins;
- both fragments occupy the same set-off/display lane; and
- neither endpoint carries a display boundary such as attribution completion
  or an explicit body-resumption boundary.

The traversal is iterative. After merging pages `N` and `N+1`, it evaluates
the merged unit's last-page fragment against page `N+2` using the same rules.
It continues for `N+3` and later pages until a boundary fails. Every transition
must independently satisfy adjacency, geometry, interruption, anchor, and type
checks. Therefore a three-page unit is a chain of two proven adjacent-page
merges, not one inferred `N -> N+2` jump.

The merge keeps the left unit's position in TextFlow, removes the right
fragment, and leaves any intervening footnotes after the enlarged content unit.
It preserves the endpoint type. Paragraph text is joined as one logical
paragraph without inserting a paragraph break. Display-block text preserves
its existing internal line structure and is never normalized with paragraph
joining rules. At a display-block page boundary, `short_line_group` fragments
receive one newline, while flowing `set_off_text` fragments use the normal
script-aware inline join. Missing or conflicting `layout_form` evidence is
uncertain and therefore blocks the merge. Inline runs are merged with the same
separator so next-page note references remain attached.

Each successful boundary records:

- a type-specific reason:
  `cross_page_paragraph_continuation` or
  `cross_page_display_block_continuation`, with an
  `across_page_footnotes` evidence flag when applicable;
- the left and right physical page, endpoint observation ids, and geometry
  decision for that exact transition; and
- parser-neutral interruption evidence derived from any intervening footnote
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
- every merged paragraph contains only paragraph fragments, and every merged
  display block contains only display-block fragments;
- no merge changes a TextUnit's `unit_type`;
- each transition in a unit spanning three or more pages has its own successful
  adjacent-page merge evidence;
- output TextUnit order is deterministic;
- direct Skeleton anchor groups remain exact and cannot be crossed;
- every SectionMap TextUnit reference resolves against the regenerated
  TextFlow;
- SectionMap membership remains a continuous TextFlow slice;
- uncertain candidates remain separate rather than receiving a guessed merge.

## Verification Strategy

Implementation follows RED-GREEN TDD.

1. Add a synthetic failing TextFlow test for a paragraph split by two
   page-foot notes. Assert one paragraph, preserved footnotes, pages/spans,
   inline note refs, observation ids, merge reason, and interruption evidence.
2. Add a three-page paragraph test. Assert that both adjacent boundaries are
   proven independently and the result is one paragraph containing all three
   pages.
3. Add paragraph negative tests for an indented next-page paragraph, a heading
   boundary, a non-footnote interruption, and insufficient geometry.
4. Add two synthetic display-block tests: a three-page direct continuation and
   a continuation interrupted by page-foot notes. Assert one display block,
   preserved line structure and source evidence, and one merge record per page
   boundary.
5. Add hard-boundary tests for both `paragraph -> display_block` and
   `display_block -> paragraph`. Assert that neither pair merges and neither
   endpoint is reclassified, even when page-edge and lane geometry match.
6. Add a synthetic failing test for an explicit cross-page footnote followed
   by unmarked same-lane reference fragments. Assert one footnote and a stop at
   the next independent marker.
7. Add a real-book regression for `丝绸之路新史`:
   - observations `obs000747` and `obs000752` form one paragraph TextUnit;
   - `obs000748` and `obs000749` remain independent footnotes;
   - the paragraph retains the page-82 marker-1 note reference;
   - observations `obs001399`, `obs001405`, and their continuation tail form
     one cross-page footnote matching the canonical v1 behavior.
8. Regenerate all 13 PageReview-dependent TextFlows and SectionMaps. Compare
   counts, ownership, unresolved boundaries, observation coverage, and changed
   units against the immediately preceding accepted artifacts. Stop on any
   unexplained change.
9. Run focused pytest, the 13-book real-book suite, Ruff, Pylint, and Pyright.
10. Present the refreshed Task 4 manual checkpoint before committing the active
   SectionMap implementation.

## Non-goals

- Reusing MinerU canonical blocks as TextFlow input.
- Semantic sentence-completion or topic-based merging.
- Guessing unmarked cross-page footnote continuation.
- Same-page display-block classification, paragraph/display reclassification,
  table continuation, and figure-caption reconciliation.
- Changing SectionMap membership rules.
- Implementing final BookGraph `contains` edges, RAG chunking, or EPUB
  rendering.
- Preserving old development `tu...` ids through aliases or migrations.
