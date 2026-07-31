# TextFlow Layout Segmentation and Cross-Page Reconciliation

## Status

Classification and reconciliation foundation implemented on
`codex/text-flow-layout-reconciliation`; final TextFlow acceptance is blocked on
VisualRelationReview and note review integration, 2026-07-31. The revised
cross-artifact order is recorded in
[`section-map-upstream-replan.md`](section-map-upstream-replan.md).

## Problem

TextFlow is intended to contain the one authoritative sequence of logical
TextUnits. SectionMap must consume that same sequence without repairing its
types or boundaries. The current implementation violates this invariant before
cross-page reconciliation even begins: `build_text_units()` first aggregates
body-text observations using `same_page_short_line_group`,
`same_page_geometry_continuation`, and `cross_page_boundary_continuation`, and
only then calls `classify_text_units_by_layout()`.

That order destroys information needed by layout classification. A normal body
paragraph and the first lines of a set-off display block can be fused into one
provisional unit; the classifier can then assign only one type to the mixed
unit. Conversely, a display block split at a page boundary is classified one
page at a time, so each fragment can remain a paragraph when its missing outer
gap exists only on the adjacent page.

The result has five related defect patterns across two phases:

1. Same-page segmentation can combine `paragraph` and `display_block`
   fragments before either has a reliable type.
2. Page-local classification cannot recognize a set-off run whose evidence is
   distributed across two or more pages.
3. A body paragraph continues on the next page while page-foot notes appear
   between the two body fragments in physical reading order.
4. A page-foot note explicitly continues onto the next page, sometimes with
   additional unmarked reference fragments on the continuation page.
5. A display block continues across one or more page boundaries, optionally
   with page-foot notes between its physical fragments.
6. A paragraph is physically interrupted by an image and its caption, or by
   one or more excluded visual pages, while remaining one logical paragraph.
7. A multi-paragraph footnote is split into consecutive same-page observations
   because the second paragraph does not repeat the note marker.

In `丝绸之路新史`, physical pages 81 and 82 expose the cross-page paragraph
defect. The paragraph ending with `大多数人改走塔克` and the next-page fragment
beginning with `拉玛干北道` are currently separate TextUnits because two
footnote units occur between them. The artifact-based BookGraph assembler
creates two paragraph nodes and does not merge them later.

The same book exposes the explicit footnote-continuation defect on physical
pages 162 and 163. A reference beginning with marker `4` and ending in
`（接下页）` is emitted as a `list_item`; its `（接上页）` continuation and following
unmarked fragments are emitted as additional list items. Canonical v1 instead
represents the complete multi-page reference as one footnote with complete
source spans.

Concrete regressions in `丝绸之路新史` demonstrate both layers:

- on physical page 159, `obs001363`, a visibly set-off quotation, remains a
  paragraph while the following body introduction `obs001364` is classified as
  a display block;
- on physical pages 253 and 254, `obs002159` and `obs002163`, two fragments of
  one set-off quotation, both remain paragraphs because the classifier sees
  only page-local gaps;
- on physical pages 291 and 292, `obs002497` through `obs002499` and
  `obs002503` are classified as display content but are not reconciled across
  the page-foot notes;
- on physical page 292, body introduction `obs002504` is pre-aggregated with
  following short display lines `obs002505` and `obs002506`, and the mixed unit
  is classified as a display block; and
- on physical page 9, compact right-aligned terminal date `obs000111` remains a
  paragraph because it has no following page-local body gap.

These are TextFlow segmentation, classification, and boundary defects, not
SectionMap membership defects. SectionMap currently assigns incorrect but
internally valid units to their section. Deferring repair until BookGraph would
invalidate SectionMap's TextUnit references or create a second competing
logical-unit identity.

## Requirements

1. Generate a TextUnit exactly once. Intermediate layout candidates are not
   TextUnits, do not receive `tu...` ids, and are not persisted as a second
   version of TextFlow.
