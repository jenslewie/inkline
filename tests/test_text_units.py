from __future__ import annotations

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    make_observation,
    make_observed_document,
    make_observed_page,
)
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
