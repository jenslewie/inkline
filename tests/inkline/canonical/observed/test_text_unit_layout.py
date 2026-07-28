from __future__ import annotations

import pytest

from inkline.canonical import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    build_page_layout_analysis,
    build_text_units,
    classify_text_units_by_layout,
    make_observation,
    make_observed_document,
    make_observed_page,
)


def test_text_unit_layout_consumes_page_layout_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = make_observed_document(
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
                text="Inset",
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
    page_layout = build_page_layout_analysis(document)
    units, _ignored = build_text_units(document)

    def fail_if_profile_is_rebuilt(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("page profile was rebuilt from TextUnits")

    monkeypatch.setattr(
        "inkline.canonical.observed.text_unit_layout._page_layout_profile_map",
        fail_if_profile_is_rebuilt,
    )

    classified = classify_text_units_by_layout(
        units,
        document["pages"],
        page_layout=page_layout,
    )

    assert [unit["unit_type"] for unit in classified] == [
        "paragraph",
        "display_block",
        "paragraph",
    ]
