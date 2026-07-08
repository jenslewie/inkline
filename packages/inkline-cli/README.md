# inkline-cli

`inkline-cli` is the unified command-line surface for inkline.

## Public Role

- Provides the `inkline` console script.
- Wires parser ingestion, EPUB export, and RAG commands together.
- Delegates implementation to the package that owns each domain.
- Does not contain parser-specific normalization, canonical schema logic, EPUB
  rendering internals, or RAG algorithms.

## Main Modules

```text
inkline/cli/
  main.py          Top-level CLI command definitions.
```

Keep this package thin: it should validate CLI arguments, call the owning
package, and report user-facing results.
