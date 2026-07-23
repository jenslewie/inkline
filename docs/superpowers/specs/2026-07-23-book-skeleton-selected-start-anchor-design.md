# BookSkeleton Selected Start Anchor Design

## Goal

Make every non-null `BookSkeleton.toc_entries[].selected_start_page` a
provenance-bearing section-start anchor that SectionMap can consume without
re-running title location.

## Contract

BookSkeleton advances from schema version `0.1-shadow` to `0.2-shadow` and adds
the required `selected_start_anchor` field to every public TOC entry. The field
is `null` exactly when `selected_start_page` is `null`.

```json
{
  "entry_index": 12,
  "display_title": "第一章 楼兰",
  "candidate_start_pages": [42],
  "selected_start_page": 42,
  "selected_start_anchor": {
    "anchor_id": "sa000012",
    "page": 42,
    "resolution_method": "observed_title_match",
    "title_observation_ids": ["ob000381"],
    "toc_observation_ids": ["ob000094"],
    "supporting_anchor_ids": [],
    "confidence": "high"
  }
}
```

Allowed resolution methods are:

- `observed_title_match`: the selected physical page contains one or more
  observations used by the existing title-location matcher;
- `printed_page_offset`: the title was not observed on the selected physical
  page, but the existing printed-page offset rule inferred the page from two
  neighboring direct anchors with the same offset.

Direct anchors have `confidence=high`, at least one title observation id, and
no supporting anchor ids. Printed-offset anchors have `confidence=medium`, no
title observation ids, and exactly two supporting direct-anchor ids.

`toc_observation_ids` contains the parser-neutral `toc_text` observations from
the detected TOC pages that contain the normalized entry title. It is allowed
to be empty for an LLM-corrected display title that cannot be matched back to
the OCR TOC text; the title observation still provides direct target-page
evidence.

## Evidence Capture

`page_records()` retains the observation ids behind each title-location text
view. A new title-candidate function returns page, score, and matching
observation ids; the existing page-only functions remain wrappers for current
callers and tests.

The builder keeps candidate evidence private while monotonic page selection is
performed. After the final selected pages are known, it materializes direct
anchors first and printed-offset anchors second. Private candidate evidence and
printed-page values remain absent from the public TOC entry.

## Validation

`validate_book_skeleton()` validates the self-contained anchor shape and these
invariants:

- anchor id is `sa` plus the zero-padded six-digit `entry_index`;
- anchor page equals `selected_start_page`;
- null anchor and null selected page occur together;
- resolution method, confidence, evidence lists, and supporting-anchor shape
  agree;
- anchor ids and observation ids contain no duplicates.

`validate_book_skeleton_against_observed(skeleton, document)` performs
cross-artifact checks:

- every referenced observation exists;
- title observations occur on the selected anchor page;
- TOC observations occur on `toc_pages` and have `role_hint=toc_text`;
- supporting anchors exist, are direct anchors, and establish the same printed
  page offset on both sides of the inferred entry.

The builder runs both validators before returning.

## PageReview Boundary

PageReview continues to consume `boundaries`, `toc_pages`, and
`selected_start_page`. It does not use anchor evidence to infer page identity,
text consumption, or section membership. A regression test compares PageReview
plans from Skeletons whose anchor provenance differs while all existing page
fields remain unchanged.

## SectionMap Boundary

SectionMap consumes `selected_start_anchor` as the authoritative source-start
reference. It maps anchor observation ids to TextUnits and logical units, but
still decides `section_member`, `standalone`, and `unresolved` using TextFlow
continuity and PageReview exceptions. An anchor never implies that every later
page belongs to the section.

## Compatibility and Non-Goals

- Keep `candidate_start_pages` and `selected_start_page` unchanged.
- Do not expose TextUnit ids from BookSkeleton; TextUnits are built later and
  may be renumbered.
- Do not add section end pages, page ranges, resource membership, or BookGraph
  `contains` edges to BookSkeleton.
- Do not change TOC LLM output: the LLM still cannot emit candidate pages,
  selected pages, anchors, or observation ids.
