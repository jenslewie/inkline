# inkline

Composable document parsing, canonical representation, EPUB export, and RAG pipelines.

The pipeline is centered on a parser-neutral `CanonicalDocument`:

```text
source document -> parser adapter -> canonical.json -> EPUB
                                             \-> chunks.jsonl -> embeddings -> FAISS/search
```

## Layout

| Path | Responsibility |
| --- | --- |
| [packages/inkline-canonical](packages/inkline-canonical/README.md) | Stable document contract, parser-neutral shadow contracts, validation, and IO. |
| [packages/inkline-parse](packages/inkline-parse/README.md) | Parser protocol, registry, orchestration state, and non-PDF importers. |
| [packages/inkline-parser-mineru](packages/inkline-parser-mineru/README.md) | MinerU adapter, raw artifact loading, MinerU normalization, and parser-specific repairs. |
| [packages/inkline-epub](packages/inkline-epub/README.md) | `CanonicalDocument` to reflowable EPUB rendering. |
| [packages/inkline-rag](packages/inkline-rag/README.md) | Canonical chunking, embeddings, FAISS indexing, and search. |
| [packages/inkline-llm](packages/inkline-llm/README.md) | Shared local LLM/Ollama client defaults and request helpers. |
| [packages/inkline-cli](packages/inkline-cli/README.md) | Unified `inkline` command-line interface. |
| [docs](docs/) | Cross-package architecture notes, canonical design records, and phase plans. |
| [tests](tests/) | Cross-package smoke, contract, and regression tests. |

The root README is intentionally a project map. Package internals belong in the
package README, while cross-package architecture decisions belong in `docs/`.

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

During BookGraph shadow development, `inkline ingest pdf` can also write parser-neutral
ObservedDocument and observed BookGraph artifacts:

```bash
uv run --extra mineru inkline ingest pdf data/samples/丝绸之路新史.pdf \
  --parser mineru \
  --output data/outputs/丝绸之路新史/canonical.json \
  --observed-output data/outputs/丝绸之路新史/observed_document.json \
  --bookgraph-from-observed-output data/outputs/丝绸之路新史/canonical_v2_observed.json \
  --internal-canonical-output data/outputs/丝绸之路新史/internal_canonical.json \
  --book-skeleton-output data/outputs/丝绸之路新史/book_skeleton.json
```

MinerU ingestion keeps Qwen visual marker repair disabled by default. Enable it
with `--marker-locator-repair`; it uses `qwen3.6:35b-a3b` at 150 DPI for full
pages and 200 DPI for paragraph-block retries. The shared Ollama/Qwen client
lives in `inkline-llm`, which owns the default model and Ollama endpoint
constants; marker-locator prompts, evidence files, and note writeback rules stay
inside `inkline-parser-mineru`.

To reuse existing MinerU raw outputs without rerunning MinerU, call the
parser-specific `mineru-to-canonical` command directly and pass the raw files:

```bash
uv run --extra mineru mineru-to-canonical \
  --content-list-v2 data/outputs/丝绸之路新史/mineru_raw/丝绸之路新史/vlm/丝绸之路新史_content_list_v2.json \
  --middle data/outputs/丝绸之路新史/mineru_raw/丝绸之路新史/vlm/丝绸之路新史_middle.json \
  --model data/outputs/丝绸之路新史/mineru_raw/丝绸之路新史/vlm/丝绸之路新史_model.json \
  --md data/outputs/丝绸之路新史/mineru_raw/丝绸之路新史/vlm/丝绸之路新史.md \
  --source-pdf data/samples/丝绸之路新史.pdf \
  --doc-id 丝绸之路新史 \
  --title 丝绸之路新史 \
  --marker-locator-repair \
  --output data/outputs/丝绸之路新史/canonical.json \
  --bookgraph-output data/outputs/丝绸之路新史/canonical_v2.json
```

