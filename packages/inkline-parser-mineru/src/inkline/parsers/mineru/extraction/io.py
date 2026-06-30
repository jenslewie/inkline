"""I/O utilities for MinerU source data. Loads content_list_v2, content_list, middle.json, and model JSON files. Flattens nested content structures into page-level block lists."""

from __future__ import annotations

import json
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..schema.models import NoteRef, RawBlock
from ..schema.patterns import NOTE_MARKER_RE
from .text import extract_text_notes_and_runs, normalize_note_marker, normalize_ws

_CONTENT_COORD_SIZE = 1000.0
_COORD_SPACE_TOLERANCE = 0.15
_RENDERED_WIDTH_THRESHOLD = 650.0
_RENDERED_HEIGHT_THRESHOLD = 750.0


def load_json(path: Optional[str]) -> Any:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def page_sizes_from_middle(middle: Any) -> Dict[int, Tuple[float, float]]:
    sizes: Dict[int, Tuple[float, float]] = {}
    if isinstance(middle, dict) and isinstance(middle.get("pdf_info"), list):
        for i, p in enumerate(middle["pdf_info"], 1):
            ps = p.get("page_size") or []
            if len(ps) >= 2:
                sizes[i] = (float(ps[0]), float(ps[1]))
    return sizes


def load_inputs(args: Any) -> tuple[Dict[int, List[RawBlock]], Dict[int, Tuple[float, float]]]:
    """Load MinerU JSON inputs from the normalization CLI arguments."""

    middle = load_json(getattr(args, "middle", None))
    page_sizes = page_sizes_from_middle(middle)
    content_list_v2 = load_json(getattr(args, "content_list_v2", None))
    if content_list_v2 is not None:
        if not isinstance(content_list_v2, list):
            raise ValueError("content_list_v2 must be a list of page item lists")
        pages = flatten_content_list_v2(content_list_v2)
        content_page_sizes = infer_content_page_sizes(pages, page_sizes)
        return (
            replace_footnote_sources_from_middle(
                pages,
                middle,
                page_sizes,
                content_page_sizes=content_page_sizes,
            ),
            content_page_sizes,
        )

    content_list = load_json(getattr(args, "content_list", None))
    if content_list is not None:
        if not isinstance(content_list, list):
            raise ValueError("content_list must be a list")
        pages = flatten_content_list_legacy(content_list)
        content_page_sizes = infer_content_page_sizes(pages, page_sizes)
        return (
            replace_footnote_sources_from_middle(
                pages,
                middle,
                page_sizes,
                content_page_sizes=content_page_sizes,
            ),
            content_page_sizes,
        )

    raise ValueError("Either content_list_v2 or content_list is required")


def flatten_content_list_v2(content_list_v2: List[Any]) -> Dict[int, List[RawBlock]]:
    pages: Dict[int, List[RawBlock]] = {}
    for p_idx, page_items in enumerate(content_list_v2, 1):
        pages[p_idx] = []
        if not isinstance(page_items, list):
            continue
        for i, item in enumerate(page_items):
            if not isinstance(item, dict):
                continue
            typ = item.get("type", "unknown")
            text = ""
            notes: List[NoteRef] = []
            inline_runs: List[Dict[str, Any]] = []
            if typ == "list":
                # Keep list as a block; list items are expanded later when needed.
                text, notes, inline_runs = extract_text_notes_and_runs(item.get("content", {}))
            elif typ in {"image", "table"}:
                # Image/table text is handled from typed fields, not via full recursion.
                text = ""
            else:
                text, notes, inline_runs = extract_text_notes_and_runs(item.get("content", {}))
            bbox = item.get("bbox")
            pages[p_idx].append(
                RawBlock(
                    page=p_idx,
                    index=i,
                    raw_type=typ,
                    text=text,
                    bbox=bbox,
                    raw=item,
                    note_refs=notes,
                    inline_runs=inline_runs,
                )
            )
    return pages


def flatten_content_list_legacy(content_list: List[Any]) -> Dict[int, List[RawBlock]]:
    pages: Dict[int, List[RawBlock]] = {}
    for _i, item in enumerate(content_list):
        if not isinstance(item, dict):
            continue
        p = int(item.get("page_idx", 0)) + 1
        pages.setdefault(p, [])
        typ = item.get("type", "unknown")
        text = normalize_ws(str(item.get("text", "")))
        pages[p].append(
            RawBlock(
                page=p,
                index=len(pages[p]),
                raw_type=typ,
                text=text,
                bbox=item.get("bbox"),
                raw=item,
                note_refs=[],
            )
        )
    return pages


