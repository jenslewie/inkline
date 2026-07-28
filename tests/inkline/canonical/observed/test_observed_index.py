from __future__ import annotations

import pytest

from inkline.canonical.observed import (
    build_observed_index,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.schema import ValidationError


def _document() -> dict:
    return make_observed_document(
        {
            "doc_id": "indexed-book",
            "title": "Indexed Book",
            "language": "en",
            "source_file": "indexed-book.pdf",
            "parser_name": "test-parser",
            "parser_mode": "structured",
        },
        [
            make_observed_page(3, width=1000, height=1400),
            make_observed_page(1, width=1000, height=1400),
            make_observed_page(2, width=1000, height=1400),
        ],
        [
            make_observation(
                "obs000003",
                "text_region",
                text="Third page",
                page=3,
                role_hint="body_text",
            ),
            make_observation(
                "obs000001",
                "text_region",
                text="First page title",
                page=1,
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="First page body",
                page=1,
                role_hint="body_text",
            ),
        ],
        assets={
            "images": [
                {"asset_id": "asset000001", "page": 1, "path": "images/one.png"},
            ],
            "page_images": {
                "three": {
                    "asset_id": "asset000003",
                    "page": 3,
                    "path": "pages/three.png",
                }
            },
        },
    )


def test_observed_index_preserves_physical_and_observation_order() -> None:
    document = _document()

    index = build_observed_index(document)

    assert index.doc_id == "indexed-book"
    assert index.metadata == document["metadata"]
    assert index.page_numbers == (1, 2, 3)
    assert tuple(index.pages_by_number) == (1, 2, 3)
    assert index.observation_ids_by_page == {
        1: ("obs000001", "obs000002"),
        2: (),
        3: ("obs000003",),
    }
    assert tuple(index.observations_by_id) == ("obs000003", "obs000001", "obs000002")


def test_observed_index_references_the_validated_source_records() -> None:
    document = _document()

    index = build_observed_index(document)

    assert index.pages_by_number[1] is document["pages"][1]
    assert index.observations_by_id["obs000001"] is document["observations"][1]
    assert index.assets_by_id["asset000001"] is document["assets"]["images"][0]
    assert index.assets_by_id["asset000003"] is document["assets"]["page_images"]["three"]


def test_observed_index_exposes_read_only_lookup_mappings() -> None:
    index = build_observed_index(_document())

    with pytest.raises(TypeError):
        index.metadata["doc_id"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        index.pages_by_number[4] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        index.observations_by_id["obs000004"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        index.observation_ids_by_page[1] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        index.assets_by_id["asset000004"] = {}  # type: ignore[index]


def test_observed_index_uses_observed_document_validation_for_duplicate_observations() -> None:
    document = _document()
    document["observations"].append(dict(document["observations"][0]))

    with pytest.raises(ValidationError, match="duplicate observation_id"):
        build_observed_index(document)


def test_observed_index_rejects_duplicate_asset_ids() -> None:
    document = _document()
    document["assets"]["images"].append(
        {"asset_id": "asset000001", "page": 2, "path": "images/duplicate.png"}
    )

    with pytest.raises(ValidationError, match="duplicate asset_id"):
        build_observed_index(document)
