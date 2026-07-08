from __future__ import annotations

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    make_observation,
    make_observed_document,
    make_observed_page,
    validate_internal_canonical,
)
from inkline.canonical.bookgraph.from_observed import (
    build_bookgraph_from_observed,
    build_internal_canonical_from_observed,
)

INTERNAL_ONLY_NODE_ATTRS = {
    "source_text_unit_id",
    "source_logical_unit_id",
    "source_observation_ids",
    "role_hints",
    "layout_classification",
    "merge_reasons",
    "page_role",
    "page_role_signals",
    "source_text_unit_ids",
    "logical_split_reason",
}


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
                parser_payload={"raw_type": "paragraph"},
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


def test_internal_canonical_contains_exact_public_projection() -> None:
    document = _observed_document()
    public = build_bookgraph_from_observed(document)
    internal = build_internal_canonical_from_observed(document)

    validate_internal_canonical(internal)
    assert internal["public_projection"] == public


def test_internal_canonical_groups_public_and_debug_by_node() -> None:
    internal = build_internal_canonical_from_observed(_adjacent_body_document())

    first_node = internal["nodes"][0]
    assert first_node["public"]["node_id"] == "n000001"
    assert first_node["public"]["text"] == "First line"
    assert first_node["debug"]["attrs"]["source_observation_ids"] == ["obs000001"]
    assert first_node["debug"]["attrs"]["source_text_unit_id"] == "tu000001"
    assert first_node["debug"]["attrs"]["source_logical_unit_id"] == "lu000001"
    assert internal["pipeline"]["text_units"][0]["text"] == "First line\nSecond line"


def test_public_projection_excludes_internal_only_fields() -> None:
    public = build_bookgraph_from_observed(_adjacent_body_document())

    assert all(
        not (INTERNAL_ONLY_NODE_ATTRS & set(node["attrs"]))
        for node in public["nodes"]
    )
    assert all("parser_payload" not in evidence for evidence in public["evidence"])
    assert all(not key.startswith("shadow_") for key in public["metadata"])
