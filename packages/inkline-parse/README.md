# inkline-parse

`inkline-parse` defines the parser-facing abstraction layer. It lets the CLI and
orchestration code talk to parser adapters without importing parser-specific
normalization internals.

## Public Role

- Owns the `DocumentParser` protocol and parser result types.
- Owns the parser registry and entry-point discovery.
- Owns parser run state used by ingestion orchestration.
- Provides non-PDF import helpers, such as EPUB import support.
- Does not know MinerU-specific schemas, repair rules, or raw artifact formats.

## Main Modules

```text
inkline/parse/
  __init__.py      Public parser abstraction exports.
  types.py         Parser protocol and result types.
  registry.py      Parser registration and discovery.
  state.py         Parser run state helpers.
  epub.py          EPUB import helper.
```

Parser adapters, such as `inkline-parser-mineru`, should implement this package's
protocol and register through the `inkline.parsers` entry-point group.