2. Classify atomic text candidates before any paragraph/display aggregation.
   Aggregation may consume only candidates whose final layout types are
   compatible.
3. Evaluate layout runs with same-page and adjacent-page context. A logical
   display block may span any number of pages, and a page boundary must not
   hide the outer-gap evidence needed to classify its fragments.
4. Reconcile all three cross-page patterns before final `tu...` ids are
   assigned.
5. Use parser-neutral structural evidence: candidate type, role hints, page
   order, bbox/spans, page dimensions, first-line metrics, note-reference runs,
   and explicit continuation markers.
6. Do not import or invoke MinerU reconciliation code from
   `inkline-canonical`.
7. Preserve complete text, pages, spans, observation ids, parser payloads,
   inline runs, note refs, and auditable merge evidence.
8. Never cross a heading, Skeleton direct anchor, table/list boundary, or
   unrelated body unit.
9. Leave uncertain candidates separate. Classification and reconciliation are
   conservative and deterministic; they do not infer continuity from topic or
   sentence meaning.
10. Regenerate TextFlow and every dependent SectionMap artifact after the
   behavior changes. Existing `tu...` ids after the first changed boundary are
   not stable and must not be migrated or aliased.
11. A logical paragraph or display block may span any number of pages. Physical
   adjacency is evaluated independently at every `N -> N+1` boundary; it is
   not a two-page limit.
12. Cross-page content merging is type-homogeneous: only
   `paragraph -> paragraph` and `display_block -> display_block` are eligible.
   `paragraph -> display_block` and `display_block -> paragraph` must never be
   merged in either direction.
13. TextFlow reconciliation must not promote a paragraph to a display block or
    demote a display block to a paragraph. A type mismatch is an upstream
    layout-classification defect and must remain visible until that classifier
    is corrected and the artifacts are regenerated.
14. `PageLayoutAnalysis` remains page/body-lane evidence. It does not become a
    second per-text classification artifact; candidate-level decisions belong
    to TextFlow construction and its audit evidence.
15. Ordered image/table observation ids and bboxes are preserved in
    `PageLayoutAnalysis` as parser-neutral visual-region evidence. This proves
    interruption topology; it does not perform semantic image-caption pairing.
16. A visual interruption is transparent only when both paragraph endpoints
    remain type-homogeneous and geometry proves that the intervening display
    records occupy the visual region's caption corridor. The caption remains an
    independent display TextUnit.
17. Consecutive excluded `visual_page` or `blank_page` records may bridge a
    paragraph across more than one physical page. Every skipped page must be
    explicitly supplied by PageReview; a missing, included, or differently
    classified page is a hard boundary.

## Canonical v1 capability matrix

Canonical v1 is a characterization baseline, not a runtime dependency:

| Capability | Canonical v1 behavior reused | Parser-neutral TextFlow owner |
| --- | --- | --- |
| Paragraph across page-foot notes | Body ending above a bottom note band can resume on the next page | Paragraph reconciliation |
| Paragraph across image/float interruption | Next body fragment can resume after top-of-page visual material | PageLayout visual regions + paragraph reconciliation |
| Paragraph across one or more visual pages | Consecutive float pages are transparent when both text endpoints prove continuation | PageReview bridge-page set + paragraph reconciliation |
| Same-page multi-paragraph footnote | Unmarked immediately adjacent reference-lane tail belongs to the marked note | Footnote reconciliation |
| Explicit cross-page footnote | `接下页`/`接上页` pair and same-lane tail are one note | Footnote reconciliation |
| Cross-page display block | Compatible set-off fragments are jointly classified and then merged | Layout classification, then display reconciliation |
| Paragraph misread as display or vice versa | v1 sometimes repaired type during merge | Rejected: classification must be correct before aggregation |
| Image-caption semantic relation | Preserve image and caption observations without inventing an edge | VisualRelationReview runs before final TextFlow; TextFlow then materializes validated captions as `caption`, not `display_block` |

## Considered Approaches

### 1. Classification-before-aggregation inside TextFlow — selected

