# Structural Chapter Title Pages in SectionMap

## Status

Revised after scope review, 2026-07-29.

## Problem

A chapter title may occupy an otherwise sparse physical page. PageLayout can
correctly recognize that geometry as `title_like_page`, but PageReview currently
collapses that role into `visual_page` and assigns `text_flow_action=exclude`.
The title then disappears from TextFlow even when BookSkeleton has an exact
body-section start anchor on the page.

This prevents SectionMap from representing the section start correctly:

- `title_text_unit_ids` remains empty;
- the section title exists only as Skeleton anchor evidence instead of a
  heading TextUnit; and
- downstream SectionMap consumers cannot distinguish the structural heading
  from a section whose title was never observed in TextFlow.

## Requirements

For a sparse, standalone chapter title page confirmed by a BookSkeleton body
section start:

1. Preserve the complete title text, including source line breaks.
2. Represent the title as a heading in TextFlow.
3. Start the SectionMap physical range on the title page and reference its
   heading TextUnit through `title_text_unit_ids`.
4. Do not change the treatment of ordinary maps, illustrations, charts, or
   other visual pages that are not confirmed chapter-title pages.

## Classification Rule

PageLayout remains responsible for geometric evidence and may continue to emit
`title_like_page`. PageReview owns consumption policy and must distinguish a
BookSkeleton-confirmed body section start from an ordinary sparse visual page.

When both conditions hold:

- the PageLayout role is `title_like_page`; and
- BookSkeleton identifies the same physical page as a body section start;

PageReview emits:

```text
page_role = text_flow_page
text_flow_action = include
visual_asset_action = not_needed
```

This rule is deterministic. It uses the already validated Skeleton boundary and
does not require semantic inference from arbitrary page text. Other
`title_like_page` records retain their existing review behavior.

## Artifact Data Flow

The included page follows the ordinary artifact path:

```text
Observed title observations
  -> PageLayout title_like_page
  -> PageReview text_flow_page/include
  -> one heading TextUnit with preserved text and line breaks
  -> SectionMap title_text_unit_ids and physical range
```

TextFlow remains the single source of TextUnit identity. SectionMap does not
synthesize or repair a missing TextUnit. This task ends after the heading is
correctly integrated into SectionMap.

## Verification

Implementation follows test-driven development:

1. Add a failing PageReview test for a `title_like_page` that is also a
   Skeleton-confirmed body section start.
2. Add a failing TextFlow/SectionMap integration regression proving that the
   title becomes one heading TextUnit, the physical range starts on that page,
   and `title_text_unit_ids` references it.
3. Regenerate PageReview output and compare the complete golden corpus before
   publishing it.
4. Regenerate the Silk Road SectionMap review artifacts and verify that the
   first chapter starts on physical page 42 with a non-empty
   `title_text_unit_ids` value.
5. Run focused pytest, the 13-book regression suite, Ruff, Pylint, and Pyright.

## Non-goals

- Treating every sparse centered page as a chapter title.
- Including map labels, illustration labels, or decorative text in reading
  flow.
- Adding a second TextUnit-generation path in SectionMap.
- Changing BookGraph assembly or projection.
- Changing RAG chunking, embedding, indexing, or search.
- Changing EPUB rendering, navigation, or styling.

BookGraph, RAG, and EPUB will consume the corrected structural heading in later,
separately designed tasks.
