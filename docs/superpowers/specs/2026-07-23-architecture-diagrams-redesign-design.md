# Architecture Diagrams Redesign

## Goal

Replace the two diagrams in `docs/architecture.md` with Markdown-native Mermaid
flowcharts that make the canonical-v2 architecture and actual runtime data flow
immediately understandable.

## Architecture Diagram

Use a top-to-bottom layered flowchart. Group nodes by responsibility rather than
by call order:

1. Sources and parser adapters.
2. Parser-neutral evidence (`ObservedDocument`).
3. Book interpretation (`BookSkeleton`, `PageReview`, and text flow).
4. Planned relation stages (`SectionMap` and `VisualRelationReview`).
5. Graph construction and downstream products.

Solid arrows represent implemented dependencies. Dashed arrows represent planned
canonical-v2 dependencies or migration targets. Keep the legacy canonical-v1
release path visible, but visually separate it from canonical v2.

## Runtime Workflow Diagram

Replace the sequence diagram with a top-to-bottom artifact-driven flowchart. Show
each builder between its inputs and output artifact. The diagram must make these
facts explicit:

- `BookSkeleton` consumes `ObservedDocument`.
- `PageReview` consumes both `ObservedDocument` and `BookSkeleton`.
- Unresolved PageReview candidates with the LLM disabled stop the workflow and
  return intermediate artifacts.
- A resolved PageReview is validated before retained pages are materialized.
- Page asset materialization consumes `ObservedDocument` and `PageReview` and
  produces `ObservedDocument with assets`.
- Public BookGraph and internal canonical construction currently repeat the same
  observed-to-BookGraph pipeline.
- `SectionMap` and `VisualRelationReview` are not current runtime stages.

## Rendering Constraints

- Use Mermaid `flowchart` syntax only.
- Do not use `sequenceDiagram` call/return arrows.
- Do not use HTML such as `<br/>` in labels.
- Keep labels short and use subgraphs or adjacent explanatory prose for detail.
- Use plain solid and dashed edges rather than styling that depends on a specific
  Mermaid renderer.

## Acceptance Criteria

- Both diagrams render in Markdown Preview without exposing Mermaid or HTML markup.
- A reader can identify the `ObservedDocument -> BookSkeleton` dependency and the
  combined `ObservedDocument + BookSkeleton -> PageReview` dependency at a glance.
- Current and planned paths cannot be mistaken for one another.
- The runtime early-return branch and duplicated graph construction remain visible.
- Surrounding prose agrees with the diagrams and the current implementation.
