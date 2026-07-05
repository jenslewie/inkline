from __future__ import annotations

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    make_observation,
    make_observed_document,
    make_observed_page,
    validate_bookgraph,
)
from inkline.canonical.observed_bookgraph import (
    build_bookgraph_from_observed,
    build_internal_canonical_from_observed,
)


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


def _cross_visual_insert_body_document() -> dict:
    return make_observed_document(
        _metadata(),
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
            make_observed_page(3, width=1000, height=1000),
        ],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body before",
                page=1,
                bbox=[100, 100, 700, 130],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Paragraph tail",
                page=1,
                bbox=[100, 900, 700, 980],
                spans=[{"page": 1, "bbox": [100, 900, 700, 980]}],
                role_hint="body_text",
                attrs={
                    "reading_order": 2,
                    "inline_runs": [
                        {"type": "text", "text": "Paragraph "},
                        {"type": "note_ref", "text": "1", "marker": "1"},
                        {"type": "text", "text": "tail"},
                    ],
                },
            ),
            make_observation(
                "obs000003",
                "image_region",
                page=2,
                bbox=[100, 100, 900, 900],
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="Paragraph head",
                page=3,
                bbox=[102, 30, 690, 90],
                spans=[{"page": 3, "bbox": [102, 30, 690, 90]}],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="Body after",
                page=3,
                bbox=[102, 180, 690, 220],
                role_hint="body_text",
                attrs={"reading_order": 2},
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


def _explicit_note_section_document() -> dict:
    return make_observed_document(
        _metadata(),
        [
            make_observed_page(10, width=1000, height=1000),
            make_observed_page(90, width=1000, height=1000),
        ],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="正文第一章",
                page=10,
                bbox=[100, 100, 500, 140],
                role_hint="title_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Body text 1.",
                page=10,
                bbox=[100, 180, 900, 220],
                role_hint="body_text",
                attrs={
                    "reading_order": 2,
                    "inline_runs": [
                        {"type": "text", "text": "Body text "},
                        {"type": "note_ref", "text": "1", "marker": "1"},
                    ],
                },
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="注释",
                page=90,
                bbox=[420, 100, 580, 140],
                role_hint="title_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="正文第一章",
                page=90,
                bbox=[100, 180, 500, 220],
                role_hint="title_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="1. A chapter note.",
                page=90,
                bbox=[100, 250, 900, 300],
                role_hint="reference_text",
                attrs={"reading_order": 3},
            ),
        ],
    )


