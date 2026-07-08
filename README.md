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
packages/inkline-llm/             Shared local LLM/Ollama clients.
packages/inkline-parse/           Parser protocol, registry, orchestration, and importers.
packages/inkline-parser-mineru/   MinerU adapter and MinerU-specific normalization.
packages/inkline-epub/            CanonicalDocument to reflowable EPUB.
packages/inkline-rag/             Chunking, embeddings, index, and search.
packages/inkline-cli/             Unified `inkline` CLI.
docs/                             Architecture and canonical contract notes.
tests/                            Cross-package smoke and regression tests.
```

### Canonical Package Structure

`packages/inkline-canonical` is the system hub: parser adapters write into it,
EPUB/RAG/export code read from it, and shadow BookGraph work evolves there
before becoming the release canonical contract. Its public facade is
`inkline.canonical`; implementation modules are grouped by contract layer:

```text
inkline/canonical/
  __init__.py              Public exports for stable callers.
  schema.py                Current canonical document schema and validation.
  io.py                    JSON read/write helpers for canonical artifacts.
  types.py                 Shared TypedDict-style legacy canonical types.
  source_map.py            Source/page/bbox mapping helpers.

  observed/                Parser-neutral ObservedDocument layer.
    schema.py              Observation, page, and document contracts.
    page_roles.py          Geometry-first page-role candidates.
    text_units.py          Natural text-unit construction.
    text_unit_layout.py    Layout-profile and text-unit audit helpers.

  book_skeleton/           TOC-driven book skeleton layer.
    contract.py            Skeleton schema and role contracts.
    toc.py                 TOC entry extraction and normalization.
    pages.py               Physical-page localization from observed titles.
    builder.py             Skeleton assembly from ObservedDocument evidence.
    validation.py          Skeleton contract validation.

  bookgraph/               BookGraph v2 shadow layer.
    schema.py              Public BookGraph node/edge/evidence contract.
    from_observed.py       ObservedDocument -> BookGraph builder.
    notes.py               Note/reference relation helpers.
    projection.py          BookGraph -> legacy block projection bridge.
    audit.py               Projection and structure audit helpers.
    internal.py            Internal audit artifact with debug provenance.
    footnote_text.py       Footnote text normalization utilities.
```

The intended data flow is:

```text
parser output -> ObservedDocument -> BookSkeleton -> BookGraph -> projections
```

`ObservedDocument`, `BookSkeleton`, `BookGraph`, and `internal_canonical` are
still pre-release development artifacts. They should make parser-neutral
structure explicit without leaking MinerU-specific fields into public contracts.
Parser-specific payloads belong in provenance/debug payload fields, not in the
top-level canonical schema.

As a maintainability guardrail, avoid growing `inkline.canonical` back into a
large flat namespace. If a package grows beyond 10 top-level modules, evaluate
whether related modules should become a subpackage with a small public facade.
`tests/test_canonical_package_structure.py` enforces this for
`inkline.canonical`; if Ruff or Pylint gains a native package-module-count rule,
enable it there as well.

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
