# Architecture Diagrams Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace both diagrams in `docs/architecture.md` with direct Mermaid flowcharts that clearly separate architectural layers from runtime artifact flow.

**Architecture:** The architecture diagram will group the release-v1 path and canonical-v2 layers by responsibility, with solid current dependencies and dashed planned dependencies. The runtime diagram will show builders, artifacts, the PageReview early-return decision, asset materialization, and duplicated public/internal construction as a top-to-bottom data flow.

**Tech Stack:** Markdown, Mermaid `flowchart`, shell-based documentation checks

## Global Constraints

- Use Mermaid `flowchart` syntax only.
- Do not use `sequenceDiagram`, participant call/return arrows, or HTML labels.
- Solid arrows represent implemented dependencies.
- Dashed arrows represent planned dependencies or migration targets only.
- Keep the current release-v1 path visible and separate from canonical v2.
- Preserve the PageReview early return and duplicated graph construction in the runtime diagram.

---

### Task 1: Replace Both Architecture Diagrams

**Files:**
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: The current `build_v2_artifacts()` stage order and the diagram design in `docs/superpowers/specs/2026-07-23-architecture-diagrams-redesign-design.md`.
- Produces: Two Markdown-native Mermaid flowcharts: a layered dependency view and an artifact-driven runtime view.

- [ ] **Step 1: Run a characterization check that fails on the current runtime diagram**

Run:

```bash
if rg -q '^sequenceDiagram$|^[[:space:]]+participant ' docs/architecture.md; then
  echo 'FAIL: call-return sequence syntax remains'
  exit 1
fi
```

Expected: exit 1 with `FAIL: call-return sequence syntax remains`.

- [ ] **Step 2: Replace the Architecture Dependency Graph Mermaid block**

Use a top-to-bottom flowchart with these responsibility groups and edges:

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

Keep adjacent prose explicit that `SectionMap` and `VisualRelationReview` are not current runtime stages and that `materialize_v2_page_assets` renders whole physical pages only.

- [ ] **Step 3: Replace the Current Canonical-v2 Runtime Sequence Mermaid block**

Use a top-to-bottom artifact flow with builder nodes between inputs and outputs:

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

Update the surrounding prose so it describes artifact flow rather than orchestrator messages. State in prose that physical-page anchors are resolved against `ObservedDocument` evidence and that `SectionMap` and `VisualRelationReview` are absent from this runtime.

- [ ] **Step 4: Run focused Markdown and Mermaid checks**

Run:

```bash
test "$(rg -c '^```mermaid$' docs/architecture.md)" -eq 2
! rg -n '^sequenceDiagram$|^[[:space:]]+participant |<br[[:space:]]*/?>' docs/architecture.md
rg -n 'ObservedDocument.*BookSkeleton|BookSkeleton.*PageReview|Candidates unresolved|graph pipeline runs twice' docs/architecture.md
git diff --check
```

Expected: exit 0; exactly two Mermaid blocks; no sequence or HTML syntax; all four architecture/runtime facts found; no whitespace errors.

- [ ] **Step 5: Review the rendered source and commit**

Run:

```bash
git diff -- docs/architecture.md
git status --short
```

Expected: only `docs/architecture.md` is modified and both original diagram blocks are replaced without unrelated prose changes.

Commit:

```bash
git add docs/architecture.md
git commit -m "docs: clarify architecture and runtime diagrams"
```