Replace provisional TextUnit construction with an internal atomic-candidate
stage. Classify and segment those candidates using `PageLayoutAnalysis`, then
aggregate only homogeneous candidates and run explicit cross-page
reconciliation before assigning final `tu...` ids. Port the useful structural
behavior from canonical v1 without copying parser-specific representations.

This keeps one TextUnit identity, prevents classification from inheriting a bad
pre-merge, and gives SectionMap corrected input.

### 2. Keep current aggregation and repair mixed TextUnits afterward — rejected

The classifier could attempt to split already-aggregated TextUnits back into
observations before assigning types. That would duplicate aggregation and
splitting rules, require reconstructing lost boundaries from merge metadata,
and preserve the misleading idea that provisional `tu...` ids identify real
TextUnits. It treats the symptom after the destructive step instead of fixing
the phase order.

### 3. Reuse canonical v1 MinerU reconciliation before ObservedDocument — rejected

This would reproduce the accepted MinerU result quickly, but it would make
logical paragraph identity parser-dependent. Other adapters would need their
own equivalent repair, and the unified ObservedDocument contract would no
longer produce consistent downstream behavior.

V1 remains the behavioral reference and regression oracle, not a runtime
dependency of TextFlow.

### 4. Merge nodes in NoteResolution or BookGraph — rejected

At that point SectionMap already references final TextUnit ids. Removing or
combining nodes would either leave stale SectionMap references or require the
assembler to rewrite upstream artifacts. It would also make RAG and EPUB
projections depend on a second logical-boundary definition.

NoteResolution may link references and normalize note scope, but it must not
repair TextUnit boundaries.

## Target Data Flow

```text
Inputs
  ObservedDocument       raw text and geometry evidence
  PageReview             included text-flow pages
  BookSkeleton           protected direct heading anchors
  PageLayoutAnalysis     normalized page and body-lane profiles
  VisualRelationReview   validated visual groups and caption observations
  NoteSystemReview       page/chapter/book and mixed note systems
  NoteMarkerReview       validated definition/body marker evidence

Pipeline
  -> filter retained observations by PageReview
  -> atomic text candidates (internal, no tu ids)
  -> protected structural boundaries from Skeleton and observed roles
  -> layout segmentation and classification
       -> same-page run context
       -> adjacent-page joint context
  -> homogeneous candidate aggregation
  -> explicit cross-page footnote reconciliation
  -> homogeneous paragraph/display reconciliation across page boundaries
  -> caption units from validated visual groups
  -> complete note units and unresolved note_ref inline runs from validated marker evidence
  -> final TextUnit materialization and one-time tu identity assignment
  -> validated TextFlow
  -> NoteInventory
  -> SectionMap membership
```

The current branch implements the classification/reconciliation foundation only.
VisualRelationReview, note review, NoteInventory, final SectionMap, NoteResolution,
BookGraph, RAG, and EPUB remain separate tasks. TextFlow is not frozen until those
pre-flow inputs are integrated and the 13-book comparison passes.

`PageLayoutAnalysis` is an input to layout segmentation and classification. It
provides normalized page dimensions, body lanes, ordered visual-region
geometry, and profile provenance, while the TextFlow builder owns
candidate-level type decisions and boundary evidence.

Footnote reconciliation runs before content reconciliation, matching the
dependency that page-foot units must be reliably identified before they can be
treated as transparent interruptions in paragraph or display-block flow.

## Component Design

### Atomic text candidates

Introduce an internal candidate representation under
`inkline.canonical.text_flow`. One candidate corresponds to one retained text
observation and carries its observation id, text, page, bbox/spans, role hint,
parser payload, inline runs, note refs, and protected-anchor membership.

Candidates have no `unit_id`, no schema version, and no artifact lifecycle.
Their stable audit key is the source `observation_id`. A multi-observation
Skeleton direct anchor remains an ordered protected group, but its observations
stay individually inspectable until final materialization.

