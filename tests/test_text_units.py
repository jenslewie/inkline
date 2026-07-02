from __future__ import annotations

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    audit_text_unit_layout,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.text_unit_layout import classify_text_units_by_layout
from inkline.canonical.text_units import build_text_units


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


def _document(observations: list[dict]) -> dict:
    return make_observed_document(
        _metadata(),
        [make_observed_page(1, width=1000, height=1000)],
        observations,
    )


def _document_with_pages(observations: list[dict], pages: list[dict]) -> dict:
    return make_observed_document(_metadata(), pages, observations)


def test_adjacent_body_observations_merge_into_one_text_unit() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="First line",
                page=1,
                bbox=[100, 100, 700, 130],
                spans=[{"page": 1, "bbox": [100, 100, 700, 130]}],
                role_hint="body_text",
                attrs={"reading_order": 1},
                parser_payload={"source": "first"},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Second line",
                page=1,
                bbox=[102, 135, 690, 160],
                spans=[{"page": 1, "bbox": [102, 135, 690, 160]}],
                role_hint="body_text",
                attrs={"reading_order": 2},
                parser_payload={"source": "second"},
            ),
        ]
    )

    units, ignored = build_text_units(document)

    assert ignored == {}
    assert len(units) == 1
    unit = units[0]
    assert unit["unit_id"] == "tu000001"
    assert unit["unit_type"] == "paragraph"
    assert unit["text"] == "First line\nSecond line"
    assert unit["page"] == 1
    assert unit["pages"] == [1]
    assert unit["bbox"] == [100, 100, 700, 160]
    assert unit["observation_ids"] == ["obs000001", "obs000002"]
    assert unit["role_hints"] == ["body_text"]
    assert unit["spans"] == [
        {"page": 1, "bbox": [100, 100, 700, 130]},
        {"page": 1, "bbox": [102, 135, 690, 160]},
    ]
    assert unit["parser_payloads"] == [{"source": "first"}, {"source": "second"}]


def test_large_vertical_gap_starts_new_text_unit() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="First",
                page=1,
                bbox=[100, 100, 700, 130],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Second",
                page=1,
                bbox=[100, 230, 700, 260],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ]
    )

    units, ignored = build_text_units(document)

    assert ignored == {}
    assert [unit["text"] for unit in units] == ["First", "Second"]
    assert [unit["unit_id"] for unit in units] == ["tu000001", "tu000002"]


def test_incompatible_role_hints_do_not_merge() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Chapter",
                page=1,
                bbox=[100, 100, 700, 130],
                role_hint="title_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Body",
                page=1,
                bbox=[100, 135, 700, 160],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ]
    )

    units, ignored = build_text_units(document)

    assert ignored == {}
    assert [unit["unit_type"] for unit in units] == ["heading", "paragraph"]
    assert [unit["text"] for unit in units] == ["Chapter", "Body"]


def test_centered_fragments_on_text_only_heading_page_merge_into_one_heading() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Chapter number",
                page=1,
                bbox=[455, 300, 545, 322],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Main title",
                page=1,
                bbox=[360, 365, 640, 405],
                role_hint="title_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Subtitle",
                page=1,
                bbox=[260, 430, 740, 462],
                role_hint="body_text",
                attrs={"reading_order": 3},
            ),
        ]
    )

    units, ignored = build_text_units(document)

    assert ignored == {}
    assert [unit["unit_type"] for unit in units] == ["heading"]
    assert units[0]["text"] == "Chapter number\nMain title\nSubtitle"
    assert units[0]["bbox"] == [260, 300, 740, 462]
    assert units[0]["observation_ids"] == ["obs000001", "obs000002", "obs000003"]
    assert units[0]["role_hints"] == ["body_text", "title_text"]
    assert units[0]["attrs"]["structure_promotion"] == "heading_cluster"
    assert units[0]["attrs"]["merge_reasons"] == ["heading_cluster", "heading_cluster"]


def test_wide_body_paragraph_after_heading_does_not_promote_to_heading() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Section heading",
                page=1,
                bbox=[410, 180, 590, 210],
                role_hint="title_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Body paragraph",
                page=1,
                bbox=[110, 280, 890, 920],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ]
    )

    units, _ = build_text_units(document)

    assert [unit["unit_type"] for unit in units] == ["heading", "paragraph"]


def test_image_text_heading_page_does_not_promote_map_labels_to_heading() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "image_region",
                page=1,
                bbox=[100, 100, 900, 700],
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Map title",
                page=1,
                bbox=[410, 720, 590, 745],
                role_hint="title_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Map label",
                page=1,
                bbox=[430, 760, 570, 780],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ]
    )

    units, _ = build_text_units(document)

    assert [unit["unit_type"] for unit in units] == ["paragraph"]


