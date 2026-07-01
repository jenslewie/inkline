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
        attrs={"source_block_id": "b000001"},
        evidence_ids=["ev000001"],
    )
    evidence = make_evidence(
        "ev000001",
        "mineru",
        "b000001",
        page=1,
        bbox=[10, 20, 100, 120],
        raw_type="paragraph",
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
