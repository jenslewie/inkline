from __future__ import annotations

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    make_observation,
    make_observed_document,
    make_observed_page,
    validate_bookgraph,
)
from inkline.canonical.observed_bookgraph import build_bookgraph_from_observed


def _metadata() -> dict:
    return {
        "schema_name": OBSERVED_SCHEMA_NAME,
        "schema_version": OBSERVED_SCHEMA_VERSION,
        "doc_id": "sample",
        "title": "Sample",
        "language": "en",
        "source_file": "sample.pdf",
        "parser_name": "sample_parser",
        "parser_mode": "base",
    }


def _observed_document() -> dict:
    return make_observed_document(
        _metadata(),
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Chapter",
                page=1,
                bbox=[10, 20, 200, 50],
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Body",
                page=1,
                bbox=[10, 70, 200, 120],
                role_hint="body_text",
                attrs={"inline_runs": [{"type": "text", "text": "Body"}]},
                parser_payload={"raw_type": "paragraph"},
            ),
            make_observation(
                "obs000003",
                "footnote_region",
                text="1 Note",
                page=1,
                bbox=[10, 840, 200, 900],
                role_hint="footnote_text",
            ),
            make_observation(
                "obs000004",
                "image_region",
                page=1,
                bbox=[300, 200, 600, 500],
            ),
        ],
    )


def test_build_bookgraph_from_observed_maps_explicit_structure_hints() -> None:
    graph = build_bookgraph_from_observed(_observed_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == [
        "heading",
        "paragraph",
        "footnote",
    ]
    assert graph["nodes"][0]["level"] == 1
    assert graph["nodes"][1]["inline_runs"] == [{"type": "text", "text": "Body"}]
    assert graph["metadata"]["shadow_ignored_observation_counts"] == {"image_region": 1}


def test_build_bookgraph_from_observed_uses_observation_evidence() -> None:
    graph = build_bookgraph_from_observed(_observed_document())

    evidence = graph["evidence"][1]
    assert evidence["source_id"] == "obs000002"
    assert evidence["source_kind"] == "observation"
    assert evidence["parser"] == "sample_parser"
    assert evidence["bbox"] == [10, 70, 200, 120]
    assert evidence["parser_payload"] == {"raw_type": "paragraph"}
    assert "legacy_block_id" not in graph["nodes"][1]["attrs"]


def test_build_bookgraph_from_observed_creates_reading_order_and_rag_units() -> None:
    graph = build_bookgraph_from_observed(_observed_document())

    assert graph["projections"]["reading_order"] == ["n000001", "n000002", "n000003"]
    assert graph["projections"]["epub_flow"] == ["n000001", "n000002", "n000003"]
    assert graph["projections"]["rag_units"] == [
        {
            "unit_id": "ru000001",
            "node_id": "n000002",
            "text": "Body",
            "heading_path": ["Chapter"],
            "parent_node_ids": ["n000001"],
            "source_pages": [1],
            "evidence_ids": ["ev000002"],
        },
        {
            "unit_id": "ru000002",
            "node_id": "n000003",
            "text": "1 Note",
            "heading_path": ["Chapter"],
            "parent_node_ids": ["n000001"],
            "source_pages": [1],
            "evidence_ids": ["ev000003"],
        },
    ]