def test_non_text_observations_are_ignored_with_counts() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "image_region",
                page=1,
                bbox=[100, 100, 700, 400],
            ),
            make_observation(
                "obs000002",
                "page_marker",
                text="1",
                page=1,
                bbox=[480, 950, 520, 970],
                role_hint="page_number",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body",
                page=1,
                bbox=[100, 500, 700, 530],
                role_hint="body_text",
            ),
        ]
    )

    units, ignored = build_text_units(document)

    assert [unit["text"] for unit in units] == ["Body"]
    assert ignored == {"image_region": 1, "page_marker": 1}


def test_null_bbox_prevents_geometry_merge() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="First",
                page=1,
                bbox=None,
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Second",
                page=1,
                bbox=[100, 135, 700, 160],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ]
    )

    units, ignored = build_text_units(document)

    assert ignored == {}
    assert [unit["text"] for unit in units] == ["First", "Second"]


def test_page_boundary_body_observations_merge_across_adjacent_pages() -> None:
    document = _document_with_pages(
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
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
    )

    units, ignored = build_text_units(document)

    assert ignored == {}
    assert len(units) == 1
    unit = units[0]
    assert unit["text"] == "Page bottom\nPage top"
    assert unit["page"] == 1
    assert unit["pages"] == [1, 2]
    assert unit["bbox"] == [100, 900, 700, 980]
    assert unit["spans"] == [
        {"page": 1, "bbox": [100, 900, 700, 980]},
        {"page": 2, "bbox": [102, 30, 690, 90]},
    ]
    assert unit["attrs"]["merge_reasons"] == ["cross_page_boundary_continuation"]


def test_non_boundary_body_observations_do_not_merge_across_pages() -> None:
    document = _document_with_pages(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Middle of page",
                page=1,
                bbox=[100, 500, 700, 580],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Page top",
                page=2,
                bbox=[102, 30, 690, 90],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
        ],
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
    )

    units, ignored = build_text_units(document)

    assert ignored == {}
    assert [unit["text"] for unit in units] == ["Middle of page", "Page top"]


def test_layout_classifier_marks_inset_narrow_body_unit_as_display_block() -> None:
    document = _document(
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
        ]
    )
    units, _ = build_text_units(document)

    classified = classify_text_units_by_layout(units, document["pages"])

    assert [unit["unit_type"] for unit in classified] == [
        "paragraph",
        "display_block",
        "paragraph",
    ]
    assert classified[1]["attrs"]["layout_role"] == "set_off"
    assert classified[1]["attrs"]["layout_classification"]["signals"] == [
        "narrower_than_body_lane",
        "inset_from_body_lane",
    ]


def test_layout_classifier_marks_right_aligned_short_line_group_as_display_block() -> None:
    document = _document(
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
                text="Attribution",
                page=1,
                bbox=[640, 165, 900, 185],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Affiliation",
                page=1,
                bbox=[500, 190, 900, 210],
                role_hint="body_text",
                attrs={"reading_order": 3},
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="Body after",
                page=1,
                bbox=[100, 250, 900, 280],
                role_hint="body_text",
                attrs={"reading_order": 4},
            ),
        ]
    )
    units, _ = build_text_units(document)

    classified = classify_text_units_by_layout(units, document["pages"])

    assert [unit["unit_type"] for unit in classified] == [
        "paragraph",
        "display_block",
        "paragraph",
    ]
    assert classified[1]["text"] == "Attribution\nAffiliation"
    assert classified[1]["attrs"]["layout_role"] == "set_off"
    assert classified[1]["attrs"]["layout_form"] == "short_line_group"
    assert classified[1]["attrs"]["alignment"] == "right"
    assert (
        "right_aligned_short_line_group"
        in classified[1]["attrs"]["layout_classification"]["signals"]
    )


def test_layout_classifier_marks_left_inset_set_off_text_as_display_block() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body before",
                page=1,
                bbox=[100, 100, 900, 160],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Set off quotation",
                page=1,
                bbox=[150, 195, 890, 250],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body after",
                page=1,
                bbox=[100, 285, 900, 345],
                role_hint="body_text",
                attrs={"reading_order": 3},
            ),
        ]
    )
    units, _ = build_text_units(document)

    classified = classify_text_units_by_layout(units, document["pages"])

    assert [unit["unit_type"] for unit in classified] == [
        "paragraph",
        "display_block",
        "paragraph",
    ]
    assert classified[1]["text"] == "Set off quotation"
    assert classified[1]["attrs"]["layout_role"] == "set_off"
    assert "left_inset_set_off_text" in classified[1]["attrs"]["layout_classification"]["signals"]


