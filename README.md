# inkline

Composable document parsing, canonical representation, EPUB export, and RAG pipelines.

The pipeline is centered on a parser-neutral `CanonicalDocument`:

```text
source document -> parser adapter -> canonical.json -> EPUB
                                             \-> chunks.jsonl -> embeddings -> FAISS/search
```

## Layout

```text
packages/inkline-canonical/       Stable document contract, validation, and IO.
packages/inkline-parse/           Parser protocol, registry, orchestration, and importers.
packages/inkline-parser-mineru/   MinerU adapter and MinerU-specific normalization.
packages/inkline-epub/            CanonicalDocument to reflowable EPUB.
packages/inkline-rag/             Chunking, embeddings, index, and search.
packages/inkline-cli/             Unified `inkline` CLI.
docs/                             Architecture and canonical contract notes.
tests/                            Cross-package smoke and regression tests.
```

## Quick Start

Install the workspace and run tests from the repository root:

```bash
uv sync
uv run python -m pytest -q
```

Install the optional MinerU adapter and its runtime before parsing PDFs:

```bash
uv sync --extra mineru
uv run inkline ingest pdf input.pdf --parser mineru --output data/outputs/sample/canonical.json
uv run inkline export epub data/outputs/sample/canonical.json --output data/outputs/sample/book.epub
uv run inkline rag chunk data/outputs/sample/canonical.json --output data/outputs/sample/chunks.jsonl
```

MinerU ingestion keeps Qwen visual marker repair disabled by default. Enable it
with `--marker-locator-repair`; it uses `qwen3.5:9b` at 300 DPI.

Parser-specific dependencies and repair logic stay inside parser adapters. A future
PaddleOCR integration should live in `inkline-parser-paddle` and implement the
same `inkline.parse.DocumentParser` protocol plus an `inkline.parsers` entry point.
