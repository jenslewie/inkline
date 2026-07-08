from inkline.canonical.bookgraph.audit import audit_bookgraph
from inkline.canonical.bookgraph.footnote_text import strip_footnote_marker
from inkline.canonical.bookgraph.from_observed import (
    build_bookgraph_from_observed,
    build_internal_canonical_from_observed,
)
from inkline.canonical.bookgraph.internal import (
    INTERNAL_CANONICAL_SCHEMA_NAME,
    INTERNAL_CANONICAL_SCHEMA_VERSION,
    make_internal_canonical,
    validate_internal_canonical,
)
from inkline.canonical.bookgraph.notes import (
    audit_bookgraph_notes,
    normalize_bookgraph_note_sections,
    normalize_bookgraph_notes,
    resolve_bookgraph_note_refs,
    resolve_page_footnote_refs,
)
from inkline.canonical.bookgraph.projection import bookgraph_to_blocks
from inkline.canonical.bookgraph.schema import (
    BOOKGRAPH_SCHEMA_NAME,
    BOOKGRAPH_SCHEMA_VERSION,
    make_bookgraph,
    make_edge,
    make_evidence,
    make_node,
    validate_bookgraph,
)

__all__ = [
    "BOOKGRAPH_SCHEMA_NAME",
    "BOOKGRAPH_SCHEMA_VERSION",
    "INTERNAL_CANONICAL_SCHEMA_NAME",
    "INTERNAL_CANONICAL_SCHEMA_VERSION",
    "audit_bookgraph",
    "audit_bookgraph_notes",
    "bookgraph_to_blocks",
    "build_bookgraph_from_observed",
    "build_internal_canonical_from_observed",
    "make_bookgraph",
    "make_edge",
    "make_evidence",
    "make_internal_canonical",
    "make_node",
    "normalize_bookgraph_note_sections",
    "normalize_bookgraph_notes",
    "resolve_bookgraph_note_refs",
    "resolve_page_footnote_refs",
    "strip_footnote_marker",
    "validate_bookgraph",
    "validate_internal_canonical",
]
