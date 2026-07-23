# SectionMap Implementation Plan

**Status:** Planned, not implemented.

## Objective

Add an internal `SectionMap` between `BookSkeleton` / `TextFlow` / `PageReview`
and public `BookGraph`. It maps confirmed physical and textual evidence to the
logical section tree, then provides the only source for BookGraph `contains`
edges and future RAG heading-path context.

## Design Constraints

- `BookSkeleton.selected_start_page` is a title anchor, never an implicit page
  range.
- `PageReview` identifies a page and its consumption policy; it does not assign
  that page to a logical section.
- TextFlow provides ordered text units and observed heading evidence; it does
  not independently decide a publication-level section boundary.
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
| `anchor_evidence_ids` | TOC/title and observed-heading evidence establishing a section start. |
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
  Read BookSkeleton title anchors, observed headings, TextFlow ordering, and
  resolved PageReview records without importing parser-specific fields.

- [ ] **3. Implement deterministic placement.**
  Mark confirmed external wrap, TOC, blank, copyright/title leaves, and other
  standalone identities before section range inference. Never assign a page
  solely because it follows a TOC anchor.

- [ ] **4. Infer high-confidence body section membership.**
  Use heading anchors, hierarchy, reading-flow continuity, and next confirmed
  heading boundaries. Preserve visual assets as explicit attachments only when
  evidence ties them to the section.

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

## Non-Goals

- No GraphRAG index, summary tree, or retrieval implementation.
- No visual image-to-caption relation extraction; that remains Phase 4B
  `VisualRelationReview` work.
- No document metadata extraction or binding-material inference.
- No migration of unresolved internal diagnostics into the public release
  canonical contract.