def test_layout_classifier_keeps_single_body_unit_as_paragraph() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Only body",
                page=1,
                bbox=[260, 170, 730, 200],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
        ]
    )
    units, _ = build_text_units(document)

    classified = classify_text_units_by_layout(units, document["pages"])

    assert [unit["unit_type"] for unit in classified] == ["paragraph"]
    assert "layout_classification" not in classified[0]["attrs"]


def test_layout_classifier_builds_body_lane_from_text_unit_spans() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body paragraph",
                page=1,
                bbox=[100, 100, 900, 190],
                spans=[
                    {"page": 1, "bbox": [100, 100, 900, 130]},
                    {"page": 1, "bbox": [100, 130, 900, 160]},
                    {"page": 1, "bbox": [100, 160, 900, 190]},
                ],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Inset text",
                page=1,
                bbox=[260, 230, 730, 260],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ]
    )
    units, _ = build_text_units(document)

    classified = classify_text_units_by_layout(units, document["pages"])
    audit = audit_text_unit_layout(units, document["pages"])

    assert [unit["unit_type"] for unit in classified] == ["paragraph", "display_block"]
    assert audit["summary"] == {
        "total_pages": 1,
        "pages_with_profiles": 1,
        "pages_without_profiles": 0,
        "pages_without_profiles_by_reason": {},
        "paragraph_units": 2,
        "classified_display_blocks": 1,
        "skipped_no_bbox": 0,
        "skipped_no_profile": 0,
    }
    assert audit["page_profiles"][0]["reference_unit_count"] == 3


def test_layout_audit_reports_page_coverage_reasons() -> None:
    document = _document_with_pages(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Title",
                page=1,
                bbox=[400, 100, 600, 140],
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "image_region",
                page=2,
                bbox=[100, 100, 900, 900],
            ),
            make_observation(
                "obs000003",
                "table_region",
                page=3,
                bbox=[100, 100, 900, 900],
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="Chapter",
                page=5,
                bbox=[400, 100, 600, 140],
                role_hint="title_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="Body paragraph",
                page=5,
                bbox=[100, 180, 900, 240],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000006",
                "image_region",
                page=6,
                bbox=[100, 100, 900, 700],
            ),
            make_observation(
                "obs000007",
                "text_region",
                text="Map label",
                page=6,
                bbox=[300, 750, 500, 780],
                role_hint="body_text",
            ),
            make_observation(
                "obs000008",
                "text_region",
                text="Body",
                page=7,
                bbox=[100, 100, 900, 220],
                spans=[
                    {"page": 7, "bbox": [100, 100, 900, 130]},
                    {"page": 7, "bbox": [100, 150, 900, 180]},
                    {"page": 7, "bbox": [100, 190, 900, 220]},
                ],
                role_hint="body_text",
            ),
            make_observation(
                "obs000009",
                "text_region",
                text="No stable lane",
                page=8,
                bbox=[100, 100, 600, 220],
                spans=[
                    {"page": 8, "bbox": [100, 100, 600, 130]},
                    {"page": 8, "bbox": [100, 150, 390, 180]},
                    {"page": 8, "bbox": [100, 190, 300, 220]},
                ],
                role_hint="body_text",
            ),
        ],
        [make_observed_page(page, width=1000, height=1000) for page in range(1, 9)],
    )
    units, _ = build_text_units(document)

    audit = audit_text_unit_layout(units, document["pages"], document["observations"])

    assert audit["summary"]["total_pages"] == 8
    assert audit["summary"]["pages_without_profiles"] == 4
    assert audit["summary"]["pages_without_profiles_by_reason"] == {
        "empty": 1,
        "heading_only": 1,
        "image_only": 1,
        "table_only": 1,
    }
    assert audit["page_coverage"]["pages_without_profiles"] == [
        {"page": 1, "reason": "heading_only"},
        {"page": 2, "reason": "image_only"},
        {"page": 3, "reason": "table_only"},
        {"page": 4, "reason": "empty"},
    ]
    assert audit["page_coverage"]["mixed_pages"] == {
        "heading_with_paragraph_units": [5],
        "image_with_text_units": [6],
        "table_with_text_units": [],
    }


