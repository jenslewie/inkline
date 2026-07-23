# Architecture

`inkline` is a monorepo with multiple Python packages. The main design rule is
that `inkline.canonical` is the only cross-stage document contract.

## Architecture Dependency Graph

This diagram describes ownership and data dependencies. Solid arrows are implemented
today. Dashed arrows are planned canonical-v2 stages and must not be read as current
runtime behavior.

```mermaid
flowchart TB
    source["PDF / EPUB / Word"] --> adapter["Parser adapter"]

    subgraph release_v1["Current release path"]
        legacy_builder["Legacy canonical builder"] --> canonical_v1["canonical.json"]
        canonical_v1 --> release_products["EPUB and RAG"]
    end
    adapter --> legacy_builder

    subgraph evidence["Canonical v2: parser-neutral evidence"]
        observed["ObservedDocument"]
    end
    adapter -->|"MinerU v2 path"| observed

    subgraph interpretation["Canonical v2: book interpretation"]
        skeleton["BookSkeleton: hierarchy and page anchors"]
        page_review["PageReview: page identity and consumption"]
        text_flow["TextUnits and logical units"]
        page_assets["Retained whole-page assets"]
    end
    observed --> skeleton
    observed --> page_review
    skeleton --> page_review
    observed --> text_flow
    observed --> page_assets
    page_review --> page_assets

    subgraph planned_relations["Canonical v2: planned relations"]
        section_map["SectionMap"]
        visual_review["VisualRelationReview"]
    end
    skeleton -.-> section_map
    page_review -.-> section_map
    text_flow -.-> section_map
    observed -.-> visual_review
    page_review -.-> visual_review

    subgraph graph_projection["Canonical v2: graph projection"]
        current_builder["Observed BookGraph builder"]
        public_graph["Public BookGraph"]
        internal_canonical["Internal canonical"]
        current_builder --> public_graph
        current_builder --> internal_canonical
    end
    text_flow --> current_builder
    page_review --> current_builder
    page_assets --> current_builder
    section_map -.-> current_builder
    visual_review -.-> current_builder
    public_graph -.->|"release migration target"| release_products
```

The important boundaries are:

- `PageReview` depends on both `ObservedDocument` and `BookSkeleton`. Skeleton supplies
  TOC pages, provisional matter boundaries, and title-start anchors; PageReview does
  not turn those anchors into logical section membership.
- `materialize_v2_page_assets` renders every page whose PageReview
  `visual_asset_action` is `retain`. It adds whole-page PNG records to
  `ObservedDocument.assets.images`; it does not perform OCR repair, image cropping,
  caption matching, or section assignment.
- `SectionMap` and `VisualRelationReview` are planned. Neither currently participates
  in BookGraph construction.
- EPUB and RAG still consume `canonical.json` by default. BookGraph is the migration
  target, not the current release input.

## Current Canonical-v2 Runtime Flow

This diagram follows the artifacts produced by `build_v2_artifacts()` and the current
observed BookGraph builder. Builders sit between their inputs and outputs, so the
data dependencies remain visible without call-and-return arrows.

```mermaid
flowchart TD
    raw["Raw MinerU inputs"] --> build_observed["1. Build ObservedDocument"]
    build_observed --> observed["ObservedDocument"]

    observed --> build_skeleton["2. Build BookSkeleton: optional TOC LLM"]
    build_skeleton --> skeleton["BookSkeleton"]

    observed --> build_review["3. Build PageReview: layout plus skeleton context"]
    skeleton --> build_review
    build_review --> page_review["PageReview"]

    page_review --> unresolved{"Candidates unresolved and PageReview LLM disabled?"}
    unresolved -->|"Yes"| intermediate["Return intermediate artifacts only"]
    unresolved -->|"No"| validate["4. Validate resolved PageReview"]

    observed --> materialize["5. Materialize retained physical pages"]
    validate --> materialize
    materialize --> observed_assets["ObservedDocument with 150-DPI page assets"]

    subgraph duplicated_build["Current implementation: graph pipeline runs twice"]
        public_builder["6a. Build public graph artifacts"]
        internal_builder["6b. Build internal canonical artifacts"]
    end
    observed_assets --> public_builder
    page_review --> public_builder
    observed_assets --> internal_builder
    page_review --> internal_builder
    public_builder --> public_graph["Public BookGraph"]
    internal_builder --> internal_canonical["Internal canonical"]
```

BookSkeleton may use an optional TOC LLM, but its physical-page anchors are resolved
against `ObservedDocument` evidence. PageReview rebuilds TextUnits, audits layout,
classifies page roles, and combines those results with Skeleton boundaries, TOC pages,
and body-section starts.

The current duplication between public and internal construction is real: both entry
points call `build_observed_bookgraph_artifacts()` independently. `SectionMap` and
`VisualRelationReview` are not present in this runtime yet. A future integration should
build the shared observed, text-flow, and relation artifacts once, then derive both
outputs from that single result.

## Package Boundaries

- `inkline-canonical` owns types, schema versioning, validation, provenance, and IO.
- `inkline-llm` owns local model clients such as Ollama chat/vision helpers. It
  must not know about canonical documents, parser internals, RAG records, or note
  repair semantics.
- `inkline-parse` owns the parser protocol, registry, task state, and orchestration.
- `inkline-parser-mineru` implements the protocol and owns MinerU-specific extraction,
  normalization, layout repair, note recovery, marker-locator prompts/evidence,
  and raw outputs. It may use `inkline-llm` for Qwen calls.
- A future `inkline-parser-paddle` package should implement the same protocol.
- `inkline-epub` consumes canonical JSON only.
- `inkline-rag` consumes canonical JSON or chunk JSONL only. Answer-generation
  features may use `inkline-llm`, but must not import parser adapters.
- `inkline-cli` wires packages together without owning parser behavior.

## Dependency Direction

```text
inkline-canonical
       ^
       |
inkline-parse <--- inkline-parser-mineru
       ^
       |
inkline-cli ---> inkline-epub
       \------> inkline-rag

inkline-llm <--- inkline-parser-mineru
      ^
      \------ inkline-rag
```

Parser adapters may depend on `inkline-parse` and `inkline-canonical`.
The common packages must never import a concrete parser adapter.
Installed adapters register themselves through the `inkline.parsers` entry-point
group, so the CLI does not maintain a hard-coded parser list.

`inkline-llm` is a shared service package, not a document contract. It provides
transport and response-shaping helpers for local LLMs; domain-specific prompts,
evidence schemas, and writeback behavior belong to the package that owns that
workflow. Shared defaults such as the local Ollama chat URL and the default Qwen
model live here so parser and RAG packages do not duplicate model wiring.

## Migration Notes

- `pdf-parser-eval` remains the source of parser evaluation history and the first canonical contract.
- The former standalone MinerU normalization code now lives directly under
  `inkline.parsers.mineru`; its algorithms remain parser-specific until
  a second adapter demonstrates a real reusable normalization boundary.
- `corpus-rag` provides RAG implementation patterns, but its EPUB normalized JSONL is not a long-term boundary.
- `booksmith` provides the EPUB packaging direction; this repository starts with a dependency-free EPUB writer that can be swapped for a richer builder without changing the canonical contract.
