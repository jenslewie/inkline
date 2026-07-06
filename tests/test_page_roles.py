from __future__ import annotations

from pathlib import Path

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    classify_observed_page_roles,
    make_observation,
    make_observed_document,
    make_observed_page,
)

PAGE_ROLE_VALUES = {
    "back_cover_candidate",
    "bibliographic_like_page",
    "blank_page",
    "cover_page",
    "front_matter_page",
    "front_visual_page",
    "note_section_candidate",
    "text_flow_candidate",
    "text_flow_page",
    "title_like_page",
    "toc_page",
    "unknown",
    "visual_page",
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


def _layout_audit_with_body_profiles(pages: list[int]) -> dict:
    return {
        "page_layout_profiles": [
            {"page": page, "profile_scope": "page", "profile_source": "local"} for page in pages
        ]
    }


def test_canonical_v2_doc_defines_all_phase3_page_roles() -> None:
    doc = Path("docs/canonical-v2-bookgraph.md").read_text(encoding="utf-8")

    missing = sorted(role for role in PAGE_ROLE_VALUES if f"`{role}`" not in doc)

    assert missing == []


def test_classify_observed_page_roles_marks_early_blank_pages_as_front_matter() -> None:
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
            "flow_scope": "front_matter",
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

    assert [record["page_role"] for record in roles] == ["cover_page", "front_visual_page"]
    assert [record["flow_scope"] for record in roles] == ["front_matter", "front_matter"]
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
    assert roles[0]["signals"] == ["early_page", "sparse_centered_text", "no_body_profile"]


def test_classify_observed_page_roles_marks_unnumbered_decorative_title_as_front_visual() -> None:
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
                bbox=[350, 320, 650, 370],
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Decorative subtitle",
                page=1,
                bbox=[360, 430, 640, 460],
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
    layout_audit = _layout_audit_with_body_profiles([2])

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert roles[0]["page_role"] == "front_visual_page"
    assert roles[0]["signals"] == [
        "unnumbered_prelude",
        "decorative_title_like",
        "no_body_profile",
    ]


def test_classify_observed_page_roles_keeps_profiled_text_pages_in_text_flow() -> None:
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

    assert roles[0]["page_role"] == "text_flow_page"
    assert roles[0]["flow_scope"] == "body"
    assert roles[0]["signals"] == ["body_profile"]


def test_classify_observed_page_roles_keeps_sparse_visual_caption_page_as_text_flow() -> None:
    document = make_observed_document(
        _metadata(),
        [make_observed_page(page, width=1000, height=1000) for page in range(1, 101)],
        [
            make_observation(
                "obs000001",
                "image_region",
                text="",
                page=50,
                bbox=[120, 120, 880, 580],
                role_hint="unknown",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Figure caption",
                page=50,
                bbox=[160, 650, 840, 690],
                role_hint="body_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="More caption",
                page=50,
                bbox=[160, 710, 840, 750],
                role_hint="body_text",
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="Short caption tail",
                page=50,
                bbox=[160, 770, 840, 810],
                role_hint="body_text",
            ),
        ],
    )
    layout_audit = _layout_audit_with_body_profiles([50])

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)
    role_by_page = {record["page"]: record for record in roles}

    assert role_by_page[50]["page_role"] == "text_flow_page"
    assert role_by_page[50]["flow_scope"] == "body"
    assert role_by_page[50]["signals"] == [
        "body_profile",
        "visual_verifier_candidate",
    ]


def test_classify_observed_page_roles_marks_large_visual_with_one_caption_as_visual() -> None:
    document = make_observed_document(
        _metadata(),
        [make_observed_page(page, width=1000, height=1000) for page in range(1, 101)],
        [
            make_observation(
                "obs000001",
                "image_region",
                text="",
                page=50,
                bbox=[80, 80, 920, 820],
                role_hint="unknown",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Large caption",
                page=50,
                bbox=[140, 680, 860, 960],
                role_hint="body_text",
            ),
        ],
    )
    layout_audit = _layout_audit_with_body_profiles([50])

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)
    role_by_page = {record["page"]: record for record in roles}

    assert role_by_page[50]["page_role"] == "visual_page"
    assert role_by_page[50]["flow_scope"] == "body"