def test_layout_profile_ignores_short_line_outliers_when_estimating_body_lane() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body paragraph with short carryover",
                page=1,
                bbox=[100, 100, 900, 220],
                spans=[
                    {"page": 1, "bbox": [100, 100, 180, 130]},
                    {"page": 1, "bbox": [100, 140, 900, 170]},
                    {"page": 1, "bbox": [100, 180, 900, 220]},
                ],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Inset text",
                page=1,
                bbox=[150, 260, 870, 310],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Body after",
                page=1,
                bbox=[100, 350, 900, 410],
                role_hint="body_text",
                attrs={"reading_order": 3},
            ),
        ]
    )
    units, _ = build_text_units(document)

    classified = classify_text_units_by_layout(units, document["pages"])
    audit = audit_text_unit_layout(units, document["pages"])

    assert [unit["unit_type"] for unit in classified] == [
        "paragraph",
        "display_block",
        "paragraph",
    ]
    assert audit["summary"]["skipped_no_profile"] == 0
    assert audit["profile_quality"]["accepted"] == 1
    assert audit["profile_quality"]["rejected_unstable_widths"] == 0
    assert audit["page_profiles"][0]["body_left"] == 100.0
    assert audit["page_profiles"][0]["body_right"] == 900.0
    assert audit["page_profiles"][0]["body_width"] == 800.0


def test_layout_profile_uses_widest_stable_lane_when_page_has_many_short_lines() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Mixed body and short lines",
                page=1,
                bbox=[100, 100, 900, 440],
                spans=[
                    {"page": 1, "bbox": [100, 100, 185, 120]},
                    {"page": 1, "bbox": [100, 135, 205, 155]},
                    {"page": 1, "bbox": [100, 170, 900, 200]},
                    {"page": 1, "bbox": [100, 215, 900, 245]},
                    {"page": 1, "bbox": [100, 260, 900, 290]},
                    {"page": 1, "bbox": [220, 305, 380, 325]},
                    {"page": 1, "bbox": [220, 340, 470, 360]},
                    {"page": 1, "bbox": [100, 385, 365, 405]},
                    {"page": 1, "bbox": [100, 420, 235, 440]},
                    {"page": 1, "bbox": [100, 455, 235, 475]},
                    {"page": 1, "bbox": [100, 490, 235, 510]},
                    {"page": 1, "bbox": [100, 525, 190, 545]},
                    {"page": 1, "bbox": [100, 560, 235, 580]},
                    {"page": 1, "bbox": [100, 595, 190, 615]},
                ],
                role_hint="body_text",
                attrs={"reading_order": 1},
            )
        ]
    )
    units, _ = build_text_units(document)

    audit = audit_text_unit_layout(units, document["pages"])

    assert audit["summary"]["skipped_no_profile"] == 0
    assert audit["profile_quality"]["accepted"] == 1
    assert audit["profile_quality"]["rejected_unstable_widths"] == 0
    assert audit["page_profiles"][0]["body_left"] == 100.0
    assert audit["page_profiles"][0]["body_right"] == 900.0
    assert audit["page_profiles"][0]["body_width"] == 800.0
    assert audit["page_profiles"][0]["reference_unit_count"] == 3


def test_layout_profile_uses_nearest_stable_profile_for_sparse_page() -> None:
    document = _document_with_pages(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body before",
                page=1,
                bbox=[100, 100, 900, 250],
                spans=[
                    {"page": 1, "bbox": [100, 100, 900, 130]},
                    {"page": 1, "bbox": [100, 160, 900, 190]},
                    {"page": 1, "bbox": [100, 220, 900, 250]},
                ],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Sparse page inset text",
                page=2,
                bbox=[150, 100, 870, 150],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ],
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
    )
    units, _ = build_text_units(document)

    classified = classify_text_units_by_layout(units, document["pages"])
    audit = audit_text_unit_layout(units, document["pages"])

    assert [unit["unit_type"] for unit in classified] == ["paragraph", "paragraph"]
    assert audit["summary"]["skipped_no_profile"] == 0
    assert audit["profile_quality"]["accepted"] == 1
    assert audit["profile_quality"]["filled_from_nearest_profile"] == 1
    assert audit["page_profiles"][1] == {
        "page": 2,
        "page_width": 1000.0,
        "page_height": 1000.0,
        "body_left": 100.0,
        "body_right": 900.0,
        "body_width": 800.0,
        "reference_unit_count": 1,
        "profile_source": "nearest_page",
        "profile_source_page": 1,
    }
    assert audit["unit_records"][1]["profile_source"] == "nearest_page"
    assert audit["unit_records"][1]["signals"] == []


