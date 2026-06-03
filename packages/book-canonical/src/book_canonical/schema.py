from __future__ import annotations

from dataclasses import dataclass
from typing import Any


BLOCK_TYPES = {
    "heading",
    "paragraph",
    "epigraph",
    "blockquote",
    "signature",
    "list",
    "table",
    "figure",
    "caption",
    "footnote_ref",
    "footnote",
    "equation",
    "page_break",
}


class ValidationError(ValueError):
    """Raised when a CanonicalDocument does not match the minimal contract."""


@dataclass(frozen=True)
class RequiredField:
    path: str
    expected_type: type


REQUIRED_DOCUMENT_FIELDS = (
    RequiredField("metadata", dict),
    RequiredField("blocks", list),
    RequiredField("toc", list),
    RequiredField("assets", dict),
    RequiredField("source_map", list),
)

REQUIRED_METADATA_FIELDS = (
    "doc_id",
    "title",
    "language",
    "source_file",
    "parser_name",
    "parser_mode",
)


def make_block(
    block_id: str,
    block_type: str,
    text: str = "",
    *,
    level: int | None = None,
    page: int | None = None,
    bbox: list[float] | None = None,
    children: list[dict[str, Any]] | None = None,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if block_type not in BLOCK_TYPES:
        raise ValidationError(f"Unsupported block type: {block_type}")

    block: dict[str, Any] = {
        "block_id": block_id,
        "type": block_type,
        "text": text,
        "source": {"page": page, "bbox": bbox},
        "attrs": attrs or {},
    }
    if level is not None:
        block["level"] = level
    if children is not None:
        block["children"] = children
    return block


def make_toc_entry(
    title: str,
    level: int = 1,
    *,
    page_hint: str | None = None,
    block_id: str | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"title": title, "level": level}
    if page_hint is not None:
        entry["page_hint"] = page_hint
    if block_id is not None:
        entry["block_id"] = block_id
    if children is not None:
        entry["children"] = children
    return entry


def make_document(
    *,
    doc_id: str,
    title: str,
    language: str,
    source_file: str,
    parser_name: str,
    parser_mode: str,
    blocks: list[dict[str, Any]],
    author: str | None = None,
    assets: dict[str, Any] | None = None,
    toc: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    document = {
        "metadata": {
            "doc_id": doc_id,
            "title": title,
            "author": author,
            "language": language,
            "source_file": source_file,
            "parser_name": parser_name,
            "parser_mode": parser_mode,
        },
        "blocks": blocks,
        "toc": toc or [],
        "assets": assets or {"images": []},
        "source_map": [
            {
                "block_id": block["block_id"],
                "page": block.get("source", {}).get("page"),
                "bbox": block.get("source", {}).get("bbox"),
                "parser_raw_id": block.get("attrs", {}).get("parser_raw_id"),
            }
            for block in blocks
        ],
    }
    validate_document(document)
    return document


def validate_document(document: dict[str, Any]) -> None:
    for field in REQUIRED_DOCUMENT_FIELDS:
        value = document.get(field.path)
        if not isinstance(value, field.expected_type):
            raise ValidationError(f"{field.path} must be {field.expected_type.__name__}")

    metadata = document["metadata"]
    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata:
            raise ValidationError(f"metadata.{field} is required")

    block_ids: set[str] = set()
    for index, block in enumerate(document["blocks"]):
        _validate_block(block, index)
        block_id = block["block_id"]
        if block_id in block_ids:
            raise ValidationError(f"duplicate block_id: {block_id}")
        block_ids.add(block_id)

    toc = document.get("toc", [])
    if not isinstance(toc, list):
        raise ValidationError("toc must be a list")
    for index, entry in enumerate(toc):
        _validate_toc_entry(entry, index)

    images = document["assets"].get("images", [])
    if not isinstance(images, list):
        raise ValidationError("assets.images must be a list")


def _validate_block(block: dict[str, Any], index: int) -> None:
    if not isinstance(block, dict):
        raise ValidationError(f"blocks[{index}] must be object")
    if not block.get("block_id"):
        raise ValidationError(f"blocks[{index}].block_id is required")
    if block.get("type") not in BLOCK_TYPES:
        raise ValidationError(f"blocks[{index}].type is invalid: {block.get('type')}")
    if "text" not in block:
        raise ValidationError(f"blocks[{index}].text is required")
    if not isinstance(block.get("source", {}), dict):
        raise ValidationError(f"blocks[{index}].source must be object")
    if not isinstance(block.get("attrs", {}), dict):
        raise ValidationError(f"blocks[{index}].attrs must be object")


def _validate_toc_entry(entry: dict[str, Any], index: int) -> None:
    if not isinstance(entry, dict):
        raise ValidationError(f"toc[{index}] must be object")
    if not entry.get("title"):
        raise ValidationError(f"toc[{index}].title is required")
    if not isinstance(entry.get("level", 1), int):
        raise ValidationError(f"toc[{index}].level must be int")
    children = entry.get("children", [])
    if not isinstance(children, list):
        raise ValidationError(f"toc[{index}].children must be a list")
    for child_index, child in enumerate(children):
        _validate_toc_entry(child, child_index)


def sample_document() -> dict[str, Any]:
    return make_document(
        doc_id="sample",
        title="Sample",
        language="zh-CN",
        source_file="sample.pdf",
        parser_name="sample",
        parser_mode="base",
        blocks=[
            make_block("b000001", "heading", "第一章", level=1, page=1),
            make_block("b000002", "paragraph", "这是一个最小 CanonicalDocument 样例。", page=1),
        ],
        toc=[make_toc_entry("第一章", level=1, page_hint="1")],
    )
