from __future__ import annotations

from inkline.canonical import (
    BOOKGRAPH_SCHEMA_NAME,
    BOOKGRAPH_SCHEMA_VERSION,
    audit_bookgraph_notes,
    make_bookgraph,
    make_edge,
    make_evidence,
    make_node,
    normalize_bookgraph_note_sections,
    normalize_bookgraph_notes,
    resolve_bookgraph_note_refs,
    resolve_page_footnote_refs,
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


def test_normalize_bookgraph_notes_marks_note_section_candidate_without_page_foot_claim() -> None:
    graph = make_bookgraph(
        _metadata(),
        [
            make_node(
                "n000001",
                "footnote",
                "1. Section note candidate.",
                attrs={
                    "source_text_unit_id": "tu000001",
                    "page_role": "note_section_candidate",
                },
                evidence_ids=["ev000001"],
            ),
        ],
        [],
        [make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=500)],
        projections={"reading_order": ["n000001"]},
    )

    normalized = normalize_bookgraph_notes(graph)

    note = normalized["nodes"][0]
    assert note["node_type"] == "note"
    assert note["attrs"]["marker"] == "1"
    assert note["attrs"]["source_placement"] == "note_section_candidate"
    assert note["attrs"]["scope"] == "unknown"


def test_normalize_bookgraph_note_sections_promotes_reference_entries_to_notes() -> None:
    graph = make_bookgraph(
        _metadata(),
        [
            make_node("n000001", "heading", "正文第一章", attrs={}, evidence_ids=["ev000001"]),
            make_node("n000002", "paragraph", "Body.", attrs={}, evidence_ids=["ev000002"]),
            make_node("n000003", "heading", "注释", attrs={}, evidence_ids=["ev000003"]),
            make_node("n000004", "heading", "正文第一章", attrs={}, evidence_ids=["ev000004"]),
            make_node(
                "n000005",
                "list_item",
                "1. A chapter note.",
                attrs={"source_text_unit_id": "tu000005"},
                evidence_ids=["ev000005"],
            ),
        ],
        [],
        [
            make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=10),
            make_evidence("ev000002", "mineru", "tu000002", source_kind="text_unit", page=10),
            make_evidence("ev000003", "mineru", "tu000003", source_kind="text_unit", page=90),
            make_evidence("ev000004", "mineru", "tu000004", source_kind="text_unit", page=90),
            make_evidence("ev000005", "mineru", "tu000005", source_kind="text_unit", page=90),
        ],
        projections={
            "reading_order": ["n000001", "n000002", "n000003", "n000004", "n000005"]
        },
    )

    normalized = normalize_bookgraph_note_sections(graph)

    validate_bookgraph(normalized)
    note = normalized["nodes"][4]
    assert note["node_type"] == "note"
    assert note["text"] == "A chapter note."
    assert note["attrs"]["marker"] == "1"
    assert note["attrs"]["source_placement"] == "book_end"
    assert note["attrs"]["scope"] == "chapter"
    assert note["attrs"]["scope_key"] == "正文第一章"
    assert normalized["metadata"]["shadow_note_section_detection"] == {
        "explicit_note_section_count": 1,
        "promoted_note_count": 1,
        "promoted_page_foot_reference_count": 0,
    }


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


def test_resolve_page_footnote_refs_links_same_page_unique_marker() -> None:
    graph = make_bookgraph(
        _metadata(),
        [
            make_node(
                "n000001",
                "paragraph",
                "Body text 1.",
                inline_runs=[
                    {"type": "text", "text": "Body text "},
                    {"type": "note_ref", "text": "1", "marker": "1"},
                ],
                attrs={"source_text_unit_id": "tu000001"},
                evidence_ids=["ev000001"],
            ),
            make_node(
                "n000002",
                "footnote",
                "1. Page footnote.",
                attrs={"source_text_unit_id": "tu000002"},
                evidence_ids=["ev000002"],
            ),
        ],
        [],
        [
            make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=12),
            make_evidence("ev000002", "mineru", "tu000002", source_kind="text_unit", page=12),
        ],
        projections={"reading_order": ["n000001", "n000002"]},
    )

    resolved = resolve_page_footnote_refs(graph)

    validate_bookgraph(resolved)
    assert [node["node_type"] for node in resolved["nodes"]] == ["paragraph", "note"]
    assert resolved["nodes"][0]["inline_runs"][1]["attrs"] == {
        "marker": "1",
        "target_note_id": "n000002",
        "source_placement": "page_foot",
        "scope": "page",
        "match_confidence": "exact",
    }
    assert resolved["edges"] == [
        {
            "edge_type": "references_note",
            "source": "n000001",
            "target": "n000002",
            "evidence_ids": ["ev000001", "ev000002"],
            "attrs": {
                "marker": "1",
                "source_placement": "page_foot",
                "scope": "page",
                "match_confidence": "exact",
            },
        }
    ]
    assert resolved["metadata"]["shadow_note_ref_resolution"] == {
        "page_footnote_resolved": 1,
        "page_footnote_ambiguous": 0,
        "page_footnote_unresolved": 0,
    }


