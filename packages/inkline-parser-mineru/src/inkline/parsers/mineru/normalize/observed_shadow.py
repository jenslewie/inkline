from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.observed import (
    make_observation,
    make_observed_document,
    make_observed_page,
)

from ..schema.models import NoteRef, RawBlock


def build_observed_document_shadow(
    *,
    pages: dict[int, list[RawBlock]],
    page_sizes: dict[int, tuple[float, float]],
    metadata: dict[str, Any],
    assets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed_pages = [
        make_observed_page(page, width=size[0], height=size[1])
        for page, size in sorted(page_sizes.items())
    ]
    observations: list[dict[str, Any]] = []
    for page in sorted(pages):
        for block in pages[page]:
            observations.append(_observation_from_raw_block(block, len(observations) + 1))
    return make_observed_document(
        _observed_metadata(metadata),
        observed_pages,
        observations,
        assets=assets,
    )


def _observed_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": metadata.get("doc_id") or "",
        "title": metadata.get("title") or "",
        "language": metadata.get("language") or "",
        "source_file": metadata.get("source_file") or "",
        "parser_name": metadata.get("parser_name") or "mineru",
        "parser_mode": metadata.get("parser_mode") or "",
    }


def _observation_from_raw_block(block: RawBlock, index: int) -> dict[str, Any]:
    return make_observation(
        f"obs{index:06d}",
        _kind(block.raw_type),
        text=block.text or "",
        page=block.page,
        bbox=deepcopy(block.bbox),
        spans=_spans(block),
        role_hint=_role_hint(block.raw_type),
        attrs=_attrs(block),
        parser_payload={"raw_type": block.raw_type, "raw": deepcopy(block.raw)},
    )


def _kind(raw_type: str) -> str:
    if raw_type in {"image", "chart"}:
        return "image_region"
    if raw_type == "table":
        return "table_region"
    if raw_type in {"page_number", "page_header", "page_footer"}:
        return "page_marker"
    if raw_type in {"page_footnote", "ref_text"}:
        return "footnote_region"
    return "text_region"


def _role_hint(raw_type: str) -> str:
    return {
        "paragraph": "body_text",
        "title": "title_text",
        "list": "list_text",
        "page_footnote": "footnote_text",
        "ref_text": "footnote_text",
        "caption": "caption_text",
        "toc": "toc_text",
        "page_number": "page_number",
        "page_header": "header",
        "page_footer": "footer",
    }.get(raw_type, "unknown")


def _attrs(block: RawBlock) -> dict[str, Any]:
    attrs: dict[str, Any] = {"reading_order": block.index}
    if block.inline_runs:
        attrs["inline_runs"] = deepcopy(block.inline_runs)
    if block.note_refs:
        attrs["note_refs"] = [_note_ref_dict(note_ref) for note_ref in block.note_refs]
    return attrs


def _note_ref_dict(note_ref: NoteRef) -> dict[str, str]:
    return {
        "marker": note_ref.marker,
        "source": note_ref.source,
        "raw_marker": note_ref.raw_marker,
    }


def _spans(block: RawBlock) -> list[dict[str, Any]]:
    if block.bbox is None:
        return []
    return [{"page": block.page, "bbox": deepcopy(block.bbox), "raw_index": block.index}]
