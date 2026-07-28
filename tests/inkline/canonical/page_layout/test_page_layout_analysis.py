from __future__ import annotations

import json

import pytest

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    build_observed_index,
    build_page_layout_analysis,
    make_observation,
    make_observed_document,
    make_observed_page,
    validate_page_layout_analysis,
)
from inkline.canonical.schema import ValidationError


def _document() -> dict:
    return make_observed_document(
        {
            "schema_name": OBSERVED_SCHEMA_NAME,
            "schema_version": OBSERVED_SCHEMA_VERSION,
            "doc_id": "book",
            "title": "Book",
            "language": "en",
            "source_file": "book.pdf",
            "parser_name": "test-parser",
            "parser_mode": "structured",
        },
        [make_observed_page(page, width=1000, height=1000) for page in range(1, 5)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Stable body lane",
                page=1,
                bbox=[100, 100, 900, 210],
                spans=[
                    {"page": 1, "bbox": [100, 100, 900, 130]},
                    {"page": 1, "bbox": [100, 140, 900, 170]},
                    {"page": 1, "bbox": [100, 180, 900, 210]},
                ],
                role_hint="body_text",
                attrs={
                    "reading_order": 1,
                    "text_line_metrics": {
                        "line_count": 3,
                        "first_line_indent": 20,
                        "char_width": 10,
                    },
                },
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Sparse title",
                page=2,
                bbox=[350, 120, 650, 180],
                role_hint="title_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000003",
                "image_region",
                page=3,
                bbox=[100, 100, 900, 700],
            ),
            make_observation(
                "obs000004",
                "text_region",
                text="Caption",
                page=3,
                bbox=[300, 750, 700, 790],
                role_hint="caption_text",
                attrs={"reading_order": 1},
            ),
            make_observation(
                "obs000005",
                "text_region",
                text="Geometry unavailable",
                page=4,
                role_hint="body_text",
                attrs={"reading_order": 1},
            ),
        ],
    )


def test_page_layout_analysis_contract_is_observation_based() -> None:
    analysis = build_page_layout_analysis(_document())

    assert analysis["metadata"] == {
        "schema_name": "inkline_page_layout_analysis",
        "schema_version": "0.1-shadow",
        "doc_id": "book",
    }
    assert [record["page"] for record in analysis["pages"]] == [1, 2, 3, 4]
    assert "text_units" not in analysis
    assert "unit_id" not in json.dumps(analysis)


def test_page_layout_analysis_characterizes_profiles_coverage_and_role_signals() -> None:
    analysis = build_page_layout_analysis(_document())

    assert analysis["book_layout_profile"] == {
        "profile_scope": "book",
        "source_page_count": 1,
        "body_width": 800.0,
        "indent_unit": 20.0,
        "line_height": 30.0,
        "normal_gap_y": 10.0,
        "display_gap_y": None,
    }
    assert analysis["pages"][0]["body_lane"] == {
        "profile_scope": "page",
        "profile_source": "local",
        "page_width": 1000.0,
        "page_height": 1000.0,
        "body_left": 100.0,
        "body_right": 900.0,
        "body_width": 800.0,
        "book_body_width": 800.0,
        "body_width_delta": 0.0,
        "indent_unit": 20.0,
        "line_height": 30.0,
        "normal_gap_y": 10.0,
        "display_gap_y": None,
        "reference_fragment_count": 3,
    }
    assert [record["coverage"]["profile_status"] for record in analysis["pages"]] == [
        "profiled",
        "title_only",
        "visual_with_text",
        "body_text_without_bbox",
    ]
    assert analysis["pages"][1]["role_signals"] == {
        "kind_counts": {"text_region": 1},
        "role_hint_counts": {"title_text": 1},
        "content_count": 1,
        "text_count": 1,
        "visual_count": 0,
        "body_zone_footnote_count": 0,
        "visual_area_ratio": 0.0,
        "text_area_ratio": 0.018,
        "centered_text_ratio": 1.0,
        "tall_text_count": 0,
    }
    assert analysis["audit"] == {
        "total_pages": 4,
        "pages_with_profiles": 1,
        "pages_without_profiles": 3,
        "pages_without_profiles_by_reason": {
            "body_text_without_bbox": 1,
            "title_only": 1,
            "visual_with_text": 1,
        },
        "profile_quality": {
            "accepted": 1,
            "filled_from_nearest_profile": 0,
            "rejected_no_stable_profile": 0,
            "rejected_invalid_width": 0,
            "rejected_unstable_widths": 0,
            "rejected_extreme_body_width": 0,
        },
    }


def test_page_layout_analysis_reuses_supplied_observed_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    index = build_observed_index(document)

    def fail_if_rebuilt(_document: dict) -> None:
        raise AssertionError("ObservedDocument was rescanned")

    monkeypatch.setattr(
        "inkline.canonical.page_layout.builder.build_observed_index",
        fail_if_rebuilt,
    )

    analysis = build_page_layout_analysis(document, observed_index=index)

    assert analysis["metadata"]["doc_id"] == "book"


def test_page_layout_analysis_rejects_mismatched_observed_index() -> None:
    document = _document()
    other = _document()
    other["metadata"]["doc_id"] = "other"
    index = build_observed_index(other)

    with pytest.raises(ValidationError, match="does not match"):
        build_page_layout_analysis(document, observed_index=index)


def test_validate_page_layout_analysis_rejects_unordered_pages() -> None:
    analysis = build_page_layout_analysis(_document())
    analysis["pages"] = list(reversed(analysis["pages"]))

    with pytest.raises(ValidationError, match="unique and ordered"):
        validate_page_layout_analysis(analysis)


def test_validate_page_layout_analysis_rejects_incomplete_body_lane() -> None:
    analysis = build_page_layout_analysis(_document())
    analysis["pages"][0]["body_lane"].pop("reference_fragment_count")

    with pytest.raises(ValidationError, match=r"pages\[0\]\.body_lane"):
        validate_page_layout_analysis(analysis)


def test_sparse_centered_title_cluster_body_hints_do_not_define_body_lane() -> None:
    document = make_observed_document(
        _document()["metadata"],
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Chapter label",
                page=1,
                bbox=[300, 250, 700, 280],
                role_hint="body_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Chapter title",
                page=1,
                bbox=[350, 330, 650, 370],
                role_hint="title_text",
            ),
            make_observation(
                "obs000003",
                "text_region",
                text="Chapter subtitle",
                page=1,
                bbox=[300, 420, 700, 450],
                role_hint="body_text",
            ),
        ],
    )

    analysis = build_page_layout_analysis(document)

    assert analysis["pages"][0]["body_lane"] is None
    assert analysis["pages"][0]["coverage"] == {"profile_status": "title_cluster"}