def test_build_bookgraph_from_observed_uses_text_unit_aggregation() -> None:
    graph = build_bookgraph_from_observed(_adjacent_body_document())
    internal = build_internal_canonical_from_observed(_adjacent_body_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == ["paragraph", "paragraph"]
    assert [node["text"] for node in graph["nodes"]] == ["First line", "Second line"]
    assert internal["pipeline"]["text_units"][0]["text"] == "First line\nSecond line"
    assert internal["nodes"][0]["debug"]["attrs"]["source_observation_ids"] == ["obs000001"]
    assert internal["pipeline"]["text_units"][0]["observation_ids"] == [
        "obs000001",
        "obs000002",
    ]
    assert "parser_payload" not in graph["evidence"][0]


def test_build_bookgraph_from_observed_preserves_cross_page_text_unit_evidence() -> None:
    graph = build_bookgraph_from_observed(_cross_page_body_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == ["paragraph"]
    assert graph["nodes"][0]["text"] == "Page bottomPage top"
    internal = build_internal_canonical_from_observed(_cross_page_body_document())
    assert internal["nodes"][0]["debug"]["attrs"]["source_observation_ids"] == [
        "obs000001",
        "obs000002",
    ]
    assert internal["nodes"][0]["debug"]["attrs"]["merge_reasons"] == [
        "cross_page_boundary_continuation"
    ]
    assert graph["evidence"][0]["pages"] == [1, 2]
    assert graph["evidence"][0]["spans"] == [
        {"page": 1, "bbox": [100, 900, 700, 980]},
        {"page": 2, "bbox": [102, 30, 690, 90]},
    ]


def test_build_bookgraph_from_observed_bridges_paragraph_over_visual_insert() -> None:
    document = _cross_visual_insert_body_document()
    graph = build_bookgraph_from_observed(document)

    validate_bookgraph(graph)
    assert [node["text"] for node in graph["nodes"]] == [
        "Body before",
        "Paragraph tailParagraph head",
        "Body after",
    ]
    assert graph["nodes"][1]["inline_runs"] == [
        {"type": "text", "text": "Paragraph "},
        {"type": "note_ref", "text": "1", "marker": "1"},
        {"type": "text", "text": "tailParagraph head"},
    ]
    assert graph["evidence"][1]["pages"] == [1, 3]
    assert graph["evidence"][1]["spans"] == [
        {"page": 1, "bbox": [100, 900, 700, 980]},
        {"page": 3, "bbox": [102, 30, 690, 90]},
    ]

    internal = build_internal_canonical_from_observed(document)

    assert internal["nodes"][1]["debug"]["attrs"]["merge_reasons"] == [
        "cross_nontext_page_boundary_continuation"
    ]
    assert internal["pipeline"]["page_roles"][1]["page_role"] == "visual_page"
    assert "merge_reasons" not in graph["nodes"][1]["attrs"]


def test_build_bookgraph_from_observed_does_not_bridge_multiline_visual_insert_endpoint() -> None:
    document = _cross_visual_insert_body_document()
    document["observations"][3]["text"] = "Paragraph\nhead"

    graph = build_bookgraph_from_observed(document)

    validate_bookgraph(graph)
    assert [node["text"] for node in graph["nodes"]] == [
        "Body before",
        "Paragraph tail",
        "Paragraph\nhead",
        "Body after",
    ]


def test_build_bookgraph_from_observed_does_not_bridge_indented_visual_insert_endpoint() -> None:
    document = _cross_visual_insert_body_document()
    document["observations"][3]["attrs"]["text_line_metrics"] = {
        "line_count": 3,
        "first_line_indent": 18,
        "char_width": 10,
    }

    graph = build_bookgraph_from_observed(document)

    validate_bookgraph(graph)
    assert [node["text"] for node in graph["nodes"]] == [
        "Body before",
        "Paragraph tail",
        "Paragraph head",
        "Body after",
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
    internal = build_internal_canonical_from_observed(_inset_body_document())
    assert internal["nodes"][1]["debug"]["attrs"]["layout_classification"]["signals"] == [
        "narrower_than_body_lane",
        "inset_from_body_lane",
    ]


def test_build_bookgraph_from_observed_records_layout_audit_summary() -> None:
    internal = build_internal_canonical_from_observed(_inset_body_document())

    assert internal["pipeline"]["layout_audit"]["summary"] == {
        "total_pages": 1,
        "pages_with_profiles": 1,
        "pages_without_profiles": 0,
        "pages_without_profiles_by_reason": {},
        "paragraph_units": 3,
        "classified_display_blocks": 1,
        "skipped_no_bbox": 0,
        "skipped_no_profile": 0,
    }
    assert internal["pipeline"]["layout_audit"]["profile_quality"] == {
        "accepted": 1,
        "filled_from_nearest_profile": 0,
        "rejected_no_stable_profile": 0,
        "rejected_invalid_width": 0,
        "rejected_unstable_widths": 0,
        "rejected_extreme_body_width": 0,
    }
    assert internal["pipeline"]["layout_audit"]["page_coverage"] == {
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
    assert "shadow_text_unit_layout_audit" not in internal["public_projection"]["metadata"]


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
    internal = build_internal_canonical_from_observed(_observed_document())
    assert internal["pipeline"]["ignored_observation_counts"] == {"image_region": 1}


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
    internal = build_internal_canonical_from_observed(_page_footnote_ref_document())
    assert internal["pipeline"]["bookgraph_debug_metadata"]["shadow_note_ref_resolution"] == {
        "page_footnote_resolved": 1,
        "page_footnote_ambiguous": 0,
        "page_footnote_unresolved": 0,
    }


def test_build_bookgraph_from_observed_resolves_explicit_note_section_refs() -> None:
    graph = build_bookgraph_from_observed(_explicit_note_section_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == [
        "heading",
        "paragraph",
        "heading",
        "heading",
        "note",
    ]
    note = graph["nodes"][4]
    assert note["attrs"]["source_placement"] == "book_end"
    assert note["attrs"]["scope"] == "chapter"
    assert graph["nodes"][1]["inline_runs"][1]["attrs"]["target_note_id"] == "n000005"
    internal = build_internal_canonical_from_observed(_explicit_note_section_document())
    assert internal["pipeline"]["bookgraph_debug_metadata"][
        "shadow_scoped_note_ref_resolution"
    ] == {
        "scoped_note_resolved": 1,
        "scoped_note_ambiguous": 0,
        "scoped_note_unresolved": 0,
    }


def test_build_bookgraph_from_observed_promotes_bottom_reference_text_to_page_foot_note() -> None:
    document = make_observed_document(
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
                    "inline_runs": [{"type": "note_ref", "text": "1", "marker": "1"}],
                },
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="1. Bottom reference note.",
                page=12,
                bbox=[100, 720, 900, 760],
                role_hint="reference_text",
                attrs={"reading_order": 2},
            ),
        ],
    )

    graph = build_bookgraph_from_observed(document)

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == ["paragraph", "note"]
    assert graph["nodes"][1]["attrs"]["source_placement"] == "page_foot"
    assert graph["nodes"][0]["inline_runs"][0]["attrs"]["target_note_id"] == "n000002"


def test_build_bookgraph_from_observed_does_not_promote_image_title_to_heading() -> None:
    graph = build_bookgraph_from_observed(_image_title_document())

    validate_bookgraph(graph)
    assert [node["node_type"] for node in graph["nodes"]] == ["paragraph"]
    assert graph["nodes"][0]["attrs"]["layout_role"] == "caption_candidate"
    internal = build_internal_canonical_from_observed(_image_title_document())
    assert internal["pipeline"]["ignored_observation_counts"] == {"image_region": 1}


def test_build_bookgraph_from_observed_preserves_observation_provenance() -> None:
    graph = build_bookgraph_from_observed(_observed_document())
    internal = build_internal_canonical_from_observed(_observed_document())

    evidence = graph["evidence"][1]
    assert evidence["source_id"] == "ev000002"
    assert evidence["source_kind"] == "source_span_set"
    assert evidence["parser"] == "sample_parser"
    assert evidence["bbox"] == [10, 70, 900, 120]
    assert "parser_payload" not in evidence
    assert internal["evidence"][1]["debug"]["parser_payload"] == {
        "observation_ids": ["obs000002"],
        "parser_payloads": [{"raw_type": "paragraph"}],
    }
    assert internal["nodes"][1]["debug"]["attrs"]["source_observation_ids"] == ["obs000002"]
    assert "legacy_block_id" not in graph["nodes"][1]["attrs"]


def test_build_bookgraph_from_observed_creates_reading_order_without_downstream_projections() -> (
    None
):
    graph = build_bookgraph_from_observed(_observed_document())

    assert graph["projections"]["reading_order"] == ["n000001", "n000002", "n000003"]
    assert "epub_flow" not in graph["projections"]
    assert "rag_units" not in graph["projections"]


def test_build_bookgraph_from_observed_records_page_roles_without_projection_policy() -> None:
    graph = build_bookgraph_from_observed(_front_matter_then_body_document())
    internal = build_internal_canonical_from_observed(_front_matter_then_body_document())

    validate_bookgraph(graph)
    assert internal["pipeline"]["page_roles"] == [
        {
            "page": 1,
            "page_role": "title_like_page",
            "flow_scope": "front_matter",
            "signals": ["early_page", "sparse_centered_text", "no_body_profile"],
        },
        {
            "page": 2,
            "page_role": "text_flow_page",
            "flow_scope": "body",
            "signals": ["body_profile"],
        },
    ]
    assert "page_role" not in graph["nodes"][0]["attrs"]
    assert "flow_scope" not in graph["nodes"][0]["attrs"]
    assert "include_in_epub" not in graph["nodes"][0]["attrs"]
    assert "include_in_rag" not in graph["nodes"][0]["attrs"]
    assert "page_role" not in graph["nodes"][1]["attrs"]
    assert "flow_scope" not in graph["nodes"][1]["attrs"]
    assert "include_in_epub" not in graph["nodes"][1]["attrs"]
    assert "include_in_rag" not in graph["nodes"][1]["attrs"]
    assert graph["projections"]["reading_order"] == ["n000001", "n000002", "n000003"]
    assert "epub_flow" not in graph["projections"]
    assert "rag_units" not in graph["projections"]
