from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from inkline.canonical.io import write_jsonl
from inkline.canonical.source_map import bbox_ref

TEXT_TYPES = {
    "paragraph",
    "display_block",
    "list_item",
    "caption",
    "footnote",
}


def export_chunks(document: dict[str, Any], output_path: str | Path) -> int:
    return write_jsonl(output_path, build_chunks(document))


def build_chunks(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    metadata = document["metadata"]
    heading_path: list[str] = []
    buffer: list[dict[str, Any]] = []
    chunk_no = 1

    for block in document["blocks"]:
        block_type = block["type"]
        if block_type == "heading":
            if buffer:
                yield _make_text_chunk(metadata, chunk_no, heading_path, buffer)
                chunk_no += 1
                buffer = []
            level = int(block.get("level", 1))
            heading_path = heading_path[: max(level - 1, 0)]
            heading_path.append(block["text"])
            continue

        if block_type == "table":
            if buffer:
                yield _make_text_chunk(metadata, chunk_no, heading_path, buffer)
                chunk_no += 1
                buffer = []
            yield _make_table_chunk(metadata, chunk_no, heading_path, block)
            chunk_no += 1
            continue

        if block_type in TEXT_TYPES and block.get("text"):
            buffer.append(block)

    if buffer:
        yield _make_text_chunk(metadata, chunk_no, heading_path, buffer)


def _make_text_chunk(
    metadata: dict[str, Any],
    chunk_no: int,
    heading_path: list[str],
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    pages = [
        block.get("source", {}).get("page")
        for block in blocks
        if block.get("source", {}).get("page")
    ]
    bbox_refs = [ref for block in blocks if (ref := bbox_ref(block))]
    text = "\n\n".join(block["text"] for block in blocks if block.get("text"))
    return {
        "chunk_id": _chunk_id(metadata, chunk_no),
        "doc_id": metadata["doc_id"],
        "book_id": metadata["doc_id"],
        "title": metadata.get("title") or metadata["doc_id"],
        "author": metadata.get("author"),
        "language": metadata.get("language"),
        "source_path": metadata.get("source_file"),
        "parser": metadata["parser_name"],
        "parser_mode": metadata["parser_mode"],
        "chunk_type": "text",
        "chunk_strategy": "canonical_heading_path",
        "text": text,
        "heading_path": list(heading_path),
        "chapter_title": heading_path[-1]
        if heading_path
        else metadata.get("title") or metadata["doc_id"],
        "page_start": min(pages) if pages else None,
        "page_end": max(pages) if pages else None,
        "block_ids": [block["block_id"] for block in blocks],
        "bbox_refs": bbox_refs,
        "token_count": _estimate_tokens(text),
    }


def _make_table_chunk(
    metadata: dict[str, Any],
    chunk_no: int,
    heading_path: list[str],
    block: dict[str, Any],
) -> dict[str, Any]:
    ref = bbox_ref(block)
    page = block.get("source", {}).get("page")
    text = block.get("text", "")
    return {
        "chunk_id": _chunk_id(metadata, chunk_no),
        "doc_id": metadata["doc_id"],
        "book_id": metadata["doc_id"],
        "title": metadata.get("title") or metadata["doc_id"],
        "author": metadata.get("author"),
        "language": metadata.get("language"),
        "source_path": metadata.get("source_file"),
        "parser": metadata["parser_name"],
        "parser_mode": metadata["parser_mode"],
        "chunk_type": "table",
        "chunk_strategy": "canonical_heading_path",
        "text": text,
        "heading_path": list(heading_path),
        "chapter_title": heading_path[-1]
        if heading_path
        else metadata.get("title") or metadata["doc_id"],
        "page_start": page,
        "page_end": page,
        "block_ids": [block["block_id"]],
        "bbox_refs": [ref] if ref else [],
        "token_count": _estimate_tokens(text),
    }


def _chunk_id(metadata: dict[str, Any], chunk_no: int) -> str:
    return f"{metadata['doc_id']}-{metadata['parser_name']}-{chunk_no:06d}"


def _estimate_tokens(text: str) -> int:
    # Cheap mixed Chinese/Latin estimate suitable for batching and smoke checks.
    return max(1, len(text.strip()) // 2) if text.strip() else 0
