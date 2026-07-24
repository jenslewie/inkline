# SectionMap Implementation Plan

**Status:** Planned, not implemented.

## Objective

Add an internal `SectionMap` between `BookSkeleton` / `TextFlow` / `PageReview`
and public `BookGraph`. It maps confirmed physical and textual evidence to the
logical section tree, then provides the only source for BookGraph `contains`
edges and future RAG heading-path context.

## Design Constraints

- `BookSkeleton` schema is `0.2-shadow`. `selected_start_anchor` is `null` iff
  `selected_start_page` is `null`; otherwise it records `anchor_id`, `page`,
  `resolution_method`, `printed_page_offset`, `title_observation_ids`,
  `toc_observation_ids`, `supporting_anchor_ids`, and `confidence`.
- `observed_title_match` is a direct, `high`-confidence anchor with title
  evidence. `printed_page_offset` is `medium` confidence and has exactly two
  straddling direct anchors that agree on its offset.
- A selected start anchor proves where a section starts and why. It does not
  prove that later pages or resources belong to that section.
- `PageReview` consumes `selected_start_page` and remains independent of anchor
  provenance; it identifies a page and its consumption policy, not its logical
  section.
- SectionMap consumes anchors by `resolution_method`. For
  `observed_title_match`, it maps `title_observation_ids` to TextUnits/logical
  units. For `printed_page_offset`, whose title evidence is empty by contract,
  it uses the validated physical `page`, matching `toc_observation_ids`, and
  two agreeing direct `supporting_anchor_ids`; it neither fabricates a title
  TextUnit nor rediscovers a heading. TextFlow provides ordering and
  continuity, not a publication-level boundary by itself.
- The TOC LLM may emit only TOC-structure fields; it must not emit physical
  pages, start anchors, printed-page offsets, or observation ids.
- SectionMap must preserve `standalone` and `unresolved` physical pages. It may
  not fill gaps by assigning pages to the nearest preceding title.
- All internal decisions require provenance. A confidence value without
  evidence ids and a decision source is insufficient.
- LLM use is bounded to unresolved candidate boundaries. It must return a
  constrained relation between existing ids/pages, not rewrite text or invent
  titles, page numbers, or section ids.
- SectionMap remains internal through the v2 shadow period. Public BookGraph
  receives only confirmed `contains` edges and section/RAG context derived from
  them.

## Inputs and Output

```text
ObservedDocument ──> BookSkeleton anchors ─┐
ObservedDocument ──> TextFlow units ───────┼─> SectionMap ─> BookGraph
ObservedDocument ──> PageReview ───────────┘
```

The internal SectionMap contract will contain:

| Field | Meaning |
| --- | --- |
| `sections` | Logical sections, hierarchy, source Skeleton entry, physical ranges, unit membership, attached visual pages, and evidence. |
| `page_placements` | Explicit `section_member`, `standalone`, or `unresolved` placement for nontrivial physical pages. |
| `anchor_evidence_ids` | Direct anchors map title evidence to units; offset anchors retain TOC evidence and two direct support anchors without inventing a title unit. |
| `evidence_ids` | Evidence behind range, membership, and exception decisions. |
| `decision_source` | Deterministic structural rule or bounded LLM boundary verifier. |
| `confidence` | `high`, `medium`, or `low`, always accompanied by evidence and source. |

`physical_ranges` describe evidence-backed coverage, not unconditional ownership.
For example, a TOC page after a chronology anchor remains `standalone`; it is
not silently included in the chronology section.

## Work Plan

- [ ] **1. Write and test the SectionMap contract.**
  Define validation for section ids, parent tree, valid page placements,
  referenced TextUnit ids, evidence ids, and no dangling section ids.

- [ ] **2. Build anchor and page-identity evidence adapters.**
  Read `selected_start_anchor` provenance. Map direct-anchor
  `title_observation_ids` to TextUnits/logical units. For an offset anchor,
  retain its validated physical page, TOC evidence, and two direct supports;
  do not invent a title unit or rediscover observed heading evidence. Read
  TextFlow ordering plus resolved PageReview records without importing
  parser-specific fields. Do not treat either anchor method as membership/range
  evidence.

- [ ] **3. Implement deterministic placement.**
  Mark confirmed external wrap, TOC, blank, copyright/title leaves, and other
  standalone identities before section range inference. Never assign a page
  solely because it follows a TOC anchor.

- [ ] **4. Infer high-confidence body section membership.**
  Use mapped direct-anchor units or validated offset-page/support provenance,
  hierarchy, reading-flow continuity, and next confirmed heading boundaries.
  Preserve visual assets as explicit attachments only when evidence ties them
  to the section. An offset alone cannot establish membership.

- [ ] **5. Add bounded front/back matter boundary verification.**
  Send only unresolved gaps and existing candidate section ids/pages to the
  LLM. Require `section_member`, `standalone`, or `unresolved`; validate every
  returned reference against the input manifest.

- [ ] **6. Project confirmed structure to BookGraph.**
  Create section nodes and `contains` edges only for confirmed TextFlow unit
  membership. Keep unresolved PageReview and SectionMap diagnostics in internal
  canonical, not public node attrs.

- [ ] **7. Add audits and real-book regression fixtures.**
  Audit placement counts, unresolved regions, invalid hierarchy, coverage gaps,
  and evidence sources. Verify against books with external wraps, front-matter
  chronology pages, body plates, chapter-end notes, and book-end notes.

## Required Acceptance Cases

1. A TOC page immediately after a chronology title anchor is `standalone`, not
   a chronology member.
2. Cover, flap, and back exterior pages before the first book-internal section
   remain `standalone`.
3. A continuous body paragraph sequence between two confirmed headings joins
   the earlier section without crossing the next heading boundary.
4. A visual page within a body chapter may be attached to that section, but it
   never becomes an independent text-flow member solely because of page range.
5. A conflicting front/back matter gap remains `unresolved`; no nearest-title
   fallback is allowed.
6. Public BookGraph `contains` edges reference only validated, confirmed
   SectionMap memberships.
7. An offset-only section start has no title TextUnit; its physical page, TOC
   evidence, and two direct supports remain traceable, and no page is assigned
   solely because of the offset.

## Non-Goals

- No GraphRAG index, summary tree, or retrieval implementation.
- No visual image-to-caption relation extraction; that remains Phase 4B
  `VisualRelationReview` work.
- No document metadata extraction or binding-material inference.
- No migration of unresolved internal diagnostics into the public release
  canonical contract.