Observed kinds and explicit roles may establish non-body candidate classes such
as heading, footnote/reference, list, or visual/table-related text. Remaining
`body_text` candidates enter layout segmentation as unresolved body candidates;
they are not assumed to be paragraphs merely because MinerU emitted paragraph-
like text.

The existing `same_page_short_line_group`, `same_page_geometry_continuation`,
and `cross_page_boundary_continuation` decisions move out of observation-to-
candidate construction. They may be reconsidered only after layout
classification and only inside a homogeneous type.

### Layout segmentation and classification

The classifier consumes ordered atomic candidates, page records,
`PageLayoutAnalysis`, and protected structural boundaries. It produces one
layout decision per candidate plus explicit run-boundary evidence. It never
merges text and never assigns final ids.

Same-page segmentation first separates changes in layout lane or layout form.
A body-lane introduction followed by short, aligned, set-off lines forms two
runs even when their vertical gap is small. The introduction can remain a
paragraph while the short-line run becomes a display block. Candidate grouping
is allowed for evaluating a run, but a decision is written back to every
candidate independently so mixed source evidence remains visible.

Adjacent pages are evaluated jointly when the last unresolved body candidate
or run on page `N` and the first unresolved body candidate or run on page
`N+1` both reach their respective content boundaries. Joint classification is
eligible only when:

- the pages are physically adjacent;
- both fragments occupy compatible horizontal lanes and layout forms;
- the left fragment reaches the page-bottom content boundary and the right
  fragment starts at the next page's content top;
- page-foot notes are the only transparent interruption;
- no heading, direct Skeleton anchor, list/table/visual boundary, body-lane
  resumption, or independently complete attribution intervenes; and
- the combined same-page outer-gap, inset, alignment, and page-edge evidence is
  sufficient to classify the run without using lexical meaning.

This joint view fixes the page-edge false negative: a display fragment at the
bottom of page `N` may supply only `display_gap_before`, while its continuation
at the top of page `N+1` supplies only `display_gap_after`. Compatible set-off
geometry plus the two outer gaps proves one cross-page display run; neither
fragment needs to be temporarily called a paragraph and later promoted by the
reconciler.

The same boundary evaluation is iterative for page `N+2` and later pages. Each
adjacent transition records its own signals and must pass independently.

A compact right-aligned terminal attribution may be classified as a display
block with one outer gap only when strong right-lane geometry is present, no
following body candidate exists on that page, and the following flow boundary
is independently structural (for example, a protected heading/direct anchor or
the end of included text flow). Page termination alone is not enough.

Classification output records at least:

- `classified_type` and optional `layout_form`/alignment;
- page-local geometry signals and the `PageLayoutAnalysis` profile source;
- same-page run membership and boundary reasons;
- one evidence record per accepted adjacent-page joint decision; and
- an explicit unresolved reason when evidence is insufficient.

The final contract still requires a concrete type. An uncertain body candidate
therefore materializes conservatively as an independent `paragraph` with its
uncertainty evidence; it is a hard aggregation boundary and cannot be used as
proof that adjacent paragraph or display candidates belong to the same logical
unit. `paragraph` here is the lossless body-text fallback, not a claim of strong
layout confidence.

### Homogeneous candidate aggregation

Only after every body candidate has a layout decision may candidates be
materialized into provisional logical records for reconciliation. These records
still have no `tu...` ids. Aggregation rules are type-homogeneous:

- heading fragments may aggregate only inside the same protected structural
  group;
- paragraph fragments may aggregate only with paragraphs;
- display fragments may aggregate only with display blocks of a compatible
  `layout_form`;
- footnote/reference fragments follow the explicit note rules below; and
- list, table-related, visual-related, or differently typed candidates are hard
  boundaries.

`same_page_short_line_group`, `same_page_geometry_continuation`, and
`cross_page_boundary_continuation` therefore become post-classification
evidence, not pre-classification facts. A candidate cannot inherit another
candidate's type merely because they were close enough to aggregate.

### TextFlow reconciler