def test_classify_observed_page_roles_keeps_visual_body_mixed_page_in_body() -> None:
    document = make_observed_document(
        _metadata(),
        [make_observed_page(50, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "image_region",
                text="",
                page=50,
                bbox=[120, 120, 880, 360],
                role_hint="unknown",
            ),
            *[
                make_observation(
                    f"obs00000{offset + 2}",
                    "text_region",
                    text=f"Body line {offset}",
                    page=50,
                    bbox=[120, 400 + offset * 48, 880, 430 + offset * 48],
                    role_hint="body_text",
                )
                for offset in range(8)
            ],
        ],
    )
    layout_audit = _layout_audit_with_body_profiles([50])

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert roles[0]["page_role"] == "text_flow_page"
    assert roles[0]["flow_scope"] == "body"


def test_classify_observed_page_roles_marks_mid_book_sparse_centered_text_as_title_like() -> None:
    document = make_observed_document(
        _metadata(),
        [make_observed_page(page, width=1000, height=1000) for page in range(1, 321)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Part title",
                page=308,
                bbox=[350, 360, 650, 405],
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Subtitle",
                page=308,
                bbox=[390, 450, 610, 490],
                role_hint="title_text",
            ),
        ],
    )
    layout_audit = _layout_audit_with_body_profiles([])

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)
    role_by_page = {record["page"]: record for record in roles}

    assert role_by_page[308]["page_role"] == "title_like_page"
    assert role_by_page[308]["flow_scope"] == "body"
    assert role_by_page[308]["signals"] == ["sparse_centered_text", "no_body_profile"]


def test_classify_observed_page_roles_keeps_sparse_centered_body_text_as_text_flow_candidate() -> (
    None
):
    document = make_observed_document(
        _metadata(),
        [make_observed_page(page, width=1000, height=1000) for page in range(1, 321)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Short carried-over body line",
                page=208,
                bbox=[350, 420, 650, 470],
                role_hint="body_text",
            ),
        ],
    )
    layout_audit = _layout_audit_with_body_profiles([])

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)
    role_by_page = {record["page"]: record for record in roles}

    assert role_by_page[208]["page_role"] == "text_flow_candidate"
    assert role_by_page[208]["flow_scope"] == "body"


def test_classify_observed_page_roles_marks_unnumbered_prelude_as_front_matter() -> None:
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
    assert roles[0]["signals"] == ["unnumbered_prelude", "text_content", "body_profile"]
    assert roles[1]["page_role"] == "text_flow_page"


def test_classify_observed_page_roles_keeps_preface_and_toc_prefix_out_of_body_scope() -> None:
    pages = [make_observed_page(page, width=1000, height=1000) for page in range(1, 9)]
    observations = [
        make_observation(
            "obs000001",
            "text_region",
            text="Cover title",
            page=1,
            bbox=[250, 200, 750, 260],
            role_hint="title_text",
        ),
        make_observation(
            "obs000002",
            "text_region",
            text="Preface",
            page=2,
            bbox=[120, 100, 880, 130],
            role_hint="title_text",
        ),
        make_observation(
            "obs000003",
            "text_region",
            text="Preface body",
            page=2,
            bbox=[120, 160, 880, 190],
            role_hint="body_text",
        ),
        make_observation(
            "obs000004",
            "text_region",
            text="Contents",
            page=3,
            bbox=[120, 100, 880, 130],
            role_hint="title_text",
        ),
        make_observation(
            "obs000005",
            "text_region",
            text="Chapter entries",
            page=3,
            bbox=[120, 160, 880, 500],
            role_hint="toc_text",
        ),
        make_observation(
            "obs000006",
            "text_region",
            text="More chapter entries",
            page=4,
            bbox=[120, 100, 880, 500],
            role_hint="toc_text",
        ),
        make_observation(
            "obs000007",
            "text_region",
            text="Foreword",
            page=5,
            bbox=[120, 100, 880, 130],
            role_hint="title_text",
        ),
        make_observation(
            "obs000008",
            "text_region",
            text="Foreword body",
            page=5,
            bbox=[120, 160, 880, 190],
            role_hint="body_text",
        ),
        make_observation(
            "obs000009",
            "text_region",
            text="Chapter One",
            page=6,
            bbox=[120, 100, 880, 130],
            role_hint="title_text",
        ),
        make_observation(
            "obs000010",
            "text_region",
            text="Subtitle",
            page=6,
            bbox=[120, 150, 880, 180],
            role_hint="title_text",
        ),
        make_observation(
            "obs000011",
            "text_region",
            text="Body starts here",
            page=6,
            bbox=[120, 220, 880, 250],
            role_hint="body_text",
        ),
        make_observation(
            "obs000012",
            "page_marker",
            text="1",
            page=6,
            bbox=[890, 940, 910, 960],
            role_hint="page_number",
        ),
        make_observation(
            "obs000013",
            "text_region",
            text="Next body page",
            page=7,
            bbox=[120, 100, 880, 130],
            role_hint="body_text",
        ),
        make_observation(
            "obs000014",
            "text_region",
            text="Next body page",
            page=8,
            bbox=[120, 100, 880, 130],
            role_hint="body_text",
        ),
    ]
    layout_audit = _layout_audit_with_body_profiles(list(range(2, 9)))
    document = make_observed_document(_metadata(), pages, observations)

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert [record["flow_scope"] for record in roles[:5]] == ["front_matter"] * 5
    assert roles[2]["page_role"] == "toc_page"
    assert roles[3]["page_role"] == "toc_page"
    assert [record["flow_scope"] for record in roles[5:]] == ["body"] * 3


