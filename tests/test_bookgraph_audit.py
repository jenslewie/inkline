from __future__ import annotations

from inkline.canonical import (
    BOOKGRAPH_SCHEMA_NAME,
    BOOKGRAPH_SCHEMA_VERSION,
    make_bookgraph,
    make_edge,
    make_evidence,
    make_node,
)
from inkline.canonical.bookgraph_audit import audit_bookgraph


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
        "shadow_ignored_block_counts": {"figure": 1},
    }


def _graph() -> dict:
    return make_bookgraph(
        _metadata(),
        [
            make_node(
                "n000001",
                "heading",
                "Chapter 1",
                level=1,
                attrs={"source_block_id": "b000001"},
                evidence_ids=["ev000001"],
            ),
            make_node(
                "n000002",
                "paragraph",
                "Body1",
                inline_runs=[
                    {"type": "text", "text": "Body"},
                    {"type": "note_ref", "marker": "1", "target_note_id": "b000004"},
                ],
                attrs={"source_block_id": "b000002", "layout_role": "normal_flow"},
                evidence_ids=["ev000002"],
            ),
            make_node(
                "n000003",
                "display_block",
                "Quote",
                attrs={"source_block_id": "b000003", "layout_role": "indented_quote"},
                evidence_ids=["ev000003"],
            ),
            make_node(
                "n000004",
                "footnote",
                "1. Note",
                attrs={"source_block_id": "b000004"},
                evidence_ids=["ev000004"],
            ),
        ],
        [
            make_edge("appears_on_page", "n000001", "page:1", evidence_ids=["ev000001"]),
            make_edge("appears_on_page", "n000002", "page:1", evidence_ids=["ev000002"]),
            make_edge("appears_on_page", "n000003", "page:2", evidence_ids=["ev000003"]),
            make_edge("appears_on_page", "n000004", "page:2", evidence_ids=["ev000004"]),
            make_edge("references_note", "n000002", "n000004", evidence_ids=["ev000002"]),
        ],
        [
            make_evidence("ev000001", "mineru", "b000001", page=1, raw_type="heading"),
            make_evidence("ev000002", "mineru", "b000002", page=1, raw_type="paragraph"),
            make_evidence(
                "ev000003",
                "mineru",
                "b000003",
                page=2,
                bbox=[10, 20, 100, 120],
                raw_type="display_block",
            ),
            make_evidence("ev000004", "mineru", "b000004", page=2, raw_type="footnote"),
        ],
        projections={
            "reading_order": ["n000001", "n000002", "n000003", "n000004"],
            "epub_flow": ["n000001", "n000002", "n000003", "n000004"],
            "rag_units": [{"unit_id": "ru000001", "node_id": "n000002"}],
        },
    )


def test_audit_bookgraph_reports_counts_and_health_signals() -> None:
    audit = audit_bookgraph(_graph())

    assert audit["metadata"]["doc_id"] == "sample"
    assert audit["node_counts"] == {
        "display_block": 1,
        "footnote": 1,
        "heading": 1,
        "paragraph": 1,
    }
    assert audit["edge_counts"] == {"appears_on_page": 4, "references_note": 1}
    assert audit["ignored_block_counts"] == {"figure": 1}
    assert audit["footnotes"]["note_ref_runs"] == 1
    assert audit["footnotes"]["references_note_edges"] == 1
    assert audit["footnotes"]["resolved_note_ref_ratio"] == 1.0
    assert audit["display_blocks"]["pages"] == {"2": 1}
    assert audit["display_blocks"]["source_block_ids"] == ["b000003"]


