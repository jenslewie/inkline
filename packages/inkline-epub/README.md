# inkline-epub

`inkline-epub` renders canonical documents into reflowable EPUB output.

## Public Role

- Consumes `CanonicalDocument` data from `inkline-canonical`.
- Renders text, notes, figures, tables, visual pages, navigation, package
  metadata, and theme assets.
- Owns EPUB presentation choices that should not mutate canonical data.
- Does not parse source PDFs, call OCR/LLM repair, or change canonical contracts.

## Main Areas

```text
inkline/epub/
  exporter.py      Public export entry point.
  renderer.py      Document rendering orchestration.
  markup.py        Shared XHTML helpers.
  assets/          Asset path/materialization helpers.
  chapter/         Chapter model and splitting.
  figure/          Figure/image/visual-page rendering.
  navigation/      TOC/nav document rendering.
  package/         OPF/package metadata rendering.
  table/           Table rendering.
  text/            Text and note rendering.
  theme/           CSS/theme output.
```

When a problem is purely about EPUB presentation, prefer fixing it here instead
of changing canonical data.
