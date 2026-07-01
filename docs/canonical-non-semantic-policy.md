# Canonical Non-Semantic Construction Policy

Canonical construction must be evidence-based, parser-neutral, and non-semantic.

This policy applies to ObservedDocument, BookGraph, projections, parser adapters,
and migration helpers. It is stricter than ordinary implementation guidance:
canonical data represents observable book structure, not an interpretation of
the text's meaning.

## Allowed Signals

Canonical builders may use deterministic structural evidence:

- parser explicit structure, normalized through adapter-owned mappings
- reading order
- page number and page position
- bbox geometry and relative layout
- typography, style, line height, and spacing
- cross-page continuity
- explicit markers, note references, and reference targets
- provenance, confidence, and source spans
- punctuation or numbering format only as weak format evidence

## Forbidden Signals

Canonical builders must not use semantic guessing:

- text meaning
- book topic, historical context, or narrative content
- keyword rules that classify structure by content meaning
- book-specific sentence anchors
- LLM classification of heading, paragraph, display block, caption, or footnote
- parser-specific raw labels as canonical contract fields

Parser-specific data belongs in adapter code or `parser_payload`. Migration data
from v1 canonical belongs in explicitly named legacy fields, not in the long-term
BookGraph contract.

## Layer Boundaries

ObservedDocument records what a parser observed. It may carry parser payloads,
but its top-level fields must remain parser-neutral.

BookGraph records logical book structure. Its nodes and edges may refer to
evidence, but parser-specific labels cannot become top-level schema fields.

Projections adapt BookGraph for EPUB, RAG, or migration comparison. They must not
change canonical structure based on downstream convenience.

Semantic enrichment may exist later as a derived layer outside canonical, such as
RAG indexes, topic graphs, or LLM annotations. Those layers must not rewrite node
types, reading order, evidence, or source relationships.
