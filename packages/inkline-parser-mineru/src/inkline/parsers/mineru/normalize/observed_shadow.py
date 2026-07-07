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
    middle: Any | None = None,
    source_pdf: str | None = None,
    allow_missing_pdf_text: bool = False,
) -> dict[str, Any]:
    observed_pages = [
        make_observed_page(page, width=size[0], height=size[1])
        for page, size in sorted(page_sizes.items())
    ]
    observations: list[dict[str, Any]] = []
    total_pages = len(page_sizes)
    line_extractor = _line_extractor(
        source_pdf, page_sizes, allow_missing_pdf_text=allow_missing_pdf_text
    )
    try:
        for page in sorted(pages):
            for block in pages[page]:
                observations.append(
                    _observation_from_raw_block(
                        block,
                        len(observations) + 1,
                        total_pages,
                        text_line_metrics=_text_line_metrics(line_extractor, block),
                    )
                )
        observations.extend(
            _middle_title_observations(
                middle,
                start_index=len(observations) + 1,
                existing_observations=observations,
            )
        )
    finally:
        if line_extractor is not None:
            line_extractor.close()
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


def _line_extractor(
    source_pdf: str | None,
    page_sizes: dict[int, tuple[float, float]],
    *,
    allow_missing_pdf_text: bool,
) -> Any | None:
    if not source_pdf:
        return None
    from ..reconcile.cross_page import _PdfLineExtractor

    page_widths = {page: size[0] for page, size in page_sizes.items()}
    page_heights = {page: size[1] for page, size in page_sizes.items()}
    return _PdfLineExtractor(
        source_pdf,
        page_widths,
        page_heights,
        allow_missing_pdf_text=allow_missing_pdf_text,
    )


def _text_line_metrics(line_extractor: Any | None, block: RawBlock) -> dict[str, Any] | None:
    if line_extractor is None or block.raw_type not in {"paragraph", "list", "ref_text"}:
        return None
    metrics = line_extractor.line_metrics_for_block(
        {
            "text": block.text or "",
            "source": {
                "page": block.page,
                "bbox": deepcopy(block.bbox),
                "pages": [block.page],
            },
        }
    )
    return metrics if isinstance(metrics, dict) else None


