from __future__ import annotations

from inkline.canonical.bookgraph.projection import bookgraph_to_blocks
from inkline.parsers.mineru.normalize.bookgraph_shadow import build_bookgraph_shadow


def _canonical() -> dict:
    return {
        "metadata": {
            "schema_version": "1.0",
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        "blocks": [
            {
                "block_id": "b000001",
                "type": "heading",
                "text": "Chapter 1",
                "level": 1,
                "source": {"page": 1, "bbox": [10, 10, 200, 40]},
                "attrs": {},
            },
            {
                "block_id": "b000002",
                "type": "paragraph",
                "text": "Body text1",
                "source": {
                    "page": 1,
                    "bbox": [10, 50, 200, 90],
                    "spans": [{"page": 1, "bbox": [10, 50, 200, 90], "block_id": "raw:1:1"}],
                },
                "attrs": {
                    "inline_runs": [
                        {"type": "text", "text": "Body text"},
                        {"type": "note_ref", "marker": "1", "target_note_id": "b000005"},
                    ]
                },
            },
            {
                "block_id": "b000003",
                "type": "display_block",
                "text": "Quoted text",
                "source": {"page": 1, "bbox": [30, 100, 180, 130]},
                "attrs": {"layout_context": "set_off"},
            },
            {
                "block_id": "b000004",
                "type": "figure",
                "text": "",
                "source": {"page": 1},
                "attrs": {},
            },
            {
                "block_id": "b000005",
                "type": "footnote",
                "text": "1. Footnote",
                "source": {"page": 2, "pages": [2], "bbox": [10, 800, 200, 840]},
                "attrs": {},
            },
        ],
        "toc": [],
        "assets": {"images": [{"image_id": "img1"}]},
        "source_map": [],
    }


def test_build_bookgraph_shadow_converts_supported_text_blocks() -> None:
    graph = build_bookgraph_shadow(_canonical())

    assert [node["node_type"] for node in graph["nodes"]] == [
        "heading",
        "paragraph",
        "display_block",
        "footnote",
    ]
    assert [node["attrs"]["legacy_block_id"] for node in graph["nodes"]] == [
        "b000001",
        "b000002",
        "b000003",
        "b000005",
    ]
    assert graph["metadata"]["shadow_ignored_block_counts"] == {"figure": 1}


def test_build_bookgraph_shadow_preserves_source_and_inline_runs() -> None:
    graph = build_bookgraph_shadow(_canonical())
    paragraph = graph["nodes"][1]
    evidence = graph["evidence"][1]

    assert paragraph["inline_runs"] == [
        {"type": "text", "text": "Body text"},
        {"type": "note_ref", "marker": "1", "target_note_id": "b000005"},
    ]
    assert evidence["page"] == 1
    assert evidence["pages"] == [1]
    assert evidence["bbox"] == [10, 50, 200, 90]
    assert evidence["spans"] == [{"page": 1, "bbox": [10, 50, 200, 90], "block_id": "raw:1:1"}]
    assert evidence["source_kind"] == "legacy_block"
    assert evidence["parser_payload"] == {"legacy_type": "paragraph"}
    assert "raw_type" not in evidence


def test_build_bookgraph_shadow_generates_note_reference_and_page_edges() -> None:
    graph = build_bookgraph_shadow(_canonical())

    references = [edge for edge in graph["edges"] if edge["edge_type"] == "references_note"]
    appears = [edge for edge in graph["edges"] if edge["edge_type"] == "appears_on_page"]

    assert references == [
        {
            "edge_type": "references_note",
            "source": "n000002",
            "target": "n000004",
            "evidence_ids": ["ev000002"],
            "attrs": {"target_note_id": "b000005"},
        }
    ]
    assert len(appears) == 4
    assert {edge["target"] for edge in appears} == {"page:1", "page:2"}


def test_build_bookgraph_shadow_resolves_note_ref_to_footnote_note_id_alias() -> None:
    canonical = _canonical()
    canonical["blocks"][1]["attrs"]["inline_runs"][1]["target_note_id"] = "note_b000005"
    canonical["blocks"][4]["attrs"]["note_id"] = "note_b000005"

    graph = build_bookgraph_shadow(canonical)

    references = [edge for edge in graph["edges"] if edge["edge_type"] == "references_note"]
    assert references == [
        {
            "edge_type": "references_note",
            "source": "n000002",
            "target": "n000004",
            "evidence_ids": ["ev000002"],
            "attrs": {"target_note_id": "note_b000005"},
        }
    ]


def test_build_bookgraph_shadow_resolves_note_ref_to_note_prefixed_block_id() -> None:
    canonical = _canonical()
    canonical["blocks"][1]["attrs"]["inline_runs"][1]["target_note_id"] = "note_b000005"

    graph = build_bookgraph_shadow(canonical)

    references = [edge for edge in graph["edges"] if edge["edge_type"] == "references_note"]
    assert references == [
        {
            "edge_type": "references_note",
            "source": "n000002",
            "target": "n000004",
            "evidence_ids": ["ev000002"],
            "attrs": {"target_note_id": "note_b000005"},
        }
    ]


def test_build_bookgraph_shadow_creates_heading_path_aware_rag_units() -> None:
    graph = build_bookgraph_shadow(_canonical())

    assert [unit["node_id"] for unit in graph["projections"]["rag_units"]] == [
        "n000002",
        "n000003",
        "n000004",
    ]
    assert all(unit["heading_path"] == ["Chapter 1"] for unit in graph["projections"]["rag_units"])
    assert all(
        unit["parent_node_ids"] == ["n000001"] for unit in graph["projections"]["rag_units"]
    )


def test_projection_round_trips_supported_block_fields() -> None:
    canonical = _canonical()
    graph = build_bookgraph_shadow(canonical)

    projected = bookgraph_to_blocks(graph)
    supported = [block for block in canonical["blocks"] if block["type"] != "figure"]

    assert [
        (block["block_id"], block["type"], block["text"], block.get("level"))
        for block in projected
    ] == [
        (block["block_id"], block["type"], block["text"], block.get("level"))
        for block in supported
    ]
    assert projected[1]["attrs"]["inline_runs"] == supported[1]["attrs"]["inline_runs"]
    assert projected[1]["source"]["spans"] == supported[1]["source"]["spans"]
