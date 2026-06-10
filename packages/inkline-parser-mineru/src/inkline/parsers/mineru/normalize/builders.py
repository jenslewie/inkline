"""Canonical block factory functions. Provides make_heading, make_paragraph, make_quote_block, make_figure, make_table, make_toc_item, make_flush_right_terminal_block, and union_bbox. All canonical blocks are created through these factories to ensure consistent shape."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..schema.models import BBox, IdFactory, NoteRef, RawBlock, canonical_block
from ..schema.patterns import TOC_LINE_RE
from ..extraction.text import block_text, extract_caption_list, merge_inline_runs, merge_note_refs, normalize_toc_number, normalize_ws, strip_trailing_text_note

def _build_display_attrs(
    raw_lines: List[str],
    blocks: Sequence[RawBlock],
    role: str,
) -> Tuple[Dict[str, Any], List[str]]:
    inline_runs = merge_inline_runs(blocks)
    attrs = {
        "role": role,
        "quote_text": "\n".join(raw_lines).strip(),
        "note_refs": merge_note_refs(blocks),
        "raw_types": [b.raw_type for b in blocks],
    }
    if any(run.get("type") == "note_ref" for run in inline_runs):
        attrs["inline_runs"] = inline_runs
    line_layouts = _line_layouts_for_display_blocks(blocks)
    if line_layouts:
        attrs["line_layouts"] = line_layouts
    return attrs, raw_lines


def _line_layouts_for_display_blocks(blocks: Sequence[RawBlock]) -> List[Dict[str, Any]]:
    """Record non-default line layout inside a display block.

    The signal is deliberately geometric: a short raw line whose right edge is
    close to the display block's right edge is a right-aligned line. This keeps
    reflow targets from losing layout without reintroducing semantic labels such
    as "signature".
    """
    text_blocks = [b for b in blocks if block_text(b) and b.bbox]
    if len(text_blocks) < 2:
        return []
    if len(text_blocks) > 6:
        return []
    box = union_bbox([b.bbox for b in text_blocks])
    if not box:
        return []
    x0, _y0, x1, _y1 = [float(v) for v in box]
    width = max(1.0, x1 - x0)
    layouts: List[Dict[str, Any]] = []
    for line_index, b in enumerate(text_blocks):
        line_width = max(1.0, float(b.x1) - float(b.x0))
        short_line = line_width <= width * 0.35
        near_right_edge = abs(float(b.x1) - x1) <= max(36.0, width * 0.06)
        right_lane = float(b.x0) >= x0 + width * 0.55
        if short_line and near_right_edge and right_lane:
            layouts.append({
                "line_index": line_index,
                "alignment": "right",
            })
    return layouts


def make_quote_block(
    ids: IdFactory,
    blocks: Sequence[RawBlock],
    block_type: str,
    role: str,
    prev_text: str,
    level: Optional[int] = None,
) -> Dict[str, Any]:
    raw_lines = [block_text(b) for b in blocks if block_text(b)]
    attrs, quote_lines = _build_display_attrs(raw_lines, blocks, role)
    text = "\n".join(raw_lines).strip()
    page = blocks[0].page if blocks else None
    bbox = union_bbox([b.bbox for b in blocks if b.bbox])
    return canonical_block(ids.next(), block_type, text, page, bbox, attrs=attrs, level=level, source_pages=_unique_pages(blocks))


def make_epigraph_group(ids: IdFactory, groups: List[List[RawBlock]]) -> Dict[str, Any]:
    items = []
    all_blocks: List[RawBlock] = []
    for g in groups:
        all_blocks.extend(g)
        raw_lines = [block_text(b) for b in g if block_text(b)]
        inline_runs = merge_inline_runs(g)
        item = {
            "text": "\n".join(raw_lines),
            "quote_text": "\n".join(raw_lines),
            "note_refs": merge_note_refs(g),
            "source": {"page": g[0].page, "bbox": union_bbox([b.bbox for b in g if b.bbox])},
        }
        if any(run.get("type") == "note_ref" for run in inline_runs):
            item["inline_runs"] = inline_runs
        items.append(item)
    text = "\n\n".join(i["text"] for i in items)
    attrs = {"role": "section_epigraphs", "items": items}
    return canonical_block(ids.next(), "epigraph_group", text, all_blocks[0].page, union_bbox([b.bbox for b in all_blocks if b.bbox]), attrs=attrs, source_pages=_unique_pages(all_blocks))


def union_bbox(bboxes: Sequence[Optional[BBox]]) -> Optional[BBox]:
    vals = [b for b in bboxes if b and len(b) >= 4]
    if not vals:
        return None
    return [min(b[0] for b in vals), min(b[1] for b in vals), max(b[2] for b in vals), max(b[3] for b in vals)]


def _unique_pages(blocks: Sequence[RawBlock]) -> List[int]:
    return sorted({b.page for b in blocks})


def make_paragraph(ids: IdFactory, b: RawBlock, block_type: str = "paragraph", extra_attrs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    text, extra = strip_trailing_text_note(b.text)
    refs = b.note_refs + extra
    attrs = {"raw_type": b.raw_type}
    inline_runs = merge_inline_runs([b], separator="")
    if refs:
        attrs["note_refs"] = [_note_ref_dict(r, b.page) for r in refs]
    if any(run.get("type") == "note_ref" for run in inline_runs):
        attrs["inline_runs"] = inline_runs
    if extra_attrs:
        attrs.update(extra_attrs)
    return canonical_block(ids.next(), block_type, text, b.page, b.bbox, attrs=attrs)


def _note_ref_dict(ref: NoteRef, page: int) -> Dict[str, Any]:
    out = {"marker": ref.marker, "source": ref.source, "source_page": page}
    if ref.raw_marker:
        out["raw_marker"] = ref.raw_marker
    return out


def make_flush_right_terminal_block(ids: IdFactory, blocks: Sequence[RawBlock]) -> Dict[str, Any]:
    lines = [block_text(b) for b in blocks if block_text(b)]
    text = "\n".join(lines)
    attrs = {
        "layout_role": "flush_right_terminal_block",
        "alignment": "right",
        "line_count": len(lines),
        "raw_types": [b.raw_type for b in blocks],
        "style_hints": {"text_align": "right"},
    }
    return canonical_block(
        ids.next(),
        "display_block",
        text,
        blocks[0].page,
        union_bbox([b.bbox for b in blocks]),
        attrs=attrs,
        source_pages=_unique_pages(blocks),
    )


def make_heading(ids: IdFactory, blocks: Sequence[RawBlock], level: int, role: Optional[str] = None) -> Dict[str, Any]:
    parts = [block_text(b) for b in blocks if block_text(b)]
    raw_text = "\n".join(parts).strip()
    norm_text = normalize_toc_number(raw_text)
    raw_types = [b.raw_type for b in blocks]
    if "title" in raw_types:
        raw_type = "title"
    elif len(set(raw_types)) == 1:
        raw_type = raw_types[0]
    else:
        raw_type = "mixed"
    attrs = {"raw_type": raw_type, "raw_text": raw_text}
    if raw_type == "mixed":
        attrs["raw_types"] = raw_types
    if role:
        attrs["role"] = role
    return canonical_block(ids.next(), "heading", norm_text, blocks[0].page, union_bbox([b.bbox for b in blocks]), attrs=attrs, level=level, source_pages=_unique_pages(blocks))


def make_toc_item(ids: IdFactory, b: RawBlock, text: Optional[str] = None, level: int = 1) -> Dict[str, Any]:
    t = normalize_toc_number(text if text is not None else block_text(b))
    m = TOC_LINE_RE.match(t)
    attrs: Dict[str, Any] = {"role": "toc_entry"}
    display_text = t
    if m:
        display_text = normalize_toc_number(m.group("title")).strip()
        attrs["title"] = display_text
        attrs["target_page_label"] = m.group("page")
    return canonical_block(ids.next(), "toc_item", display_text, b.page, b.bbox, attrs=attrs, level=level)


def make_figure(ids: IdFactory, b: RawBlock) -> Dict[str, Any]:
    content = b.raw.get("content", {})
    source = content.get("image_source", {}) if isinstance(content, dict) else {}
    image_path = source.get("path")
    ocr_text = content.get("content") if isinstance(content, dict) else None
    captions = extract_caption_list(content.get("image_caption", [])) if isinstance(content, dict) else []
    footnotes = extract_caption_list(content.get("image_footnote", [])) if isinstance(content, dict) else []
    attrs = {
        "image_path": image_path,
        "sub_type": b.raw.get("sub_type"),
        "ocr_text_in_image": normalize_ws(ocr_text or ""),
        "captions": captions,
        "footnotes": footnotes,
    }
    return canonical_block(ids.next(), "figure", "", b.page, b.bbox, attrs=attrs)


def make_full_page_figure(ids: IdFactory, image: RawBlock, absorbed_blocks: Sequence[RawBlock]) -> Dict[str, Any]:
    fig = make_figure(ids, image)
    all_blocks = [image, *absorbed_blocks]
    fig["source"]["bbox"] = union_bbox([b.bbox for b in all_blocks])
    fig["source"]["pages"] = _unique_pages(all_blocks)
    attrs = fig.setdefault("attrs", {})
    attrs["layout_role"] = "full_page_image"
    attrs["mineru_split_repaired"] = True
    attrs["absorbed_block_count"] = len(absorbed_blocks)
    attrs["absorbed_raw_types"] = [b.raw_type for b in absorbed_blocks]
    return fig


def make_page_snapshot_figure(ids: IdFactory, page: int, blocks: Sequence[RawBlock], role: str) -> Dict[str, Any]:
    text_blocks = [b for b in blocks if block_text(b)]
    attrs = {
        "image_path": None,
        "sub_type": "page_snapshot",
        "ocr_text_in_image": normalize_ws("\n".join(block_text(b) for b in text_blocks)),
        "captions": [],
        "footnotes": [],
        "layout_role": "full_page_image",
        "snapshot_role": role,
        "mineru_split_repaired": True,
        "absorbed_block_count": len(blocks),
        "absorbed_raw_types": [b.raw_type for b in blocks],
    }
    if role == "visual_label_page":
        attrs["absorbed_block_ids"] = [f"raw:{b.page}:{b.index}" for b in blocks]
        attrs["absorbed_text"] = [block_text(b) for b in text_blocks]
    return canonical_block(
        ids.next(),
        "figure",
        "",
        page,
        union_bbox([b.bbox for b in blocks if b.bbox]),
        attrs=attrs,
        source_pages=_unique_pages(blocks),
    )


def make_table(ids: IdFactory, b: RawBlock) -> Dict[str, Any]:
    content = b.raw.get("content", {})
    html = content.get("html", "") if isinstance(content, dict) else ""
    captions = extract_caption_list(content.get("table_caption", [])) if isinstance(content, dict) else []
    footnotes = extract_caption_list(content.get("table_footnote", [])) if isinstance(content, dict) else []
    caption_text = "\n".join(captions)
    attrs = {
        "html": html,
        "caption": caption_text or None,
        "footnotes": footnotes,
        "table_type": content.get("table_type") if isinstance(content, dict) else None,
        "table_nest_level": content.get("table_nest_level") if isinstance(content, dict) else None,
        "image_path": (content.get("image_source") or {}).get("path") if isinstance(content, dict) else None,
    }
    return canonical_block(ids.next(), "table", caption_text, b.page, b.bbox, attrs=attrs)
