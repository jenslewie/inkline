from __future__ import annotations

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    classify_observed_page_roles,
    make_observation,
    make_observed_document,
    make_observed_page,
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


def test_classify_observed_page_roles_marks_blank_pages_as_non_content() -> None:
    document = make_observed_document(
        _metadata(),
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "page_marker",
                text="1",
                page=1,
                bbox=[480, 950, 520, 980],
                role_hint="page_number",
            )
        ],
    )

    roles = classify_observed_page_roles(document)

    assert roles == [
        {
            "page": 1,
            "page_role": "blank_page",
            "flow_scope": "non_content",
            "include_in_epub": False,
            "include_in_rag": False,
            "signals": ["no_content_observations"],
        }
    ]


def test_classify_observed_page_roles_uses_visual_density_for_cover_material() -> None:
    document = make_observed_document(
        _metadata(),
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
        [
            make_observation(
                "obs000001",
                "image_region",
                page=1,
                bbox=[0, 0, 1000, 980],
            ),
            make_observation(
                "obs000002",
                "image_region",
                page=2,
                bbox=[40, 40, 960, 960],
            ),
        ],
    )

    roles = classify_observed_page_roles(document)

    assert [record["page_role"] for record in roles] == ["cover_page", "cover_spread"]
    assert [record["flow_scope"] for record in roles] == ["front_matter", "front_matter"]
    assert [record["include_in_rag"] for record in roles] == [False, False]
    assert "visual_dominant" in roles[0]["signals"]
    assert "early_page" in roles[1]["signals"]


def test_classify_observed_page_roles_marks_sparse_centered_front_text_as_title_like() -> None:
    document = make_observed_document(
        _metadata(),
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Title",
                page=1,
                bbox=[350, 320, 650, 370],
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Author",
                page=1,
                bbox=[430, 430, 570, 460],
                role_hint="title_text",
            ),
        ],
    )

    roles = classify_observed_page_roles(document)

    assert roles[0]["page_role"] == "title_like_page"
    assert roles[0]["flow_scope"] == "front_matter"
    assert roles[0]["include_in_rag"] is False
    assert roles[0]["signals"] == ["early_page", "sparse_centered_text", "no_body_profile"]


def test_classify_observed_page_roles_keeps_profiled_text_pages_in_body_scope() -> None:
    document = make_observed_document(
        _metadata(),
        [make_observed_page(10, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="First body line",
                page=10,
                bbox=[100, 100, 900, 130],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Second body line",
                page=10,
                bbox=[100, 150, 900, 180],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ],
    )

    roles = classify_observed_page_roles(document)

    assert roles[0]["page_role"] == "body"
    assert roles[0]["flow_scope"] == "body"
    assert roles[0]["include_in_rag"] is True
    assert roles[0]["signals"] == ["body_profile"]


def test_classify_observed_page_roles_keeps_unnumbered_prelude_out_of_rag() -> None:
    document = make_observed_document(
        _metadata(),
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Front matter line one",
                page=1,
                bbox=[100, 100, 900, 130],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Front matter line two",
                page=1,
                bbox=[100, 150, 900, 180],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body line one",
                page=2,
                bbox=[100, 100, 900, 130],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="Body line two",
                page=2,
                bbox=[100, 150, 900, 180],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000005",
                "page_marker",
                text="1",
                page=2,
                bbox=[880, 950, 900, 970],
                role_hint="page_number",
            ),
        ],
    )

    roles = classify_observed_page_roles(document)

    assert roles[0]["page_role"] == "front_matter_page"
    assert roles[0]["flow_scope"] == "front_matter"
    assert roles[0]["include_in_rag"] is False
    assert roles[0]["signals"] == ["unnumbered_prelude", "text_content", "body_profile"]
    assert roles[1]["page_role"] == "body"
    assert roles[1]["include_in_rag"] is True