def replace_footnote_sources_from_middle(
    pages: Dict[int, List[RawBlock]],
    middle: Any,
    page_sizes: Dict[int, Tuple[float, float]],
    content_page_sizes: Optional[Dict[int, Tuple[float, float]]] = None,
) -> Dict[int, List[RawBlock]]:
    """Use middle.json as the authoritative source for page-footnote blocks."""

    if not isinstance(middle, dict) or not isinstance(middle.get("pdf_info"), list):
        return pages

    middle_footnotes = footnote_blocks_from_middle(
        middle,
        page_sizes,
        content_page_sizes=content_page_sizes,
    )
    out: Dict[int, List[RawBlock]] = {}
    all_pages = set(pages) | set(middle_footnotes)
    for page in sorted(all_pages):
        body_blocks = [
            block for block in pages.get(page, []) if not _is_content_list_footnote_source(block)
        ]
        body_blocks.extend(middle_footnotes.get(page, []))
        body_blocks.sort(key=_raw_block_reading_key)
        out[page] = body_blocks
    return out


def footnote_blocks_from_middle(
    middle: Any,
    page_sizes: Dict[int, Tuple[float, float]],
    content_page_sizes: Optional[Dict[int, Tuple[float, float]]] = None,
) -> Dict[int, List[RawBlock]]:
    """Collect discarded page_footnote and para ref_text blocks from middle.json."""

    out: Dict[int, List[RawBlock]] = {}
    if not isinstance(middle, dict) or not isinstance(middle.get("pdf_info"), list):
        return out

    for fallback_page, page_info in enumerate(middle["pdf_info"], 1):
        if not isinstance(page_info, dict):
            continue
        raw_page_idx = page_info.get("page_idx")
        page = int(raw_page_idx) + 1 if isinstance(raw_page_idx, int) else fallback_page
        page_size = page_sizes.get(page)
        content_page_size = (content_page_sizes or {}).get(page)
        page_markers = inline_note_markers_from_middle_page(page_info)
        definitions: List[Dict[str, Any]] = []

        for block in page_info.get("discarded_blocks") or []:
            if isinstance(block, dict) and block.get("type") == "page_footnote":
                definitions.append(block)

        for block in page_info.get("para_blocks") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "ref_text":
                definitions.append(block)
                continue
            if block.get("type") == "list" and block.get("sub_type") == "ref_text":
                definitions.extend(
                    child
                    for child in block.get("blocks") or []
                    if isinstance(child, dict) and child.get("type") == "ref_text"
                )

        page_blocks: List[RawBlock] = []
        for fallback_index, block in enumerate(definitions):
            text = _middle_block_text(block)
            if not text:
                continue
            raw = dict(block)
            raw["_middle_page_inline_markers"] = page_markers
            raw_index = block.get("index")
            index = int(raw_index) if isinstance(raw_index, int) else fallback_index
            page_blocks.append(
                RawBlock(
                    page=page,
                    index=index,
                    raw_type=str(block.get("type") or "page_footnote"),
                    text=text,
                    bbox=_middle_bbox_to_content_bbox(
                        block.get("bbox"),
                        page_size,
                        content_page_size=content_page_size,
                    ),
                    raw=raw,
                )
            )
        if page_blocks:
            page_blocks.sort(key=_raw_block_reading_key)
            out[page] = page_blocks
    return out


def inline_note_markers_from_middle_page(page_info: Dict[str, Any]) -> List[str]:
    """Return note-like inline-equation markers in MinerU para-block order."""

    markers: List[str] = []
    for item in _walk_dicts(page_info.get("para_blocks") or []):
        if item.get("type") not in {"inline_equation", "equation_inline"}:
            continue
        marker = normalize_note_marker(item.get("content", "")).replace("＊", "*")
        if marker and NOTE_MARKER_RE.fullmatch(marker):
            markers.append(marker)
    return markers


def _walk_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _middle_block_text(block: Dict[str, Any]) -> str:
    lines: List[str] = []
    for line in block.get("lines") or []:
        if not isinstance(line, dict):
            continue
        parts: List[str] = []
        for span in line.get("spans") or []:
            if not isinstance(span, dict):
                continue
            content = str(span.get("content") or "")
            if span.get("type") in {"inline_equation", "equation_inline"}:
                marker = normalize_note_marker(content).replace("＊", "*")
                parts.append(marker if NOTE_MARKER_RE.fullmatch(marker) else content)
            else:
                parts.append(content)
        text = normalize_ws("".join(parts))
        if text:
            lines.append(text)
    return "\n".join(lines)