Introduce a focused internal module under `inkline.canonical.text_flow` rather
than continuing to grow `builder.py`. Its internal entry point receives the
classified, homogeneous logical records and page records and returns a
reconciled list. It does not assign ids and does not mutate ObservedDocument,
Skeleton, PageReview, or PageLayoutAnalysis.

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

This reference/list-to-footnote normalization is driven by explicit note roles
and paired continuation markers. It is separate from layout classification and
does not permit paragraph/display type conversion.

The merged unit records:

- `pages` in physical order;
- all source `spans`, `observation_ids`, and parser payloads;
- merged inline runs and note refs;
- `attrs.merge_reasons` containing
  `explicit_cross_page_footnote_continuation`; and
- provenance for every absorbed source fragment.

Before the explicit cross-page pass, a same-page pass may absorb an immediately
following unmarked footnote paragraph when both records are already footnotes,
remain in a compatible reference lane, have a small measured vertical gap, and
the left record begins with an independent note marker. It stops at a numeric,
symbolic, or star marker, a lane break, a large gap, or any non-footnote
record. This is continuation of one multi-paragraph footnote, not generic
semantic deduplication. Unmarked cross-page guessing remains outside this
task.

### Homogeneous cross-page content pass

The pass handles paragraph and display-block continuity through the same
boundary traversal, but with separate type-specific policies. It searches for
either of these ordered patterns:

