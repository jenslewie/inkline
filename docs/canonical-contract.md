# Canonical Contract

`CanonicalDocument` is a parser-neutral JSON object with these required top-level fields:

- `metadata`: document identity and parser/source metadata.
- `blocks`: ordered reading-flow blocks.
- `toc`: nested table-of-contents entries.
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
heading paragraph toc_item display_block epigraph blockquote signature list
list_item table table_continuation figure caption footnote_ref footnote
equation page_break
```

Downstream packages must consume canonical fields instead of parser-private raw outputs. Parser-specific evidence can live under `block.attrs`.

Canonical JSON written before `schema_version` was introduced is treated as the
implicit v0 format. `read_canonical()` migrates it to `1.0` in memory; validation
and newly written files remain strict about the version field.
