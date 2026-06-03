# Architecture

`inkline` is a monorepo with multiple Python packages. The main design rule is that `book_canonical` is the only cross-stage document contract.

## Data Flow

```text
PDF/EPUB/Word
  -> ingest engine
  -> canonical.json
  -> EPUB exporter
  -> RAG chunker
  -> embeddings
  -> index/search/eval
```

## Package Boundaries

- `book-canonical` has no parser, EPUB, FAISS, or LLM dependencies.
- `book-ingest` defines lightweight ingestion interfaces and dispatch points.
- `book-mineru` contains MinerU-specific code, including the migrated `mineru_normalizer` package.
- `book-epub` consumes canonical JSON only.
- `book-rag` consumes canonical JSON or chunk JSONL only.
- `book-cli` wires packages together without owning core behavior.

## Migration Notes

- `pdf-parser-eval` remains the source of parser evaluation history and the first canonical contract.
- `pdf-parser-eval/mineru_normalizer` is migrated into `book-mineru` as an isolated compatibility package.
- `corpus-rag` provides RAG implementation patterns, but its EPUB normalized JSONL is not a long-term boundary.
- `booksmith` provides the EPUB packaging direction; this repository starts with a dependency-free EPUB writer that can be swapped for a richer builder without changing the canonical contract.
