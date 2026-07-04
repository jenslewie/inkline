from __future__ import annotations

from inkline.canonical import (
    BOOKGRAPH_SCHEMA_NAME,
    BOOKGRAPH_SCHEMA_VERSION,
    audit_bookgraph_notes,
    make_bookgraph,
    make_edge,
    make_evidence,
    make_node,
    normalize_bookgraph_notes,
    validate_bookgraph,
)


def _metadata() -> dict:
    return {
        "schema_name": BOOKGRAPH_SCHEMA_NAME,
        "schema_version": BOOKGRAPH_SCHEMA_VERSION,
        "doc_id": "sample",
        "title": "Sample",
        "language": "en",
        "source_file": "sample.pdf",
        "parser_name": "mineru",
        "parser_mode": "vlm",
    }


def test_normalize_bookgraph_notes_converts_footnote_nodes_to_note_nodes() -> None:
    graph = make_bookgraph(
        _metadata(),
        [
            make_node(
                "n000001",
                "paragraph",
                "Body text.",
                attrs={"source_text_unit_id": "tu000001"},
                evidence_ids=["ev000001"],
            ),
            make_node(
                "n000002",
                "footnote",
                "1. A page footnote.",
                attrs={"source_text_unit_id": "tu000002"},
                evidence_ids=["ev000002"],
            ),
        ],
        [make_edge("appears_on_page", "n000002", "page:1", evidence_ids=["ev000002"])],
        [
            make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=1),
            make_evidence("ev000002", "mineru", "tu000002", source_kind="text_unit", page=1),
        ],
        projections={"reading_order": ["n000001", "n000002"]},
    )

    normalized = normalize_bookgraph_notes(graph)

    validate_bookgraph(normalized)
    note = normalized["nodes"][1]
    assert note["node_type"] == "note"
    assert note["text"] == "A page footnote."
    assert note["attrs"]["marker"] == "1"
    assert note["attrs"]["source_placement"] == "page_foot"
    assert note["attrs"]["scope"] == "page"
    assert note["attrs"]["source_text_unit_ids"] == ["tu000002"]


def test_normalize_bookgraph_notes_keeps_existing_note_nodes() -> None:
    note = make_node(
        "n000001",
        "note",
        "Existing note.",
        attrs={
            "marker": "a",
            "source_placement": "book_end",
            "scope": "book",
            "source_text_unit_ids": ["tu000010"],
        },
        evidence_ids=["ev000001"],
    )
    graph = make_bookgraph(
        _metadata(),
        [note],
        [],
        [make_evidence("ev000001", "mineru", "tu000010", source_kind="text_unit", page=10)],
        projections={"reading_order": ["n000001"]},
    )

    normalized = normalize_bookgraph_notes(graph)

    assert normalized["nodes"] == [note]


def test_audit_bookgraph_notes_reports_resolved_and_orphan_notes() -> None:
    body = make_node(
        "n000001",
        "paragraph",
        "Body text 1 2.",
        inline_runs=[
            {
                "type": "note_ref",
                "text": "1",
                "attrs": {"marker": "1", "target_note_id": "n000002"},
            },
            {
                "type": "note_ref",
                "text": "2",
                "attrs": {"marker": "2", "match_confidence": "unresolved"},
            },
        ],
        attrs={"source_text_unit_id": "tu000001"},
        evidence_ids=["ev000001"],
    )
    note = make_node(
        "n000002",
        "note",
        "Resolved note.",
        attrs={
            "marker": "1",
            "source_placement": "page_foot",
            "scope": "page",
            "source_text_unit_ids": ["tu000002"],
        },
        evidence_ids=["ev000002"],
    )
    orphan_note = make_node(
        "n000003",
        "note",
        "Orphan note.",
        attrs={
            "marker": "3",
            "source_placement": "book_end",
            "scope": "book",
            "source_text_unit_ids": ["tu000003"],
        },
        evidence_ids=["ev000003"],
    )
    graph = make_bookgraph(
        _metadata(),
        [body, note, orphan_note],
        [make_edge("references_note", "n000001", "n000002", evidence_ids=["ev000001"])],
        [
            make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=1),
            make_evidence("ev000002", "mineru", "tu000002", source_kind="text_unit", page=1),
            make_evidence("ev000003", "mineru", "tu000003", source_kind="text_unit", page=10),
        ],
        projections={"reading_order": ["n000001", "n000002", "n000003"]},
    )

    assert audit_bookgraph_notes(graph) == {
        "note_count": 2,
        "legacy_footnote_count": 0,
        "references_note_edge_count": 1,
        "resolved_note_ref_count": 1,
        "unresolved_note_ref_count": 1,
        "orphan_note_count": 1,
        "notes_by_source_placement": {"book_end": 1, "page_foot": 1},
        "notes_by_scope": {"book": 1, "page": 1},
    }


def test_audit_bookgraph_notes_counts_legacy_top_level_note_ref_target() -> None:
    body = make_node(
        "n000001",
        "paragraph",
        "Body text 1.",
        inline_runs=[
            {
                "type": "note_ref",
                "text": "1",
                "target_note_id": "n000002",
            },
        ],
        attrs={"source_text_unit_id": "tu000001"},
        evidence_ids=["ev000001"],
    )
    note = make_node(
        "n000002",
        "note",
        "Resolved note.",
        attrs={
            "marker": "1",
            "source_placement": "page_foot",
            "scope": "page",
            "source_text_unit_ids": ["tu000002"],
        },
        evidence_ids=["ev000002"],
    )
    graph = make_bookgraph(
        _metadata(),
        [body, note],
        [make_edge("references_note", "n000001", "n000002", evidence_ids=["ev000001"])],
        [
            make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=1),
            make_evidence("ev000002", "mineru", "tu000002", source_kind="text_unit", page=1),
        ],
        projections={"reading_order": ["n000001", "n000002"]},
    )

    assert audit_bookgraph_notes(graph)["resolved_note_ref_count"] == 1
