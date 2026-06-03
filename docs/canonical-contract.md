# Canonical Contract

`CanonicalDocument` is a parser-neutral JSON object with these required top-level fields:

- `metadata`: document identity and parser/source metadata.
- `blocks`: ordered reading-flow blocks.
- `toc`: nested table-of-contents entries.
- `assets`: extracted assets such as images.
- `source_map`: block-to-source references for traceability.

Required metadata fields:

- `doc_id`
- `title`
- `language`
- `source_file`
- `parser_name`
- `parser_mode`

Supported block types:

```text
heading paragraph epigraph blockquote signature list table figure caption
footnote_ref footnote equation page_break
```

Downstream packages must consume canonical fields instead of parser-private raw outputs. Parser-specific evidence can live under `block.attrs`.
