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

  page_review/             Bounded multimodal page-review layer.
    selection.py            Geometry and skeleton evidence -> review candidates.
    llm.py                  Strict LLM decision prompt and request grouping.
    resolution.py           Decision validation and resolved-review contract.

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
parser output -> ObservedDocument -> BookSkeleton -> PageReview -> BookGraph -> projections
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

## PageReview Boundary

`PageReview` is an internal Phase 4A artifact. Its `page_role` has exactly two
reading-flow values: `text_flow_page` and `visual_page`. A map, image, diagram,
or table is evidence about a page, not a third reading-flow role. A page with
independent body paragraphs is `text_flow_page`; a page containing only visual
material, captions, or labels is `visual_page`.

Optional `special_page_kind` records a separate semantic identity such as
`cover_page`, `back_cover`, `cover_flap`, `dust_jacket_spread`, `front_board`,
`back_board`, `title_page`, `dedication_page`, `acknowledgments_page`,
`copyright_page`, `toc_page`, or `blank_page`. It
does not replace `page_role`. Resolved `visual_page` decisions cannot use
`text_flow_action = include`, which prevents image/caption OCR from silently
becoming reading-flow nodes. `visual_asset_action` independently controls
whether the rendered page image is retained for provenance and EPUB fidelity.
For `copyright_page`, PageReview deterministically uses `visual_page`,
`front_matter`, `metadata_only`, and `retain`: its text remains evidence for
later document-level metadata extraction, not reading-flow OCR or RAG chunks.
An `acknowledgments_page` is distinct from a dedication leaf: it remains
front-matter reading flow (`text_flow_page + include + not_needed`).

External-wrap identities are deliberately more precise than generic cover
pages: `dust_jacket_spread` is a flattened full jacket with its panels and
spine; `front_board` and `back_board` are hardcover boards visible after the
jacket is removed. All external-wrap identities normalize to
`visual_page + exclude + retain`.

`book_block_position` records the physical book position separately from the
reading-flow role: `external_wrap`, `front_matter`, `body`, `back_matter`, or
`unknown`. Before the first Skeleton body page, PageReview uses the provisional
internal context `pre_body`; it does not assume those pages are front matter. It
does deterministically materialize
`front_matter` for pages covered by a localized Skeleton front-matter section
and for `toc_page`. PageReview then closes the remaining pre-body `unknown`
pages with a bounded second LLM pass, so ordinary internal front prose does not
silently remain unresolved.
The LLM can identify an outer cover, back cover, or cover flap as
`external_wrap`. A book without those pages simply produces no such decision.

The current LLM scope is deliberately limited to `pre_body`. It runs in two
stages: selected visual candidates first, then every remaining pre-body page
whose `book_block_position` is still `unknown`. Body and back-matter pages
retain geometry and Skeleton decisions with `llm_review_status = not_selected`;
they are not rendered or sent to the model, and never retain a `needs_review`
consumption action.

The multimodal review prompt has a small common contract plus exactly one
evidence-selected profile per request group: `front_special`,
`front_residual_unknown`,
`body_section_start`, `visual_sparse_text`, `mixed_visual_body`,
`textual_table`, or `general`. Groups never mix profiles; pages are batched by
profile and `pre_body`/`body`/`back_matter` boundary in physical-page order,
up to the configured group size. A reviewed page keeps `llm_group_id` and
`llm_prompt_profile`; its group records the matter boundary and review stage,
while the top-level `llm` record stores the model and prompt version.

`table_region` always selects `textual_table`: a readable table and a table
continuation remain in reading flow even when they fill an entire page.

## Maintenance Guardrail

Avoid growing `inkline.canonical` back into a large flat namespace. If a package
grows beyond 10 top-level modules, evaluate whether related modules should
become a subpackage with a small public facade.
`tests/test_canonical_package_structure.py` enforces this for
`inkline.canonical`; if Ruff or Pylint gains a native package-module-count rule,
enable it there as well.
