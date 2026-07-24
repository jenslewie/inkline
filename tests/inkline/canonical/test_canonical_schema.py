import json
import re

import pytest

from inkline.canonical import (
    BLOCK_TYPES,
    MigrationError,
    ValidationError,
    make_block,
    make_document,
    make_toc_entry,
    sample_document,
    validate_document,
)
from inkline.canonical.io import read_canonical


def test_sample_document_validates():
    validate_document(sample_document())


def test_document_requires_core_top_level_fields():
    document = sample_document()
    document.pop("source_map")

    with pytest.raises(ValidationError, match="source_map"):
        validate_document(document)


def test_pages_metadata_validates_when_present():
    document = sample_document()
    document["pages"] = [
        {
            "physical_page": 1,
            "region": "front_matter",
            "page_role": "cover",
            "snapshot": {"required": True, "role": "designed_media_page"},
        }
    ]

    validate_document(document)


def test_block_types_match_public_contract():
    assert {
        "heading",
        "paragraph",
        "toc_item",
        "display_block",
        "list_item",
        "table",
        "table_continuation",
        "figure",
        "caption",
        "footnote",
    } == BLOCK_TYPES


@pytest.mark.parametrize("block_type", sorted(BLOCK_TYPES))
def test_public_block_types_validate(block_type):
    document = make_document(
        doc_id="sample",
        title="Sample",
        language="zh-CN",
        source_file="sample.pdf",
        parser_name="sample",
        parser_mode="base",
        blocks=[
            make_block("b000001", block_type, "示例文本。", page=1),
        ],
        toc=[make_toc_entry("第一章", level=1)],
    )

    validate_document(document)


@pytest.mark.parametrize(
    "block_type",
    ["epigraph", "blockquote", "signature", "list", "footnote_ref", "equation", "page_break"],
)
def test_deprecated_block_types_are_rejected(block_type):
    with pytest.raises(ValidationError, match="Unsupported block type"):
        make_block("b000001", block_type, "示例文本。", page=1)

    document = sample_document()
    document["blocks"][0]["type"] = block_type
    with pytest.raises(ValidationError, match="type is invalid"):
        validate_document(document)


def test_toc_entry_validation_requires_title():
    with pytest.raises(ValidationError, match="title"):
        validate_document(
            make_document(
                doc_id="sample",
                title="Sample",
                language="zh-CN",
                source_file="sample.pdf",
                parser_name="sample",
                parser_mode="base",
                blocks=[],
                toc=[{"level": 1}],
            )
        )


def test_read_canonical_migrates_unversioned_document(tmp_path):
    legacy = sample_document()
    legacy["metadata"].pop("schema_version")
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = read_canonical(path)

    assert migrated["metadata"]["schema_version"] == "1.0"
    assert "schema_version" not in legacy["metadata"]


def test_read_canonical_rejects_unknown_schema_version(tmp_path):
    document = sample_document()
    document["metadata"]["schema_version"] = "99.0"
    path = tmp_path / "future.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(MigrationError, match=re.escape("99.0")):
        read_canonical(path)
