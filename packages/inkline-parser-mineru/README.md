# inkline-parser-mineru

`inkline-parser-mineru` is the MinerU adapter. It is the only package that should
understand MinerU raw outputs, MinerU block types, and MinerU-specific repair
rules.

## Public Role

- Provides the `mineru` parser entry point for `inkline-parse`.
- Provides `mineru-to-canonical` for raw artifact reuse and full canonical output.
- Provides `mineru-to-book-skeleton` for raw artifact reuse when only a
  TOC-driven BookSkeleton is needed.
- Provides `mineru-page-review` when only a Phase 4A PageReview is needed.
- Loads MinerU raw artifacts and normalizes them into current canonical output.
- Builds optional shadow artifacts: `ObservedDocument`, BookGraph, internal
  canonical, and book skeleton outputs.
- Owns MinerU-specific layout, note, display block, table, figure, and Qwen
  marker-locator repair logic.
- Does not define canonical public contracts; those belong in
  `inkline-canonical`.

## Main Areas

```text
inkline/parsers/mineru/
  app/             `mineru-to-canonical` and `mineru-to-book-skeleton` CLIs.
  bridge.py        Programmatic parser bridge.
  extraction/      Raw MinerU artifact loading and text extraction helpers.
  schema/          MinerU raw schema and pattern helpers.
  analysis/        Layout, style, geometry, and diagnostic analysis helpers.
  normalize/       MinerU raw outputs -> canonical/shadow artifacts.
  reconcile/       Cross-block reconciliation and parser-specific repairs.
```

Parser-specific data should stay in this package or in explicit provenance/debug
payloads on shadow artifacts.

## PageReview Only

`mineru-page-review` builds `ObservedDocument -> BookSkeleton -> PageReview` but
does not write a canonical graph. Its required `--output` is the PageReview JSON;
the resumable LLM checkpoint and rendered contact sheets are written beside it.

```bash
uv run --extra mineru mineru-page-review \
  --content-list-v2 data/outputs/mineru/丝绸之路新史/vlm/丝绸之路新史_content_list_v2.json \
  --middle data/outputs/mineru/丝绸之路新史/vlm/丝绸之路新史_middle.json \
  --source-pdf data/samples/丝绸之路新史.pdf \
  --doc-id 丝绸之路新史 \
  --title 丝绸之路新史 \
  --skeleton-llm \
  --llm \
  --output /tmp/inkline-page-review/丝绸之路新史_page_review.json
```

Re-run the same command after an LLM failure. Completed page groups are reused
from `/tmp/inkline-page-review/page_review.checkpoint.json`. A checkpoint is
bound to the review-plan schema and prompt version. When either changes, the
CLI archives the old checkpoint beside the output as
`page_review.checkpoint.json.stale` and starts a fresh review plan.

The PageReview LLM only sees pages before the Skeleton body boundary. It first
reviews selected visual candidates, then reviews every remaining pre-body page
whose book-block position is still `unknown`. That range is provisional
`pre_body`, not an assertion that all of its pages are front matter: the model
may identify `cover_page`, `back_cover`, `cover_flap`, `dust_jacket_spread`,
`front_board`, or `back_board` as `external_wrap`. Books without external wrap
simply have no such results.