```text
paragraph on page N
  -> zero or more page-foot footnotes
  -> optional image/caption corridor or PageReview-approved visual pages
  -> paragraph on page N+1 or the next retained text-flow page

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

For paragraphs only, a validated visual group or structured table on the right page
may be transparent when it starts in the page-top content zone and the right
paragraph starts immediately after the combined visual/caption corridor. Caption
records remain independent `caption` TextUnits; table caption ownership remains in
TableFlow.
The same evidence allows a top-of-page image with no caption. It does not
permit a paragraph to merge with a display block.

For a multi-page visual bridge, the missing physical pages must exactly equal
the `visual_page`/`blank_page` exclusions supplied by PageReview. The merge
event records every bridge page. This is the only permitted non-adjacent
physical-page transition.

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

After classification, homogeneous aggregation, and both reconciliation passes
finish, final materialization assigns `tu000001...` exactly once. Candidate and
reconciliation records never carry a `tu...` id. No downstream builder may
delete, combine, or renumber TextUnits.

SectionMap is regenerated from the reconciled TextFlow. Its membership builder
does not need a compatibility path for old ids. BookGraph and NoteResolution
behavior are outside this task.

## Validation Invariants

Validation and tests must prove:

- no intermediate candidate or reconciliation record receives a `tu...` id;
- every body candidate is classified before it participates in paragraph or
  display aggregation;
- no aggregated record contains both paragraph and display-block candidates;
- every accepted cross-page layout decision has explicit evidence for each
  adjacent-page transition;
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

1. Add a phase-order test proving atomic candidates have no `tu...` ids and no
   body aggregation occurs before layout classification.
2. Add a same-page regression proving body-lane introduction `obs002504` is not
   pre-merged with aligned short display lines `obs002505` and `obs002506` on
   physical page 292 of `丝绸之路新史`.
3. Add a page-local classification regression for physical page 159: the
   set-off quotation `obs001363` is a display block and following body
   introduction `obs001364` is a paragraph.
4. Add an adjacent-page joint-classification regression for physical pages 253
   and 254. `obs002159` and `obs002163` must both be classified as display
   blocks before reconciliation, then become one display TextUnit.
5. Add a terminal-attribution regression for `obs000111` on physical page 9.
   The compact right-aligned date is a display block only with strong geometry,
   an outer gap, and an independently proven following structural boundary.
   Add a negative case in which page termination is the only evidence.
6. Add a synthetic failing TextFlow test for a paragraph split by two
   page-foot notes. Assert one paragraph, preserved footnotes, pages/spans,
   inline note refs, observation ids, merge reason, and interruption evidence.
7. Add a three-page paragraph test. Assert that both adjacent boundaries are
   proven independently and the result is one paragraph containing all three
   pages.
8. Add paragraph negative tests for an indented next-page paragraph, a heading
   boundary, a non-footnote interruption, and insufficient geometry.
9. Add two synthetic display-block tests: a three-page direct continuation and
   a continuation interrupted by page-foot notes. Assert one display block,
   preserved line structure and source evidence, and one merge record per page
   boundary.
10. Add a real-book display reconciliation for `obs002497` through
    `obs002499` and `obs002503` on physical pages 291 and 292. The fragments
    must already be display blocks before reconciliation and must merge across
    the page-foot notes.
11. Add hard-boundary tests for both `paragraph -> display_block` and
   `display_block -> paragraph`. Assert that neither pair merges and neither
   endpoint is reclassified, even when page-edge and lane geometry match.
12. Add a synthetic failing test for an explicit cross-page footnote followed
   by unmarked same-lane reference fragments. Assert one footnote and a stop at
   the next independent marker.
13. Add a real-book regression for `丝绸之路新史`:
   - observations `obs000747` and `obs000752` form one paragraph TextUnit;
   - `obs000748` and `obs000749` remain independent footnotes;
   - the paragraph retains the page-82 marker-1 note reference;
   - observations `obs001399`, `obs001405`, and their continuation tail form
     one cross-page footnote matching the canonical v1 behavior.
14. Add real-book regressions from the 2026-07-29 audit:
   - `obs000249` and `obs000256` are one paragraph while `obs000253`,
     `obs000254`, and `obs000255` form a validated visual group whose text
     materializes as caption units;
   - `obs000378`/`obs000383` and `obs000384`/`obs000388` are paragraph
     continuations across top-of-page images;
   - `obs000419` and `obs000420` are one same-page multi-paragraph footnote;
   - `obs000480`, `obs000485`, `obs000486`, and `obs000487` are classified
     before aggregation and materialize as one cross-page display block;
   - `obs000509` and `obs000517` are one paragraph across a page-foot note
     band; and
   - `obs000416` and `obs000428` are one paragraph across two
     PageReview-excluded visual pages.
15. Add negative tests proving that an independent marked footnote, large
   same-page footnote gap, indented new paragraph, heading, non-approved bridge
   page, and `paragraph`/`display_block` type mismatch all stop reconciliation.
16. Validate and merge the current classification/reconciliation foundation without
   declaring TextFlow final.
17. Implement and freeze VisualRelationReview, NoteSystemReview, and
   NoteMarkerReview as separate upstream artifacts.
18. Integrate those immutable artifacts into TextFlow, then regenerate all 13
   TextFlows. Compare classification, logical boundaries, observation coverage,
   captions, note units, inline runs, unconsumed evidence, and changed units against
   the immediately preceding accepted artifacts. Freeze TextFlow only after every
   unexplained change is resolved.
19. Build NoteInventory and finalize TableFlow independently.
20. Only then rebuild all 13 SectionMaps. Compare text, table, visual-group,
   note-group, page, range, and unresolved ownership. Stop on any unexplained change.
21. Run focused pytest, the 13-book real-book suite, Ruff, Pylint, and Pyright at each
   branch gate.
22. Present the refreshed Task 4 manual checkpoint only after the new upstream
   artifacts are frozen.

## Non-goals

- Reusing MinerU canonical blocks as TextFlow input.
- Semantic sentence-completion or topic-based merging.
- Guessing unmarked cross-page footnote continuation.
- Implementing VisualRelationReview itself; it is now a required external input to
  final TextFlow.
- Implementing note-system or marker review itself; they are required external
  inputs to final TextFlow.
- Reclassifying paragraph/display types during reconciliation.
- Table continuation.
- Changing SectionMap membership rules.
- Implementing final BookGraph `contains` edges, RAG chunking, or EPUB
  rendering.
- Preserving old development `tu...` ids through aliases or migrations.
