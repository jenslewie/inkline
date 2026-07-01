from __future__ import annotations

from inkline.canonical import (
    BOOKGRAPH_SCHEMA_NAME,
    BOOKGRAPH_SCHEMA_VERSION,
    make_bookgraph,
    make_evidence,
    make_node,
)
from inkline.canonical.bookgraph_projection import bookgraph_to_blocks


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


def test_paragraph_node_projects_to_v1_like_block() -> None:
    graph = make_bookgraph(
        _metadata(),
        [
            make_node(
                "n000001",
                "paragraph",
                "Body text",
                attrs={"source_block_id": "b000010", "logical_role": "body"},
                evidence_ids=["ev000001"],
            )
        ],
        [],
        [make_evidence("ev000001", "mineru", "b000010", page=3, raw_type="paragraph")],
        projections={"reading_order": ["n000001"], "epub_flow": ["n000001"], "rag_units": []},
    )

    assert bookgraph_to_blocks(graph) == [
        {
            "block_id": "b000010",
            "type": "paragraph",
            "text": "Body text",
            "attrs": {"logical_role": "body"},
            "source": {"page": 3, "pages": [3]},
        }
    ]


def test_heading_preserves_level_and_reading_order_controls_output() -> None:
    graph = make_bookgraph(
        _metadata(),
        [
            make_node("n000001", "paragraph", "Second", evidence_ids=["ev000001"]),
            make_node("n000002", "heading", "First", level=2, evidence_ids=["ev000002"]),
        ],
        [],
        [
            make_evidence("ev000001", "mineru", "b2", page=2),
            make_evidence("ev000002", "mineru", "b1", page=1),
        ],
        projections={"reading_order": ["n000002", "n000001"], "epub_flow": [], "rag_units": []},
    )

    blocks = bookgraph_to_blocks(graph)

    assert [block["text"] for block in blocks] == ["First", "Second"]
    assert blocks[0]["level"] == 2


def test_inline_runs_return_to_attrs_and_source_restores_evidence_fields() -> None:
    inline_runs = [
        {"type": "text", "text": "Body"},
        {"type": "note_ref", "marker": "1", "target_note_id": "b000099"},
    ]
    spans = [{"page": 4, "bbox": [1, 2, 3, 4], "block_id": "raw:4:1"}]
    graph = make_bookgraph(
        _metadata(),
        [
            make_node(
                "n000001",
                "paragraph",
                "Body1",
                inline_runs=inline_runs,
                attrs={"source_block_id": "b000001", "layout_role": "normal_flow"},
                evidence_ids=["ev000001"],
            )
        ],
        [],
        [
            make_evidence(
                "ev000001",
                "mineru",
                "b000001",
                page=4,
                pages=[4, 5],
                bbox=[10, 20, 300, 400],
                spans=spans,
                raw_type="paragraph",
            )
        ],
        projections={"reading_order": ["n000001"], "epub_flow": [], "rag_units": []},
    )

    block = bookgraph_to_blocks(graph)[0]

    assert block["attrs"]["inline_runs"] == inline_runs
    assert block["attrs"]["layout_role"] == "normal_flow"
    assert block["source"] == {
        "page": 4,
        "bbox": [10, 20, 300, 400],
        "pages": [4, 5],
        "spans": spans,
    }
