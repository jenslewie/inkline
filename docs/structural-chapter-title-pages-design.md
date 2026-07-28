# Structural Chapter Title Pages

## Status

Approved design, 2026-07-28.

## Problem

A chapter title may occupy an otherwise sparse physical page. PageLayout can
correctly recognize that geometry as `title_like_page`, but PageReview currently
collapses that role into `visual_page` and assigns `text_flow_action=exclude`.
The title then disappears from TextFlow and the current BookGraph assembler,
even when BookSkeleton has an exact body-section start anchor on the page.

This behavior breaks the product contract:

- BookGraph loses a structural heading node.
- RAG cannot use the chapter title in its embedding input.
- EPUB cannot render the original title text as a semantic, searchable chapter
  title page.

## Requirements

For a sparse, standalone chapter title page confirmed by a BookSkeleton body
section start:

1. Preserve the complete title text, including source line breaks.
2. Represent the title as a heading in TextFlow and BookGraph.
3. Start the SectionMap physical range on the title page and reference its
   heading TextUnit through `title_text_unit_ids`.
4. Include the complete heading path in the RAG embedding input.
5. Render the complete heading as semantic EPUB HTML on a dedicated page.
6. Do not replace the visible EPUB title with a page snapshot.
7. Do not change the treatment of ordinary maps, illustrations, charts, or
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
  -> BookGraph heading node with observation provenance
```

TextFlow remains the single source of TextUnit identity. SectionMap does not
synthesize or repair a missing TextUnit. The BookGraph assembler receives the
heading through the validated TextFlow and later uses SectionMap for section
containment.

## RAG Projection

Chunk display text remains body-only so search results do not repeat the chapter
title. Embedding input is built deterministically from the structural heading
path and body text:

```text
<heading level 1>
<heading level 2, when present>

<chunk body text>
```

The chunk continues to store `heading_path` and `chapter_title` as structured
metadata. The embedding command must use this combined representation rather
than `row["text"]` alone. A shared pure helper owns this formatting so tests and
CLI behavior cannot diverge.

## EPUB Projection

A chapter-splitting heading starts a new XHTML chapter. The EPUB renderer emits
the complete heading text inside `.chapter-title-page`; embedded newlines become
`<br/>` without changing the text. Existing CSS provides full-page height and a
forced page break, so body content starts on the following page.

The chapter-title page is rendered as semantic HTML/CSS:

- visible title text is selectable and searchable;
- navigation uses the structural heading;
- the title remains available to accessibility tools;
- no page snapshot replaces or duplicates the visible title.

## Verification

Implementation follows test-driven development:

1. Add a failing PageReview test for a `title_like_page` that is also a
   Skeleton-confirmed body section start.
2. Add a failing TextFlow/SectionMap integration regression proving that the
   title becomes one heading TextUnit, the physical range starts on that page,
   and `title_text_unit_ids` references it.
3. Add a failing RAG test proving the embedding input contains the complete
   heading path and body text while chunk display text remains unchanged.
4. Add or extend EPUB tests proving multiline title preservation, semantic HTML
   rendering, and a forced page break before body content.
5. Regenerate PageReview output and compare the complete golden corpus before
   publishing it.
6. Regenerate the Silk Road SectionMap review artifacts and verify that the
   first chapter starts on physical page 42 with a non-empty
   `title_text_unit_ids` value.
7. Run focused pytest, the 13-book regression suite, Ruff, Pylint, and Pyright.

## Non-goals

- Reproducing PDF fonts, decoration, or exact title coordinates in EPUB.
- Treating every sparse centered page as a chapter title.
- Including map labels, illustration labels, or decorative text in reading
  flow.
- Adding a second TextUnit-generation path in SectionMap or BookGraph assembly.
