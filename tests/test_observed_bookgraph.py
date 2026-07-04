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
                bbox=[10, 70, 900, 120],
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


def _adjacent_body_document() -> dict:
    return make_observed_document(
        _metadata(),
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="First line",
                page=1,
                bbox=[100, 100, 700, 130],
                role_hint="body_text",
                attrs={"reading_order": 1},
                parser_payload={"raw_type": "paragraph"},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Second line",
                page=1,
                bbox=[102, 135, 690, 160],
                role_hint="body_text",
                attrs={"reading_order": 2},
                parser_payload={"raw_type": "paragraph"},
            ),
        ],
    )


def _cross_page_body_document() -> dict:
    return make_observed_document(
        _metadata(),
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Page bottom",
                page=1,
                bbox=[100, 900, 700, 980],
                spans=[{"page": 1, "bbox": [100, 900, 700, 980]}],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Page top",
                page=2,
                bbox=[102, 30, 690, 90],
                spans=[{"page": 2, "bbox": [102, 30, 690, 90]}],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
        ],
    )


def _inset_body_document() -> dict:
    return make_observed_document(
        _metadata(),
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body before",
                page=1,
                bbox=[100, 100, 900, 130],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Inset text",
                page=1,
                bbox=[260, 170, 730, 200],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body after",
                page=1,
                bbox=[100, 240, 900, 270],
                role_hint="body_text",
                attrs={"reading_order": 3},
            ),
        ],
    )


def _image_title_document() -> dict:
    return make_observed_document(
        _metadata(),
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "image_region",
                page=1,
                bbox=[100, 120, 900, 520],
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Image title",
                page=1,
                bbox=[300, 540, 700, 570],
                role_hint="title_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Image description",
                page=1,
                bbox=[300, 575, 700, 620],
                role_hint="body_text",
                attrs={"reading_order": 3},
            ),
        ],
    )


def _front_matter_then_body_document() -> dict:
    return make_observed_document(
        _metadata(),
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Display title",
                page=1,
                bbox=[360, 300, 640, 350],
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Body line one",
                page=2,
                bbox=[100, 100, 900, 130],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body line two",
                page=2,
                bbox=[100, 150, 900, 180],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ],
    )


def _page_footnote_ref_document() -> dict:
    return make_observed_document(
        _metadata(),
        [make_observed_page(12, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body text 1.",
                page=12,
                bbox=[100, 100, 900, 140],
                role_hint="body_text",
                attrs={
                    "reading_order": 1,
                    "inline_runs": [
                        {"type": "text", "text": "Body text "},
                        {"type": "note_ref", "text": "1", "marker": "1"},
                    ],
                },
            ),
            make_observation(
                "obs000002",
                "footnote_region",
                text="1. Page footnote.",
                page=12,
                bbox=[100, 860, 900, 910],
                role_hint="footnote_text",
                attrs={"reading_order": 2},
            ),
        ],
    )


