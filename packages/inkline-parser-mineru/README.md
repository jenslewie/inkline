# inkline-parser-mineru

`inkline-parser-mineru` is the MinerU adapter. It is the only package that should
understand MinerU raw outputs, MinerU block types, and MinerU-specific repair
rules.

## Public Role

- Provides the `mineru` parser entry point for `inkline-parse`.
- Provides the `mineru-to-canonical` development command for raw artifact reuse.
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
  app/             `mineru-to-canonical` CLI.
  bridge.py        Programmatic parser bridge.
  extraction/      Raw MinerU artifact loading and text extraction helpers.
  schema/          MinerU raw schema and pattern helpers.
  analysis/        Layout, style, geometry, and diagnostic analysis helpers.
  normalize/       MinerU raw outputs -> canonical/shadow artifacts.
  reconcile/       Cross-block reconciliation and parser-specific repairs.
```

Parser-specific data should stay in this package or in explicit provenance/debug
payloads on shadow artifacts.