def test_layout_profile_uses_nearest_stable_profile_for_narrow_local_references() -> None:
    document = _document_with_pages(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body before",
                page=1,
                bbox=[100, 100, 900, 250],
                spans=[
                    {"page": 1, "bbox": [100, 100, 900, 130]},
                    {"page": 1, "bbox": [100, 160, 900, 190]},
                    {"page": 1, "bbox": [100, 220, 900, 250]},
                ],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Narrow local structure",
                page=2,
                bbox=[420, 100, 610, 220],
                spans=[
                    {"page": 2, "bbox": [420, 100, 610, 130]},
                    {"page": 2, "bbox": [422, 160, 608, 190]},
                    {"page": 2, "bbox": [421, 220, 609, 250]},
                ],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ],
        [
            make_observed_page(1, width=1000, height=1000),
            make_observed_page(2, width=1000, height=1000),
        ],
    )
    units, _ = build_text_units(document)

    audit = audit_text_unit_layout(units, document["pages"])

    assert audit["summary"]["skipped_no_profile"] == 0
    assert audit["profile_quality"]["filled_from_nearest_profile"] == 1
    assert audit["profile_quality"]["rejected_extreme_body_width"] == 0
    assert audit["page_profiles"][1]["profile_source"] == "nearest_page"
    assert audit["page_profiles"][1]["profile_source_page"] == 1
    assert audit["unit_records"][1]["body_width"] == 800.0


def test_layout_profile_quality_rejects_page_without_dominant_body_lane() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Unstable layout",
                page=1,
                bbox=[100, 100, 900, 220],
                spans=[
                    {"page": 1, "bbox": [100, 100, 900, 130]},
                    {"page": 1, "bbox": [100, 130, 590, 160]},
                    {"page": 1, "bbox": [100, 160, 600, 190]},
                    {"page": 1, "bbox": [100, 190, 400, 220]},
                ],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Inset text",
                page=1,
                bbox=[260, 260, 730, 290],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ]
    )
    units, _ = build_text_units(document)

    classified = classify_text_units_by_layout(units, document["pages"])
    audit = audit_text_unit_layout(units, document["pages"])

    assert [unit["unit_type"] for unit in classified] == ["paragraph", "paragraph"]
    assert audit["page_profiles"] == []
    assert audit["profile_quality"]["rejected_no_stable_profile"] == 1


def test_layout_profile_quality_rejects_extremely_narrow_body_width() -> None:
    document = _document(
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Narrow page fragment",
                page=1,
                bbox=[430, 100, 520, 190],
                spans=[
                    {"page": 1, "bbox": [430, 100, 520, 130]},
                    {"page": 1, "bbox": [430, 130, 520, 160]},
                    {"page": 1, "bbox": [430, 160, 520, 190]},
                ],
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Inset text",
                page=1,
                bbox=[445, 400, 500, 430],
                role_hint="body_text",
                attrs={"reading_order": 2},
            ),
        ]
    )
    units, _ = build_text_units(document)

    classified = classify_text_units_by_layout(units, document["pages"])
    audit = audit_text_unit_layout(units, document["pages"])

    assert [unit["unit_type"] for unit in classified] == ["paragraph", "paragraph"]
    assert audit["page_profiles"] == []
    assert audit["profile_quality"]["rejected_extreme_body_width"] == 1


def test_layout_audit_reports_page_profiles_and_candidate_signals_without_text() -> None:
    document = _document(
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
        ]
    )
    units, _ = build_text_units(document)

    audit = audit_text_unit_layout(units, document["pages"])

    assert audit["summary"] == {
        "total_pages": 1,
        "pages_with_profiles": 1,
        "pages_without_profiles": 0,
        "pages_without_profiles_by_reason": {},
        "paragraph_units": 3,
        "classified_display_blocks": 1,
        "skipped_no_bbox": 0,
        "skipped_no_profile": 0,
    }
    assert audit["page_profiles"] == [
        {
            "page": 1,
            "page_width": 1000.0,
            "page_height": 1000.0,
            "body_left": 100.0,
            "body_right": 900.0,
            "body_width": 800.0,
            "reference_unit_count": 2,
        }
    ]
    assert audit["unit_records"][1] == {
        "unit_id": "tu000002",
        "page": 1,
        "original_type": "paragraph",
        "classified_type": "display_block",
        "bbox": [260, 170, 730, 200],
        "width": 470.0,
        "body_width": 800.0,
        "width_ratio": 0.5875,
        "left_inset": 160.0,
        "right_inset": 170.0,
        "signals": ["narrower_than_body_lane", "inset_from_body_lane"],
        "decision": "display_block",
    }
    assert "text" not in audit["unit_records"][1]
