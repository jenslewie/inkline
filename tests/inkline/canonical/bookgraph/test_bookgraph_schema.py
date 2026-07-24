from __future__ import annotations

import pytest

from inkline.canonical import (
    BOOKGRAPH_SCHEMA_NAME,
    BOOKGRAPH_SCHEMA_VERSION,
    ValidationError,
    make_bookgraph,
    make_edge,
    make_evidence,
    make_node,
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


def _minimal_graph() -> dict:
    node = make_node(
        "n000001",
        "paragraph",
        "A paragraph.",
        attrs={"legacy_block_id": "b000001"},
        evidence_ids=["ev000001"],
    )
    evidence = make_evidence(
        "ev000001",
        "mineru",
        "b000001",
        source_kind="legacy_block",
        page=1,
        bbox=[10, 20, 100, 120],
        parser_payload={"legacy_type": "paragraph"},
    )
    return make_bookgraph(
        _metadata(),
        [node],
        [make_edge("appears_on_page", "n000001", "page:1", evidence_ids=["ev000001"])],
        [evidence],
        projections={"reading_order": ["n000001"], "epub_flow": ["n000001"], "rag_units": []},
    )


def test_minimal_valid_graph_passes() -> None:
    graph = _minimal_graph()

    validate_bookgraph(graph)


def test_evidence_keeps_parser_specific_raw_fields_in_payload() -> None:
    evidence = _minimal_graph()["evidence"][0]

    assert evidence["source_kind"] == "legacy_block"
    assert evidence["parser_payload"] == {"legacy_type": "paragraph"}
    assert "raw_type" not in evidence
    assert "raw_types" not in evidence


def test_missing_top_level_field_fails() -> None:
    graph = _minimal_graph()
    del graph["nodes"]

    with pytest.raises(ValidationError, match="nodes"):
        validate_bookgraph(graph)


def test_unknown_node_type_fails() -> None:
    graph = _minimal_graph()
    graph["nodes"][0]["node_type"] = "table"

    with pytest.raises(ValidationError, match="node_type"):
        validate_bookgraph(graph)


def test_duplicate_node_id_fails() -> None:
    graph = _minimal_graph()
    graph["nodes"].append(dict(graph["nodes"][0]))

    with pytest.raises(ValidationError, match="duplicate node_id"):
        validate_bookgraph(graph)


def test_edge_pointing_to_missing_node_fails() -> None:
    graph = _minimal_graph()
    graph["edges"].append(make_edge("references_note", "n000001", "n999999"))

    with pytest.raises(ValidationError, match="missing node"):
        validate_bookgraph(graph)


def test_reading_order_pointing_to_missing_node_fails() -> None:
    graph = _minimal_graph()
    graph["projections"]["reading_order"].append("n999999")

    with pytest.raises(ValidationError, match="reading_order"):
        validate_bookgraph(graph)


def test_note_node_with_references_note_edge_passes() -> None:
    body = make_node(
        "n000001",
        "paragraph",
        "Body text 1.",
        inline_runs=[
            {"type": "text", "text": "Body text "},
            {
                "type": "note_ref",
                "text": "1",
                "attrs": {"marker": "1", "target_note_id": "n000002"},
            },
        ],
        attrs={"source_text_unit_id": "tu000001"},
        evidence_ids=["ev000001"],
    )
    note = make_node(
        "n000002",
        "note",
        "A note.",
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
        [
            make_edge("references_note", "n000001", "n000002", evidence_ids=["ev000001"]),
        ],
        [
            make_evidence("ev000001", "mineru", "tu000001", source_kind="text_unit", page=1),
            make_evidence("ev000002", "mineru", "tu000002", source_kind="text_unit", page=1),
        ],
        projections={"reading_order": ["n000001", "n000002"]},
    )

    validate_bookgraph(graph)


def test_make_node_merges_adjacent_plain_text_inline_runs() -> None:
    node = make_node(
        "n000001",
        "paragraph",
        "abcdef",
        inline_runs=[
            {"type": "text", "text": "ab"},
            {"type": "text", "text": "cd"},
            {"type": "note_ref", "text": "1", "marker": "1"},
            {"type": "text", "text": "ef"},
        ],
        attrs={},
        evidence_ids=["ev000001"],
    )

    assert node["inline_runs"] == [
        {"type": "text", "text": "abcd"},
        {"type": "note_ref", "text": "1", "marker": "1"},
        {"type": "text", "text": "ef"},
    ]


def test_make_node_keeps_text_runs_with_different_metadata_separate() -> None:
    node = make_node(
        "n000001",
        "paragraph",
        "abcdef",
        inline_runs=[
            {"type": "text", "text": "ab", "attrs": {"style": "italic"}},
            {"type": "text", "text": "cd"},
            {"type": "text", "text": "ef"},
        ],
        attrs={},
        evidence_ids=["ev000001"],
    )

    assert node["inline_runs"] == [
        {"type": "text", "text": "ab", "attrs": {"style": "italic"}},
        {"type": "text", "text": "cdef"},
    ]


def test_adjacent_plain_text_inline_runs_fail_validation() -> None:
    graph = _minimal_graph()
    graph["nodes"][0]["inline_runs"] = [
        {"type": "text", "text": "ab"},
        {"type": "text", "text": "cd"},
    ]

    with pytest.raises(ValidationError, match="adjacent text runs"):
        validate_bookgraph(graph)


def test_references_note_edge_target_must_be_note_node() -> None:
    graph = _minimal_graph()
    graph["nodes"].append(
        make_node("n000002", "paragraph", "Not a note.", attrs={}, evidence_ids=["ev000001"])
    )
    graph["edges"].append(make_edge("references_note", "n000001", "n000002"))
    graph["projections"]["reading_order"].append("n000002")

    with pytest.raises(ValidationError, match="references_note target must be note"):
        validate_bookgraph(graph)


def test_resolved_note_ref_target_must_be_note_node() -> None:
    graph = _minimal_graph()
    graph["nodes"].append(
        make_node("n000002", "paragraph", "Not a note.", attrs={}, evidence_ids=["ev000001"])
    )
    graph["nodes"][0]["inline_runs"] = [
        {
            "type": "note_ref",
            "text": "1",
            "attrs": {"marker": "1", "target_note_id": "n000002"},
        }
    ]
    graph["projections"]["reading_order"].append("n000002")

    with pytest.raises(ValidationError, match="note_ref target must be note"):
        validate_bookgraph(graph)


def test_unresolved_note_ref_without_target_passes() -> None:
    graph = _minimal_graph()
    graph["nodes"][0]["inline_runs"] = [
        {
            "type": "note_ref",
            "text": "1",
            "attrs": {"marker": "1", "match_confidence": "unresolved"},
        }
    ]

    validate_bookgraph(graph)