def test_classify_observed_page_roles_marks_long_tail_note_zone_as_back_matter() -> None:
    pages = [make_observed_page(page, width=1000, height=1000) for page in range(1, 11)]
    observations = []
    for page in range(1, 7):
        observations.append(
            make_observation(
                f"obs{page:06d}",
                "text_region",
                text=f"Body {page}",
                page=page,
                bbox=[120, 100, 880, 130],
                role_hint="body_text",
            )
        )
    for page in range(7, 11):
        observations.extend(
            [
                make_observation(
                    f"obs{page:06d}a",
                    "footnote_region",
                    text=f"Note {page}.1",
                    page=page,
                    bbox=[120, 100, 880, 130],
                    role_hint="footnote_text",
                ),
                make_observation(
                    f"obs{page:06d}b",
                    "footnote_region",
                    text=f"Note {page}.2",
                    page=page,
                    bbox=[120, 160, 880, 190],
                    role_hint="footnote_text",
                ),
                make_observation(
                    f"obs{page:06d}c",
                    "footnote_region",
                    text=f"Note {page}.3",
                    page=page,
                    bbox=[120, 220, 880, 250],
                    role_hint="footnote_text",
                ),
            ]
        )
    layout_audit = _layout_audit_with_body_profiles(list(range(1, 11)))
    document = make_observed_document(_metadata(), pages, observations)

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert [record["flow_scope"] for record in roles[:6]] == ["body"] * 6
    assert [record["flow_scope"] for record in roles[6:]] == ["body"] * 4
    assert [record["page_role"] for record in roles[6:]] == ["note_section_candidate"] * 4


def test_classify_observed_page_roles_keeps_page_footnote_heavy_body_in_body_scope() -> None:
    pages = [make_observed_page(page, width=1000, height=1000) for page in range(1, 201)]
    observations = []
    for page in range(1, 201):
        for offset in range(4):
            observations.append(
                make_observation(
                    f"obs{page:06d}b{offset}",
                    "text_region",
                    text=f"Body line {page}.{offset}",
                    page=page,
                    bbox=[120, 100 + offset * 90, 880, 130 + offset * 90],
                    role_hint="body_text",
                )
            )
        footnote_count = 5 if page >= 100 else 1
        for offset in range(footnote_count):
            observations.append(
                make_observation(
                    f"obs{page:06d}f{offset}",
                    "footnote_region",
                    text=f"Footnote {page}.{offset}",
                    page=page,
                    bbox=[120, 760 + offset * 32, 880, 785 + offset * 32],
                    role_hint="footnote_text",
                )
            )
    layout_audit = _layout_audit_with_body_profiles(list(range(1, 201)))
    document = make_observed_document(_metadata(), pages, observations)

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert [record["flow_scope"] for record in roles] == ["body"] * 200


