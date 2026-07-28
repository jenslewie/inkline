# inkline-parse

`inkline-parse` defines the parser-facing abstraction layer. It lets the CLI and
orchestration code talk to parser adapters without importing parser-specific
normalization internals.

## Public Role

- Owns the `DocumentParser` protocol and parser result types.
- Owns the parser registry and entry-point discovery.
- Owns parser run state used by ingestion orchestration.
- Owns target canonical artifact-DAG scheduling and optional artifact
  materialization/resume policy; domain contracts and builders remain in
  `inkline-canonical`.
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
  canonical_v2.py  Target parser-neutral canonical artifact-DAG orchestrator.
```

Parser adapters, such as `inkline-parser-mineru`, should implement this package's
protocol and register through the `inkline.parsers` entry-point group.

The target orchestrator receives an adapter-produced ObservedDocument and calls the
explicit canonical builders in dependency order. It must build PageLayoutAnalysis and
TextFlow once, may write validated artifacts for resume/golden review, and must not
contain MinerU-specific rules. This deterministic interface is also the boundary a
future agent scheduler can call without moving domain decisions into prompts.
