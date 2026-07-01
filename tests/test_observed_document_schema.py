from __future__ import annotations

import pytest

from inkline.canonical import ValidationError
from inkline.canonical.observed import (
    OBSERVED_SCHEMA_NAME,
    OBSERVED_SCHEMA_VERSION,
    make_observation,
    make_observed_document,
    make_observed_page,
    validate_observed_document,
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


def _document() -> dict:
    return make_observed_document(
        _metadata(),
        [make_observed_page(1, width=1000, height=1000)],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Body text",
                page=1,
                bbox=[10, 20, 300, 80],
                spans=[{"bbox": [10, 20, 300, 80]}],
                role_hint="body_text",
                attrs={"reading_order": 1},
                parser_payload={"raw_type": "paragraph"},
            )
        ],
        assets={"images": []},
    )


def test_minimal_observed_document_passes() -> None:
    document = _document()

    validate_observed_document(document)


def test_observation_keeps_parser_specific_raw_fields_in_payload() -> None:
    observation = _document()["observations"][0]

    assert observation["role_hint"] == "body_text"
    assert observation["parser_payload"] == {"raw_type": "paragraph"}
    assert "raw_type" not in observation
    assert "raw_types" not in observation


def test_unknown_observation_kind_fails() -> None:
    document = _document()
    document["observations"][0]["kind"] = "mineru_paragraph"

    with pytest.raises(ValidationError, match="kind"):
        validate_observed_document(document)


def test_duplicate_observation_id_fails() -> None:
    document = _document()
    document["observations"].append(dict(document["observations"][0]))

    with pytest.raises(ValidationError, match="duplicate observation_id"):
        validate_observed_document(document)


def test_observation_page_must_exist() -> None:
    document = _document()
    document["observations"][0]["page"] = 99

    with pytest.raises(ValidationError, match="page"):
        validate_observed_document(document)


def test_bbox_must_be_null_or_four_numbers() -> None:
    document = _document()
    document["observations"][0]["bbox"] = [1, 2, 3]

    with pytest.raises(ValidationError, match="bbox"):
        validate_observed_document(document)


def test_bbox_field_is_required_but_may_be_null() -> None:
    document = _document()
    document["observations"][0].pop("bbox")

    with pytest.raises(ValidationError, match="bbox"):
        validate_observed_document(document)

    document = _document()
    document["observations"][0]["bbox"] = None

    validate_observed_document(document)