def test_classify_observed_page_roles_does_not_extend_note_zone_to_plain_tail_text() -> None:
    pages = [make_observed_page(page, width=1000, height=1000) for page in range(1, 13)]
    observations = []
    for page in range(1, 7):
        observations.extend(
            [
                make_observation(
                    f"obs{page:06d}a",
                    "text_region",
                    text=f"Body {page}",
                    page=page,
                    bbox=[120, 100, 880, 130],
                    role_hint="body_text",
                ),
                make_observation(
                    f"obs{page:06d}b",
                    "footnote_region",
                    text=f"Footnote {page}",
                    page=page,
                    bbox=[120, 840, 880, 870],
                    role_hint="footnote_text",
                ),
            ]
        )
    observations.append(
        make_observation(
            "obs000007a",
            "text_region",
            text="Tail section",
            page=7,
            bbox=[120, 100, 880, 130],
            role_hint="title_text",
        )
    )
    observations.extend(
        [
            make_observation(
                "obs000007b",
                "text_region",
                text="Tail section lead",
                page=7,
                bbox=[120, 160, 880, 190],
                role_hint="body_text",
            ),
            make_observation(
                "obs000007c",
                "footnote_region",
                text="Tail section first note",
                page=7,
                bbox=[120, 820, 880, 850],
                role_hint="footnote_text",
            ),
        ]
    )
    for page in range(8, 11):
        for offset in range(4):
            observations.append(
                make_observation(
                    f"obs{page:06d}{offset}",
                    "footnote_region",
                    text=f"Tail note {page}.{offset}",
                    page=page,
                    bbox=[120, 100 + offset * 60, 880, 130 + offset * 60],
                    role_hint="footnote_text",
                )
            )
    for page in range(11, 13):
        observations.append(
            make_observation(
                f"obs{page:06d}a",
                "text_region",
                text=f"Mixed tail {page}",
                page=page,
                bbox=[120, 100, 880, 130],
                role_hint="body_text",
            )
        )
    layout_audit = _layout_audit_with_body_profiles(list(range(1, 13)))
    document = make_observed_document(_metadata(), pages, observations)

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert [record["flow_scope"] for record in roles[:6]] == ["body"] * 6
    assert [record["flow_scope"] for record in roles[6:]] == ["body"] * 6
    assert [record["page_role"] for record in roles[6:]] == [
        "text_flow_page",
        "note_section_candidate",
        "note_section_candidate",
        "note_section_candidate",
        "text_flow_page",
        "text_flow_page",
    ]


def test_classify_observed_page_roles_fills_small_gaps_inside_note_clusters() -> None:
    pages = [make_observed_page(page, width=1000, height=1000) for page in range(1, 8)]
    observations = []
    for page in [2, 3, 6]:
        for offset in range(4):
            observations.append(
                make_observation(
                    f"obs{page:06d}{offset}",
                    "footnote_region",
                    text=f"Note {page}.{offset}",
                    page=page,
                    bbox=[120, 100 + offset * 60, 880, 130 + offset * 60],
                    role_hint="footnote_text",
                )
            )
    for page in [4, 5, 7]:
        observations.append(
            make_observation(
                f"obs{page:06d}a",
                "text_region",
                text=f"Tail text {page}",
                page=page,
                bbox=[120, 100, 880, 130],
                role_hint="body_text",
            )
        )
    layout_audit = _layout_audit_with_body_profiles(list(range(1, 8)))
    document = make_observed_document(_metadata(), pages, observations)

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert [record["page_role"] for record in roles] == [
        "blank_page",
        "note_section_candidate",
        "note_section_candidate",
        "note_section_candidate",
        "note_section_candidate",
        "note_section_candidate",
        "text_flow_page",
    ]


def test_classify_observed_page_roles_fills_three_page_note_gap_until_visual_barrier() -> None:
    pages = [make_observed_page(page, width=1000, height=1000) for page in range(1, 7)]
    observations = []
    for page in [1, 5]:
        for offset in range(4):
            observations.append(
                make_observation(
                    f"obs{page:06d}{offset}",
                    "footnote_region",
                    text=f"Note {page}.{offset}",
                    page=page,
                    bbox=[120, 100 + offset * 60, 880, 130 + offset * 60],
                    role_hint="footnote_text",
                )
            )
    observations.extend(
        [
            make_observation(
                "obs000002a",
                "page_marker",
                text="Note header",
                page=2,
                bbox=[700, 80, 860, 100],
                role_hint="header",
            ),
            make_observation(
                "obs000003a",
                "text_region",
                text="Note-like list text",
                page=3,
                bbox=[120, 100, 880, 360],
                role_hint="list_text",
            ),
            make_observation(
                "obs000004a",
                "table_region",
                page=4,
                bbox=[120, 200, 880, 700],
            ),
            make_observation(
                "obs000006a",
                "text_region",
                text="Text after cluster",
                page=6,
                bbox=[120, 100, 880, 130],
                role_hint="body_text",
            ),
        ]
    )
    layout_audit = _layout_audit_with_body_profiles(list(range(1, 7)))
    document = make_observed_document(_metadata(), pages, observations)

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert [record["page_role"] for record in roles] == [
        "note_section_candidate",
        "note_section_candidate",
        "note_section_candidate",
        "visual_page",
        "note_section_candidate",
        "text_flow_page",
    ]
    assert "note_cluster_gap" in roles[1]["signals"]
    assert "note_cluster_gap" in roles[2]["signals"]


