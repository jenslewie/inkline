# inkline-canonical

`inkline-canonical` is the contract hub of inkline. Parser adapters write into
canonical contracts, EPUB/RAG/export code read from them, and shadow BookGraph
work evolves here before becoming the release canonical contract.

## Public Role

- Owns the current `CanonicalDocument` schema, validation, migration helpers,
  and JSON IO.
- Owns parser-neutral development contracts such as `ObservedDocument`,
  `BookSkeleton`, `BookGraph`, and `internal_canonical`.
- Keeps parser-specific details out of public canonical fields. Parser payloads
  belong in provenance/debug payload fields.
- Does not parse PDFs, call MinerU, render EPUB, or build RAG indexes.

## Package Structure

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
    toc_llm.py             LLM TOC JSON contract, prompt, and validation.
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

The intended development data flow is:

```text
parser output -> ObservedDocument -> BookSkeleton -> BookGraph -> projections
```

`ObservedDocument`, `BookSkeleton`, `BookGraph`, and `internal_canonical` are
pre-release development artifacts. Existing EPUB/RAG flows still consume the
current canonical contract until the BookGraph projection switch is complete.

## TOC LLM Boundary

The preferred TOC path is to let the LLM read the TOC visual structure and emit
public TOC entries: `display_title`, `level`, `parent_entry_index`, and `role`.
The prompt must define each field explicitly, including that `level` starts at 1
and `role` is limited to `front_matter`, `body`, `back_matter`, or `unknown`.

Code should not patch LLM-capable structure after the fact. If the model can
infer a field from the TOC image, improve the prompt/schema/examples first.
Deterministic code is responsible for validation and for facts outside the
LLM's evidence, especially `candidate_start_pages` and `selected_start_page`,
which are derived from ObservedDocument physical page evidence.

Public BookSkeleton TOC entries intentionally do not expose split
`raw_title`/`title`/`raw_label`/`label` fields. Internal builders may derive
temporary locator candidates from `display_title`, but those helpers are not
part of the public skeleton contract.

## Maintenance Guardrail

Avoid growing `inkline.canonical` back into a large flat namespace. If a package
grows beyond 10 top-level modules, evaluate whether related modules should
become a subpackage with a small public facade.
`tests/test_canonical_package_structure.py` enforces this for
`inkline.canonical`; if Ruff or Pylint gains a native package-module-count rule,
enable it there as well.
