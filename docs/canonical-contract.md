# Canonical Contract

`CanonicalDocument` is a parser-neutral JSON object with these required top-level fields:

- `metadata`: document identity and parser/source metadata.
- `blocks`: ordered reading-flow blocks.
- `toc`: nested table-of-contents entries.
- `pages`: optional physical-page metadata.
- `assets`: extracted assets such as images.
- `source_map`: block-to-source references for traceability.

Required metadata fields:

- `schema_version`
- `doc_id`
- `title`
- `language`
- `source_file`
- `parser_name`
- `parser_mode`

Supported block types:

```text
heading paragraph toc_item display_block list_item table table_continuation
figure caption footnote
```

Downstream packages must consume canonical fields instead of parser-private raw outputs. Parser-specific evidence can live under `block.attrs`.

Display text uses the layout-first `display_block` type. Do not emit semantic
display block variants such as epigraph, blockquote, or signature; preserve
layout details under `block.attrs` instead.

Inline note references are represented in `block.attrs.inline_runs` as
`{"type": "note_ref", ...}` runs, not as top-level `footnote_ref` blocks.
Inline equation markers from parser-private inputs may remain as note-ref
sources, but canonical output does not use a top-level `equation` block.

`pages` describes physical pages without replacing reading-flow `blocks`.
Page metadata uses two coarse axes:

- `region`: `front_matter`, `content`, `back_matter`, or `unknown`.
- `page_role`: `cover`, `title_page`, `copyright_page`, `back_cover`,
  `generic`, or `unknown`.

When a page should preserve its visual presentation, `pages[*].snapshot` may
point to an image in `assets.images`. A snapshot asset is a rendition of the
page; it must not replace extractable text blocks. `figure` blocks represent
actual visual content in the book, such as diagrams, maps, and charts, not
generic page snapshots.

Canonical JSON written before `schema_version` was introduced is treated as the
implicit v0 format. `read_canonical()` migrates it to `1.0` in memory; validation
and newly written files remain strict about the version field.