def test_resolve_page_footnote_refs_does_not_guess_ambiguous_marker() -> None:
    graph = make_bookgraph(
        _metadata(),
        [
            make_node(
                "n000001",
                "paragraph",
                "Body text 1.",
                inline_runs=[{"type": "note_ref", "text": "1", "marker": "1"}],
                attrs={"source_text_unit_id": "tu000001"},
                evidence_ids=["ev000001"],
            ),
            make_node(
                "n000002",
                "footnote",
                "1. First note.",
                attrs={"source_text_unit_id": "tu000002"},
                evidence_ids=["ev000002"],
            ),
            make_node(
                "n000003",
                "footnote",
                "1. Duplicate note.",
                attrs={"source_text_unit_id": "tu000003"},
                evidence_ids=["ev000003"],
            ),
        ],
        [],
        [
            make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=12),
            make_evidence("ev000002", "mineru", "tu000002", source_kind="text_unit", page=12),
            make_evidence("ev000003", "mineru", "tu000003", source_kind="text_unit", page=12),
        ],
        projections={"reading_order": ["n000001", "n000002", "n000003"]},
    )

    resolved = resolve_page_footnote_refs(graph)

    validate_bookgraph(resolved)
    assert "attrs" not in resolved["nodes"][0]["inline_runs"][0]
    assert resolved["edges"] == []
    assert resolved["metadata"]["shadow_note_ref_resolution"] == {
        "page_footnote_resolved": 0,
        "page_footnote_ambiguous": 1,
        "page_footnote_unresolved": 0,
    }


def test_resolve_bookgraph_note_refs_links_scoped_section_note() -> None:
    graph = make_bookgraph(
        _metadata(),
        [
            make_node("n000001", "heading", "正文第一章", attrs={}, evidence_ids=["ev000001"]),
            make_node(
                "n000002",
                "paragraph",
                "Body text 1.",
                inline_runs=[
                    {"type": "text", "text": "Body text "},
                    {"type": "note_ref", "text": "1", "marker": "1"},
                ],
                attrs={},
                evidence_ids=["ev000002"],
            ),
            make_node("n000003", "heading", "注释", attrs={}, evidence_ids=["ev000003"]),
            make_node("n000004", "heading", "正文第一章", attrs={}, evidence_ids=["ev000004"]),
            make_node(
                "n000005",
                "list_item",
                "1. A chapter note.",
                attrs={"source_text_unit_id": "tu000005"},
                evidence_ids=["ev000005"],
            ),
        ],
        [],
        [
            make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=10),
            make_evidence("ev000002", "mineru", "tu000002", source_kind="text_unit", page=10),
            make_evidence("ev000003", "mineru", "tu000003", source_kind="text_unit", page=90),
            make_evidence("ev000004", "mineru", "tu000004", source_kind="text_unit", page=90),
            make_evidence("ev000005", "mineru", "tu000005", source_kind="text_unit", page=90),
        ],
        projections={
            "reading_order": ["n000001", "n000002", "n000003", "n000004", "n000005"]
        },
    )

    resolved = resolve_bookgraph_note_refs(graph)

    validate_bookgraph(resolved)
    assert resolved["nodes"][4]["node_type"] == "note"
    assert resolved["nodes"][1]["inline_runs"][1]["attrs"] == {
        "marker": "1",
        "target_note_id": "n000005",
        "source_placement": "book_end",
        "scope": "chapter",
        "scope_key": "正文第一章",
        "match_confidence": "exact",
    }
    assert resolved["edges"][-1]["edge_type"] == "references_note"
    assert resolved["edges"][-1]["target"] == "n000005"
    assert resolved["metadata"]["shadow_scoped_note_ref_resolution"] == {
        "scoped_note_resolved": 1,
        "scoped_note_ambiguous": 0,
        "scoped_note_unresolved": 0,
    }


def test_resolve_bookgraph_note_refs_promotes_sparse_bottom_reference_text_to_page_foot() -> None:
    metadata = {
        **_metadata(),
        "shadow_page_sizes": [{"page": 12, "width": 1000.0, "height": 1000.0}],
    }
    graph = make_bookgraph(
        metadata,
        [
            make_node(
                "n000001",
                "paragraph",
                "Body text 1.",
                inline_runs=[{"type": "note_ref", "text": "1", "marker": "1"}],
                attrs={},
                evidence_ids=["ev000001"],
            ),
            make_node(
                "n000002",
                "list_item",
                "1. Bottom reference note.",
                attrs={
                    "source_text_unit_id": "tu000002",
                    "role_hints": ["reference_text"],
                },
                evidence_ids=["ev000002"],
            ),
        ],
        [],
        [
            make_evidence(
                "ev000001",
                "mineru",
                "tu000001",
                source_kind="text_unit",
                page=12,
                bbox=[100, 100, 900, 140],
            ),
            make_evidence(
                "ev000002",
                "mineru",
                "tu000002",
                source_kind="text_unit",
                page=12,
                bbox=[100, 720, 900, 760],
            ),
        ],
        projections={"reading_order": ["n000001", "n000002"]},
    )

    resolved = resolve_bookgraph_note_refs(graph)

    assert resolved["nodes"][1]["node_type"] == "note"
    assert resolved["nodes"][1]["attrs"]["page_foot_promotion"] == "bottom_reference_text"
    assert resolved["nodes"][0]["inline_runs"][0]["attrs"]["target_note_id"] == "n000002"
    assert resolved["metadata"]["shadow_note_section_detection"][
        "promoted_page_foot_reference_count"
    ] == 1
