import json

import pytest

from inkline.canonical import MigrationError, ValidationError, make_block, make_document, make_toc_entry, sample_document, validate_document
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


def test_epigraph_blockquote_and_signature_blocks_validate():
    document = make_document(
        doc_id="sample",
        title="Sample",
        language="zh-CN",
        source_file="sample.pdf",
        parser_name="sample",
        parser_mode="base",
        blocks=[
            make_block("b000001", "epigraph", "沉醉夕阳，碧草青川。", page=1),
            make_block("b000002", "blockquote", "凡兵之所起者有五。", page=2),
            make_block("b000003", "signature", "塞缪尔·霍利", page=3),
        ],
        toc=[make_toc_entry("第一章", level=1)],
    )

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

    with pytest.raises(MigrationError, match="99.0"):
        read_canonical(path)