def test_build_bookgraph_from_observed_uses_text_unit_aggregation() -> None:
    graph = build_bookgraph_from_observed(_adjacent_body_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == ["paragraph"]
    assert graph["nodes"][0]["text"] == "First line\nSecond line"
    assert graph["nodes"][0]["attrs"]["source_observation_ids"] == [
        "obs000001",
        "obs000002",
    ]
    assert graph["evidence"][0]["source_id"] == "tu000001"
    assert graph["evidence"][0]["source_kind"] == "text_unit"
    assert graph["evidence"][0]["parser_payload"] == {
        "observation_ids": ["obs000001", "obs000002"],
        "parser_payloads": [{"raw_type": "paragraph"}, {"raw_type": "paragraph"}],
    }


def test_build_bookgraph_from_observed_preserves_cross_page_text_unit_evidence() -> None:
    graph = build_bookgraph_from_observed(_cross_page_body_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == ["paragraph"]
    assert graph["nodes"][0]["text"] == "Page bottom\nPage top"
    assert graph["nodes"][0]["attrs"]["source_observation_ids"] == [
        "obs000001",
        "obs000002",
    ]
    assert graph["nodes"][0]["attrs"]["merge_reasons"] == ["cross_page_boundary_continuation"]
    assert graph["evidence"][0]["pages"] == [1, 2]
    assert graph["evidence"][0]["spans"] == [
        {"page": 1, "bbox": [100, 900, 700, 980]},
        {"page": 2, "bbox": [102, 30, 690, 90]},
    ]


def test_build_bookgraph_from_observed_uses_layout_classification() -> None:
    graph = build_bookgraph_from_observed(_inset_body_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == [
        "paragraph",
        "display_block",
        "paragraph",
    ]
    assert graph["nodes"][1]["attrs"]["layout_role"] == "set_off"
    assert graph["nodes"][1]["attrs"]["layout_classification"]["signals"] == [
        "narrower_than_body_lane",
        "inset_from_body_lane",
    ]


def test_build_bookgraph_from_observed_records_layout_audit_summary() -> None:
    graph = build_bookgraph_from_observed(_inset_body_document())

    assert graph["metadata"]["shadow_text_unit_layout_audit_summary"] == {
        "total_pages": 1,
        "pages_with_profiles": 1,
        "pages_without_profiles": 0,
        "pages_without_profiles_by_reason": {},
        "paragraph_units": 3,
        "classified_display_blocks": 1,
        "skipped_no_bbox": 0,
        "skipped_no_profile": 0,
    }
    assert graph["metadata"]["shadow_text_unit_layout_profile_quality"] == {
        "accepted": 1,
        "filled_from_nearest_profile": 0,
        "rejected_no_stable_profile": 0,
        "rejected_invalid_width": 0,
        "rejected_unstable_widths": 0,
        "rejected_extreme_body_width": 0,
    }
    assert graph["metadata"]["shadow_text_unit_layout_page_coverage"] == {
        "total_pages": 1,
        "pages_with_profiles": 1,
        "pages_without_profiles": [],
        "pages_without_profiles_by_reason": {},
        "mixed_pages": {
            "heading_with_paragraph_units": [],
            "image_with_text_units": [],
            "table_with_text_units": [],
        },
    }
    assert "shadow_text_unit_layout_audit" not in graph["metadata"]


def test_build_bookgraph_from_observed_maps_explicit_structure_hints() -> None:
    graph = build_bookgraph_from_observed(_observed_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == [
        "heading",
        "paragraph",
        "note",
    ]
    assert graph["nodes"][0]["level"] == 1
    assert graph["nodes"][1]["inline_runs"] == [{"type": "text", "text": "Body"}]
    assert graph["metadata"]["shadow_ignored_observation_counts"] == {"image_region": 1}


def test_build_bookgraph_from_observed_resolves_page_footnote_refs() -> None:
    graph = build_bookgraph_from_observed(_page_footnote_ref_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == ["paragraph", "note"]
    assert graph["nodes"][0]["inline_runs"][1]["attrs"]["target_note_id"] == "n000002"
    assert graph["nodes"][1]["attrs"]["source_placement"] == "page_foot"
    assert graph["nodes"][1]["attrs"]["scope"] == "page"
    assert graph["edges"][-1]["edge_type"] == "references_note"
    assert graph["edges"][-1]["source"] == "n000001"
    assert graph["edges"][-1]["target"] == "n000002"
    assert graph["metadata"]["shadow_note_ref_resolution"] == {
        "page_footnote_resolved": 1,
        "page_footnote_ambiguous": 0,
        "page_footnote_unresolved": 0,
    }


def test_build_bookgraph_from_observed_does_not_promote_image_title_to_heading() -> None:
    graph = build_bookgraph_from_observed(_image_title_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == ["paragraph"]
    assert graph["nodes"][0]["attrs"]["layout_role"] == "caption_candidate"
    assert graph["metadata"]["shadow_ignored_observation_counts"] == {"image_region": 1}


def test_build_bookgraph_from_observed_preserves_observation_provenance() -> None:
    graph = build_bookgraph_from_observed(_observed_document())

    evidence = graph["evidence"][1]
    assert evidence["source_id"] == "tu000002"
    assert evidence["source_kind"] == "text_unit"
    assert evidence["parser"] == "sample_parser"
    assert evidence["bbox"] == [10, 70, 900, 120]
    assert evidence["parser_payload"] == {
        "observation_ids": ["obs000002"],
        "parser_payloads": [{"raw_type": "paragraph"}],
    }
    assert graph["nodes"][1]["attrs"]["source_observation_ids"] == ["obs000002"]
    assert "legacy_block_id" not in graph["nodes"][1]["attrs"]


def test_build_bookgraph_from_observed_creates_reading_order_without_downstream_projections() -> None:
    graph = build_bookgraph_from_observed(_observed_document())

    assert graph["projections"]["reading_order"] == ["n000001", "n000002", "n000003"]
    assert "epub_flow" not in graph["projections"]
    assert "rag_units" not in graph["projections"]


def test_build_bookgraph_from_observed_records_page_roles_without_projection_policy() -> None:
    graph = build_bookgraph_from_observed(_front_matter_then_body_document())

    validate_bookgraph(graph)
    assert graph["metadata"]["shadow_page_roles"] == [
        {
            "page": 1,
            "page_role": "title_like_page",
            "signals": ["early_page", "sparse_centered_text", "no_body_profile"],
        },
        {
            "page": 2,
            "page_role": "text_flow_page",
            "signals": ["body_profile"],
        },
    ]
    assert graph["nodes"][0]["attrs"]["page_role"] == "title_like_page"
    assert "flow_scope" not in graph["nodes"][0]["attrs"]
    assert "include_in_epub" not in graph["nodes"][0]["attrs"]
    assert "include_in_rag" not in graph["nodes"][0]["attrs"]
    assert graph["nodes"][1]["attrs"]["page_role"] == "text_flow_page"
    assert "flow_scope" not in graph["nodes"][1]["attrs"]
    assert "include_in_epub" not in graph["nodes"][1]["attrs"]
    assert "include_in_rag" not in graph["nodes"][1]["attrs"]
    assert graph["projections"]["reading_order"] == ["n000001", "n000002"]
    assert "epub_flow" not in graph["projections"]
    assert "rag_units" not in graph["projections"]