def test_audit_bookgraph_reports_heading_like_display_candidates() -> None:
    graph = _graph()
    graph["nodes"].append(
        make_node(
            "n000005",
            "display_block",
            "This is a full sentence.",
            attrs={"source_block_id": "b000005", "layout_role": "inline_display_block"},
            evidence_ids=["ev000005"],
        )
    )
    graph["evidence"].append(
        make_evidence(
            "ev000005",
            "mineru",
            "b000005",
            page=3,
            bbox=[10, 520, 700, 560],
            raw_type="display_block",
        )
    )
    graph["nodes"].append(
        make_node(
            "n000006",
            "display_block",
            "Upper page compact title",
            attrs={"source_block_id": "b000006", "layout_role": "standalone_display_page"},
            evidence_ids=["ev000006"],
        )
    )
    graph["evidence"].append(
        make_evidence(
            "ev000006",
            "mineru",
            "b000006",
            page=4,
            bbox=[10, 330, 700, 360],
            raw_type="display_block",
        )
    )
    graph["projections"]["reading_order"].append("n000005")
    graph["projections"]["reading_order"].append("n000006")

    audit = audit_bookgraph(graph)

    assert audit["heading_like_display_blocks"] == [
        {
            "node_id": "n000003",
            "source_block_id": "b000003",
            "text": "Quote",
            "page": 2,
            "bbox": [10, 20, 100, 120],
            "layout_role": "indented_quote",
            "reasons": ["short_text", "top_of_page", "no_sentence_terminal"],
        },
        {
            "node_id": "n000006",
            "source_block_id": "b000006",
            "text": "Upper page compact title",
            "page": 4,
            "bbox": [10, 330, 700, 360],
            "layout_role": "standalone_display_page",
            "reasons": ["short_text", "top_of_page", "no_sentence_terminal"],
        }
    ]


def test_audit_bookgraph_reports_body_like_display_candidates_and_warnings() -> None:
    graph = _graph()
    graph["nodes"].append(
        make_node(
            "n000005",
            "display_block",
            "This display block is long enough to look more like reading-flow body text "
            "than a compact quotation or epigraph.",
            attrs={"source_block_id": "b000005", "layout_role": "inline_display_block"},
            evidence_ids=["ev000005"],
        )
    )
    graph["evidence"].append(
        make_evidence(
            "ev000005",
            "mineru",
            "b000005",
            page=3,
            bbox=[120, 420, 820, 520],
            raw_type="display_block",
        )
    )
    graph["projections"]["reading_order"].append("n000005")

    audit = audit_bookgraph(graph)

    assert audit["body_like_display_blocks"] == [
        {
            "node_id": "n000005",
            "source_block_id": "b000005",
            "text": "This display block is long enough to look more like reading-flow body text "
            "than a compact quotation or epigraph.",
            "page": 3,
            "bbox": [120, 420, 820, 520],
            "layout_role": "inline_display_block",
            "text_length": 112,
            "reasons": ["long_text", "inline_display_block"],
        }
    ]
    assert audit["structure_warnings"] == [
        {
            "warning": "display_blocks_outnumber_paragraphs",
            "display_block_count": 2,
            "paragraph_count": 1,
        }
    ]


def test_audit_bookgraph_compares_projection_to_legacy_supported_blocks() -> None:
    legacy = {
        "blocks": [
            {
                "block_id": "b000001",
                "type": "heading",
                "text": "Chapter 1",
                "level": 1,
                "source": {"page": 1, "pages": [1]},
                "attrs": {},
            },
            {
                "block_id": "b000002",
                "type": "paragraph",
                "text": "Body1",
                "source": {"page": 1, "pages": [1]},
                "attrs": {
                    "inline_runs": [
                        {"type": "text", "text": "Body"},
                        {"type": "note_ref", "marker": "1", "target_note_id": "b000004"},
                    ]
                },
            },
            {
                "block_id": "b000003",
                "type": "display_block",
                "text": "Quote changed",
                "source": {"page": 2, "pages": [2], "bbox": [10, 20, 100, 120]},
                "attrs": {},
            },
            {
                "block_id": "b000010",
                "type": "figure",
                "text": "",
                "source": {"page": 3},
                "attrs": {},
            },
        ]
    }

    diff = audit_bookgraph(_graph(), legacy_canonical=legacy)["projection_diff"]

    assert diff["legacy_supported_block_count"] == 3
    assert diff["projected_block_count"] == 4
    assert diff["missing_block_ids"] == []
    assert diff["extra_block_ids"] == ["b000004"]
    assert diff["changed_blocks"] == [{"block_id": "b000003", "changed_fields": ["text"]}]
    assert diff["exact_supported_fields_match"] is False