def _middle_bbox_to_content_bbox(
    bbox: Any,
    page_size: Optional[Tuple[float, float]],
    content_page_size: Optional[Tuple[float, float]] = None,
) -> Optional[List[float]]:
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    if not page_size or page_size[0] <= 0 or page_size[1] <= 0:
        return [float(value) for value in bbox[:4]]
    content_width, content_height = content_page_size or (_CONTENT_COORD_SIZE, _CONTENT_COORD_SIZE)
    x_scale = content_width / page_size[0]
    y_scale = content_height / page_size[1]
    return [
        round(float(bbox[0]) * x_scale, 3),
        round(float(bbox[1]) * y_scale, 3),
        round(float(bbox[2]) * x_scale, 3),
        round(float(bbox[3]) * y_scale, 3),
    ]


def infer_content_page_sizes(
    pages: Dict[int, List[RawBlock]],
    pdf_page_sizes: Dict[int, Tuple[float, float]],
) -> Dict[int, Tuple[float, float]]:
    """Return page sizes in the same coordinate space as content-list bboxes."""

    if not pages:
        return dict(pdf_page_sizes)
    all_pages = set(pages) | set(pdf_page_sizes)
    if _looks_like_normalized_content_space(pages, pdf_page_sizes):
        return dict.fromkeys(sorted(all_pages), (_CONTENT_COORD_SIZE, _CONTENT_COORD_SIZE))
    return {
        page: pdf_page_sizes.get(page) or _page_size_from_content_blocks(pages.get(page, []))
        for page in sorted(all_pages)
    }


def _looks_like_normalized_content_space(
    pages: Dict[int, List[RawBlock]],
    pdf_page_sizes: Dict[int, Tuple[float, float]],
) -> bool:
    samples: List[Tuple[float, float, float, float]] = []
    for page, blocks in pages.items():
        pdf_size = pdf_page_sizes.get(page)
        if not pdf_size:
            continue
        max_x, max_y = _page_content_maxima(blocks)
        if max_x <= 0 or max_y <= 0:
            continue
        samples.append((max_x, max_y, pdf_size[0], pdf_size[1]))
    if not samples:
        return False

    max_x = median([sample[0] for sample in samples])
    max_y = median([sample[1] for sample in samples])
    pdf_width = median([sample[2] for sample in samples])
    pdf_height = median([sample[3] for sample in samples])
    content_fits_rendered_space = max_x <= _CONTENT_COORD_SIZE * (
        1.0 + _COORD_SPACE_TOLERANCE
    ) and max_y <= _CONTENT_COORD_SIZE * (1.0 + _COORD_SPACE_TOLERANCE)
    content_uses_rendered_scale = (
        max_x >= _RENDERED_WIDTH_THRESHOLD or max_y >= _RENDERED_HEIGHT_THRESHOLD
    )
    content_exceeds_pdf_space = max_x > pdf_width * (
        1.0 + _COORD_SPACE_TOLERANCE
    ) or max_y > pdf_height * (1.0 + _COORD_SPACE_TOLERANCE)
    pdf_larger_than_rendered_space = pdf_width > _CONTENT_COORD_SIZE * (
        1.0 + _COORD_SPACE_TOLERANCE
    ) or pdf_height > _CONTENT_COORD_SIZE * (1.0 + _COORD_SPACE_TOLERANCE)
    return (
        content_fits_rendered_space
        and content_uses_rendered_scale
        and (content_exceeds_pdf_space or pdf_larger_than_rendered_space)
    )


def _page_size_from_content_blocks(blocks: List[RawBlock]) -> Tuple[float, float]:
    max_x, max_y = _page_content_maxima(blocks)
    if max_x > _RENDERED_WIDTH_THRESHOLD or max_y > _RENDERED_HEIGHT_THRESHOLD:
        return (_CONTENT_COORD_SIZE, _CONTENT_COORD_SIZE)
    return (max(max_x, 1.0), max(max_y, 1.0))


def _page_content_maxima(blocks: List[RawBlock]) -> Tuple[float, float]:
    max_x = max((float(block.x1) for block in blocks if block.bbox), default=0.0)
    max_y = max((float(block.y1) for block in blocks if block.bbox), default=0.0)
    return max_x, max_y


def _is_content_list_footnote_source(block: RawBlock) -> bool:
    if block.raw_type in {"page_footnote", "ref_text"}:
        return True
    if block.raw_type != "list":
        return False
    content = block.raw.get("content") or {}
    return isinstance(content, dict) and content.get("list_type") == "reference_list"


def _raw_block_reading_key(block: RawBlock) -> Tuple[float, float, int]:
    return (block.y0, block.x0, block.index)