def test_classify_observed_page_roles_keeps_visual_runs_as_visual_pages() -> None:
    pages = [make_observed_page(page, width=1000, height=1000) for page in range(1, 13)]
    observations = []
    for page in range(1, 5):
        for offset in range(10):
            observations.append(
                make_observation(
                    f"obs{page:06d}b{offset}",
                    "text_region",
                    text=f"Body {page}.{offset}",
                    page=page,
                    bbox=[120, 100 + offset * 40, 880, 130 + offset * 40],
                    role_hint="body_text",
                )
            )
    for page in range(5, 13):
        if page in {5, 6, 7, 8}:
            observations.append(
                make_observation(
                    f"obs{page:06d}i",
                    "image_region",
                    text="",
                    page=page,
                    bbox=[100, 120, 900, 760],
                    role_hint="unknown",
                )
            )
        observations.append(
            make_observation(
                f"obs{page:06d}c",
                "text_region",
                text=f"Caption-like text {page}",
                page=page,
                bbox=[140, 800, 860, 840],
                role_hint="body_text",
            )
        )
    layout_audit = _layout_audit_with_body_profiles(list(range(1, 13)))
    document = make_observed_document(_metadata(), pages, observations)

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert [record["flow_scope"] for record in roles[:4]] == ["body"] * 4
    assert [record["flow_scope"] for record in roles[4:]] == ["body"] * 8
    assert [record["page_role"] for record in roles[4:]] == [
        "visual_page",
        "visual_page",
        "visual_page",
        "visual_page",
        "text_flow_page",
        "text_flow_page",
        "text_flow_page",
        "text_flow_page",
    ]


def test_classify_observed_page_roles_keeps_known_flow_scopes_contiguous() -> None:
    pages = [make_observed_page(page, width=1000, height=1000) for page in range(1, 9)]
    observations = []
    for page in [1, 2, 3, 4, 5, 6, 8]:
        observations.extend(
            [
                make_observation(
                    f"obs{page:06d}a",
                    "text_region",
                    text=f"Body {page}.1",
                    page=page,
                    bbox=[120, 100, 880, 130],
                    role_hint="body_text",
                ),
                make_observation(
                    f"obs{page:06d}b",
                    "text_region",
                    text=f"Body {page}.2",
                    page=page,
                    bbox=[120, 160, 880, 190],
                    role_hint="body_text",
                ),
            ]
        )
    observations.append(
        make_observation(
            "obs000007i",
            "image_region",
            text="",
            page=7,
            bbox=[60, 80, 940, 940],
            role_hint="unknown",
        )
    )
    layout_audit = _layout_audit_with_body_profiles([1, 2, 3, 4, 5, 6, 8])
    document = make_observed_document(_metadata(), pages, observations)

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert [record["flow_scope"] for record in roles] == ["body"] * 8
    assert roles[6]["page_role"] == "visual_page"
    assert "late_page" in roles[6]["signals"]


def test_classify_observed_page_roles_marks_last_visual_mixed_page_as_back_cover_candidate() -> (
    None
):
    pages = [make_observed_page(page, width=1000, height=1000) for page in range(1, 4)]
    observations = [
        make_observation(
            "obs000001",
            "text_region",
            text="Body page",
            page=1,
            bbox=[120, 100, 880, 130],
            role_hint="body_text",
        ),
        make_observation(
            "obs000002",
            "text_region",
            text="Body page",
            page=2,
            bbox=[120, 100, 880, 130],
            role_hint="body_text",
        ),
        make_observation(
            "obs000003",
            "image_region",
            page=3,
            bbox=[430, 180, 570, 260],
        ),
        make_observation(
            "obs000004",
            "text_region",
            text="Back cover blurb",
            page=3,
            bbox=[120, 300, 880, 700],
            role_hint="body_text",
        ),
    ]
    layout_audit = _layout_audit_with_body_profiles(list(range(1, 4)))
    document = make_observed_document(_metadata(), pages, observations)

    roles = classify_observed_page_roles(document, layout_audit=layout_audit)

    assert roles[2]["page_role"] == "back_cover_candidate"
    assert roles[2]["signals"] == ["last_page_visual_content", "body_profile"]