`--source-pdf` is required when `--marker-locator-repair` is enabled because the
Qwen locator renders PDF pages for visual marker evidence. Marker evidence and
timing logs default to a sibling directory named after the output stem, such as
`data/outputs/丝绸之路新史/canonical_qwen_marker_locator/`.

`canonical_v2.json` is a pre-release BookGraph shadow artifact. It validates the
next canonical shape during development, but it is not a long-term compatibility
API or release contract. Before the first public release, the goal is still to
ship one canonical contract rather than v1/v2 side by side. Existing EPUB and
RAG flows continue to consume `canonical.json` by default until the BookGraph
projection switch is complete.

To inspect the shadow output against the current canonical blocks, run:

```bash
uv run inkline canonical audit-bookgraph \
  data/outputs/丝绸之路新史/canonical_v2.json \
  --legacy-canonical data/outputs/丝绸之路新史/canonical.json \
  --output data/outputs/丝绸之路新史/bookgraph_audit.json
```

For an existing `canonical.json`, the development helper can build the shadow
BookGraph and audit it in one step without rerunning MinerU:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/audit_bookgraph_shadow.py \
  data/outputs/golden/壬辰战争/canonical.json \
  --bookgraph-output /tmp/inkline-imjin-canonical_v2.json \
  --audit-output /tmp/inkline-imjin-bookgraph-audit.json \
  --expect-exact-projection \
  --fail-on-structure-warnings
```

Use this as a pre-release diagnostic gate. For example, the known-bad archived
`壬辰战争_20260629_134600` canonical trips the structure warning because
`display_block` nodes outnumber paragraphs. The `丝绸之路新史` golden canonical is
the current verified oracle for `display_block` and `heading`; the `壬辰战争`
golden canonical remains useful for smoke diagnostics, but still has known
content/classification issues and should not be used as a strict oracle yet.

Phase 2 also supports an ObservedDocument shadow path. This path records
parser-neutral observations first, then builds an experimental BookGraph from
those observations:

```bash
uv run --extra mineru mineru-to-canonical \
  ...existing args... \
  --output data/outputs/丝绸之路新史/canonical.json \
  --observed-output data/outputs/丝绸之路新史/observed_document.json \
  --bookgraph-from-observed-output data/outputs/丝绸之路新史/canonical_v2_observed.json \
  --internal-canonical-output data/outputs/丝绸之路新史/internal_canonical.json \
  --book-skeleton-output data/outputs/丝绸之路新史/book_skeleton.json
```

`canonical_v2_observed.json` is the public BookGraph projection for development.
`internal_canonical.json` is the audit-first superset: it contains the same
public projection plus per-page/node/edge/evidence debug provenance, TextUnits,
layout audit, page-role candidates, and parser payload snapshots for internal
troubleshooting.

`book_skeleton.json` is a pre-release shadow artifact for TOC-driven book
skeleton detection before BookGraph node construction. Add `--book-skeleton-llm`
to use the local Ollama model to classify TOC entries into front matter, body,
and back matter. The LLM is not allowed to decide PDF physical page numbers;
those still come from ObservedDocument title evidence.

To compare the v1-shadow and ObservedDocument-shadow BookGraph paths:

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/compare_bookgraph_shadow_paths.py \
  data/outputs/丝绸之路新史/canonical.json \
  data/outputs/丝绸之路新史/observed_document.json \
  --output data/outputs/丝绸之路新史/bookgraph_shadow_path_compare.json
```

RAG chunking, embedding, indexing, and search live in `inkline-rag`. Future
answer-generation code should use `inkline-llm` for the local model call and
consume canonical/chunk/search records rather than importing parser-specific
repair modules.

Parser-specific dependencies and repair logic stay inside parser adapters. A future
PaddleOCR integration should live in `inkline-parser-paddle` and implement the
same `inkline.parse.DocumentParser` protocol plus an `inkline.parsers` entry point.
