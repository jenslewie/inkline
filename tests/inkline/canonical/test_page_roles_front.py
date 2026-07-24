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


def _layout_audit_with_body_profiles(pages: list[int]) -> dict:
    return {"page_layout_profiles": [{"page": page, "profile_scope": "page"} for page in pages]}


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
    assert roles[0]["signals"] == ["early_page", "sparse_centered_text", "no_body_profile"]


def test_classify_observed_page_roles_marks_profiled_unnumbered_sparse_text_as_front_visual() -> (
    None
):
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
                text="Decorative half title",
                page=1,
                bbox=[430, 320, 570, 350],
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Decorative subtitle",
                page=1,
                bbox=[430, 390, 570, 415],
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body starts",
                page=2,
                bbox=[120, 120, 880, 150],
                role_hint="body_text",
            ),
            make_observation(
                "obs000004",
                "page_marker",
                text="1",
                page=2,
                bbox=[880, 950, 900, 970],
                role_hint="page_number",
            ),
        ],
    )

    roles = classify_observed_page_roles(
        document, layout_audit=_layout_audit_with_body_profiles([1, 2])
    )

    assert roles[0]["page_role"] == "front_visual_page"
    assert roles[0]["signals"] == [
        "unnumbered_prelude",
        "sparse_centered_front_text",
        "body_profile",
    ]


def test_classify_observed_page_roles_marks_profiled_sparse_front_leaf_without_title_hint() -> None:
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
                text="For Hana",
                page=1,
                bbox=[450, 340, 550, 365],
                role_hint="body_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="(1934-2004)",
                page=1,
                bbox=[430, 375, 570, 400],
                role_hint="body_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body starts",
                page=2,
                bbox=[120, 120, 880, 150],
                role_hint="body_text",
            ),
            make_observation(
                "obs000004",
                "page_marker",
                text="1",
                page=2,
                bbox=[880, 950, 900, 970],
                role_hint="page_number",
            ),
        ],
    )

    roles = classify_observed_page_roles(
        document, layout_audit=_layout_audit_with_body_profiles([1, 2])
    )

    assert roles[0]["page_role"] == "front_visual_page"
    assert roles[0]["signals"] == [
        "unnumbered_prelude",
        "sparse_centered_front_text",
        "body_profile",
    ]


def test_classify_observed_page_roles_marks_vertical_front_text_layout_as_visual() -> None:
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
                text="Vertical title",
                page=1,
                bbox=[420, 60, 540, 820],
                role_hint="body_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Vertical author",
                page=1,
                bbox=[620, 180, 690, 700],
                role_hint="body_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body starts",
                page=2,
                bbox=[120, 120, 880, 150],
                role_hint="body_text",
            ),
            make_observation(
                "obs000004",
                "page_marker",
                text="1",
                page=2,
                bbox=[880, 950, 900, 970],
                role_hint="page_number",
            ),
        ],
    )

    roles = classify_observed_page_roles(
        document, layout_audit=_layout_audit_with_body_profiles([1, 2])
    )

    assert roles[0]["page_role"] == "front_visual_page"
    assert roles[0]["signals"] == ["unnumbered_prelude", "vertical_text_layout", "body_profile"]


def test_classify_observed_page_roles_marks_dense_centered_front_layout_as_visual() -> None:
    observations = [
        make_observation(
            f"obs{index:06d}",
            "text_region",
            text=f"Publication line {index}",
            page=1,
            bbox=[350, 60 + index * 80, 650, 120 + index * 80],
            role_hint="body_text",
        )
        for index in range(1, 9)
    ]
    observations.extend(
        [
            make_observation(
                "obs000009",
                "text_region",
                text="Body starts",
                page=2,
                bbox=[120, 120, 880, 150],
                role_hint="body_text",
            ),
            make_observation(
                "obs000010",
                "page_marker",
                text="1",
                page=2,
                bbox=[880, 950, 900, 970],
                role_hint="page_number",
            ),
        ]
    )
    document = make_observed_document(
        _metadata(),
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
        observations,
    )

    roles = classify_observed_page_roles(
        document, layout_audit=_layout_audit_with_body_profiles([1, 2])
    )

    assert roles[0]["page_role"] == "front_visual_page"
    assert roles[0]["signals"] == [
        "unnumbered_prelude",
        "dense_centered_nonflow_layout",
        "body_profile",
    ]
