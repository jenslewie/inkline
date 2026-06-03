# inkline

Monorepo for document ingestion, canonical book representation, EPUB export, and RAG pipelines.

The first implementation keeps the pipeline centered on a parser-neutral `CanonicalDocument`:

```text
source document -> canonical.json -> EPUB
                              \-> chunks.jsonl -> embeddings -> FAISS/search
```

## Layout

```text
packages/book-canonical/  Canonical schema, validation, JSON/JSONL IO.
packages/book-ingest/     Lightweight ingestion interfaces.
packages/book-mineru/     MinerU integration and migrated MinerU normalizer code.
packages/book-epub/       CanonicalDocument to reflowable EPUB.
packages/book-rag/        CanonicalDocument to chunks, embeddings, index, search.
packages/book-cli/        Unified `inkline` CLI.
docs/                     Architecture and canonical contract notes.
tests/                    Cross-package smoke and regression tests.
```

## Quick Start

Run tests from the repository root:

```bash
python -m pytest -q
```

Use the CLI without installing by setting `PYTHONPATH` to the package source roots, or install the root project in editable mode.

```bash
inkline rag chunk data/outputs/sample/canonical.json --output data/outputs/sample/chunks.jsonl
inkline export epub data/outputs/sample/canonical.json --output data/outputs/sample/book.epub
```

`book-mineru` keeps MinerU and the migrated `mineru_normalizer` code isolated from the lightweight canonical, EPUB, and RAG packages.
