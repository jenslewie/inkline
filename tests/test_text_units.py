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
        "pages_with_profiles": 1,
        "paragraph_units": 2,
        "classified_display_blocks": 1,
        "skipped_no_bbox": 0,
        "skipped_no_profile": 0,
    }
    assert audit["page_profiles"][0]["reference_unit_count"] == 4


def test_layout_profile_quality_rejects_unstable_reference_widths() -> None:
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
                    {"page": 1, "bbox": [100, 130, 900, 160]},
                    {"page": 1, "bbox": [100, 160, 280, 190]},
                    {"page": 1, "bbox": [700, 190, 900, 220]},
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
    assert audit["profile_quality"]["rejected_unstable_widths"] == 1


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
        "pages_with_profiles": 1,
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
            "reference_unit_count": 3,
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