def _observation_from_raw_block(
    block: RawBlock,
    index: int,
    total_pages: int,
    *,
    text_line_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return make_observation(
        f"obs{index:06d}",
        _kind(block.raw_type),
        text=block.text or "",
        page=block.page,
        bbox=deepcopy(block.bbox),
        spans=_spans(block),
        role_hint=_role_hint(block.raw_type, page=block.page, total_pages=total_pages),
        attrs=_attrs(block, text_line_metrics=text_line_metrics),
        parser_payload={"raw_type": block.raw_type, "raw": deepcopy(block.raw)},
    )


def _kind(raw_type: str) -> str:
    if raw_type in {"image", "chart"}:
        return "image_region"
    if raw_type == "table":
        return "table_region"
    if raw_type in {"page_number", "page_header", "page_footer"}:
        return "page_marker"
    if raw_type == "page_footnote":
        return "footnote_region"
    return "text_region"


def _role_hint(raw_type: str, *, page: int, total_pages: int) -> str:
    if raw_type == "index" and _is_front_edge_page(page, total_pages):
        return "toc_text"
    return {
        "paragraph": "body_text",
        "title": "title_text",
        "list": "list_text",
        "page_footnote": "footnote_text",
        "ref_text": "reference_text",
        "caption": "caption_text",
        "toc": "toc_text",
        "page_number": "page_number",
        "page_header": "header",
        "page_footer": "footer",
    }.get(raw_type, "unknown")


def _is_front_edge_page(page: int, total_pages: int) -> bool:
    return page <= max(20, round(total_pages * 0.05))


def _attrs(block: RawBlock, *, text_line_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    attrs: dict[str, Any] = {"reading_order": block.index}
    if text_line_metrics:
        attrs["text_line_metrics"] = deepcopy(text_line_metrics)
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


def _middle_title_observations(
    middle: Any,
    *,
    start_index: int,
    existing_observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(middle, dict) or not isinstance(middle.get("pdf_info"), list):
        return []
    existing_keys = {
        _observation_dedupe_key(observation) for observation in existing_observations
    }
    existing_title_keys = {
        _title_dedupe_key(observation.get("page"), str(observation.get("text") or ""))
        for observation in existing_observations
        if observation.get("role_hint") == "title_text"
    }
    existing_title_observations = {
        _title_dedupe_key(observation.get("page"), str(observation.get("text") or "")): observation
        for observation in existing_observations
        if observation.get("role_hint") == "title_text"
    }
    observations = []
    next_index = start_index
    for fallback_page, page_info in enumerate(middle["pdf_info"], 1):
        if not isinstance(page_info, dict):
            continue
        raw_page_idx = page_info.get("page_idx")
        page = int(raw_page_idx) + 1 if isinstance(raw_page_idx, int) else fallback_page
        for block_index, block in enumerate(_middle_title_blocks(page_info)):
            text = _middle_block_text(block)
            if not text:
                continue
            bbox = _middle_block_bbox(block)
            key = _dedupe_key(page, text, bbox)
            title_key = _title_dedupe_key(page, text)
            if key in existing_keys or title_key in existing_title_keys:
                _attach_middle_title_source(
                    existing_title_observations.get(title_key),
                    raw_page_idx=raw_page_idx,
                    bbox=bbox,
                    block=block,
                )
                continue
            existing_keys.add(key)
            existing_title_keys.add(title_key)
            observation = make_observation(
                f"obs{next_index:06d}",
                "text_region",
                text=text,
                page=page,
                bbox=deepcopy(bbox),
                spans=_middle_spans(page, bbox, block_index),
                role_hint="title_text",
                attrs={"reading_order": block_index},
                parser_payload={
                    "raw_type": "title",
                    "source": "mineru_middle",
                    "page_idx": raw_page_idx,
                    "raw": deepcopy(block),
                },
            )
            observations.append(observation)
            existing_title_observations[title_key] = observation
            next_index += 1
    return observations


def _middle_title_blocks(page_info: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []
    seen = set()
    for collection_name in ("para_blocks", "preproc_blocks"):
        for block in page_info.get(collection_name) or []:
            if not isinstance(block, dict) or block.get("type") != "title":
                continue
            key = (_middle_block_text(block), tuple(_middle_block_bbox(block) or []))
            if key in seen:
                continue
            seen.add(key)
            blocks.append(block)
    return blocks


def _middle_block_text(block: dict[str, Any]) -> str:
    parts = []
    for line in block.get("lines") or []:
        if not isinstance(line, dict):
            continue
        line_parts = [
            str(span.get("content") or "").strip()
            for span in line.get("spans") or []
            if isinstance(span, dict) and str(span.get("content") or "").strip()
        ]
        if line_parts:
            parts.append("".join(line_parts))
    return "\n".join(parts).strip()


def _middle_block_bbox(block: dict[str, Any]) -> list[Any] | None:
    bbox = block.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        return deepcopy(bbox)
    for line in block.get("lines") or []:
        if not isinstance(line, dict):
            continue
        for span in line.get("spans") or []:
            if isinstance(span, dict):
                span_bbox = span.get("bbox")
                if isinstance(span_bbox, list) and len(span_bbox) == 4:
                    return deepcopy(span_bbox)
    return None


def _middle_spans(
    page: int,
    bbox: list[Any] | None,
    block_index: int,
) -> list[dict[str, Any]]:
    if bbox is None:
        return []
    return [{"page": page, "bbox": deepcopy(bbox), "raw_index": block_index}]


def _observation_dedupe_key(observation: dict[str, Any]) -> tuple[Any, str, tuple[Any, ...] | None]:
    return _dedupe_key(
        observation.get("page"),
        str(observation.get("text") or ""),
        observation.get("bbox"),
    )


def _dedupe_key(page: Any, text: str, bbox: Any) -> tuple[Any, str, tuple[Any, ...] | None]:
    bbox_key = tuple(bbox) if isinstance(bbox, list | tuple) else None
    return (page, text.strip(), bbox_key)


def _title_dedupe_key(page: Any, text: str) -> tuple[Any, str]:
    return (page, text.strip())


def _attach_middle_title_source(
    observation: dict[str, Any] | None,
    *,
    raw_page_idx: Any,
    bbox: list[Any] | None,
    block: dict[str, Any],
) -> None:
    if observation is None:
        return
    parser_payload = observation.setdefault("parser_payload", {})
    parser_payload.setdefault("middle_title_sources", []).append(
        {
            "source": "mineru_middle",
            "page_idx": raw_page_idx,
            "bbox": deepcopy(bbox),
            "raw": deepcopy(block),
        }
    )
