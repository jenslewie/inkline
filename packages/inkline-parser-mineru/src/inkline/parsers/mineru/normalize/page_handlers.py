"""Page classification handlers."""

from __future__ import annotations

from statistics import median
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .builders import (
    make_display_group,
    make_chart_table,
    make_figure,
    make_full_page_figure,
    make_heading,
    make_page_snapshot_figure,
    make_paragraph,
    make_display_block,
    make_toc_item,
    union_bbox,
)
from .normal_flow import _looks_like_note_definition_footer, process_normal_flow
from .page_detectors import dominant_block as _dominant_block, should_snapshot_layout_page
from .raw_display_quotes import _RawTextStyleProvider
from ..analysis.layout import has_attribution_line, is_full_page_image_page, is_title_only_page, page_has_images
from ..schema.models import IdFactory, LayoutStats, RawBlock, canonical_block
from ..schema.patterns import ATTR_RE, CHAPTER_RE, PART_RE, TOC_LINE_RE
from ..extraction.text import block_text, extract_list_item_text, normalize_ws


class _PageResult(NamedTuple):
    blocks: List[Dict[str, Any]]
    prev_major_type: Optional[str]
    in_toc: bool


def group_sparse_display_page(blocks: Sequence[RawBlock], prev_major_type: Optional[str]) -> Optional[List[List[RawBlock]]]:
    if any(b.raw_type in {"image", "chart", "table"} for b in blocks):
        return None
    paras = [b for b in blocks if b.raw_type == "paragraph" and block_text(b)]
    if not paras or not has_attribution_line(paras):
        return None
    groups: List[List[RawBlock]] = []
    buf: List[RawBlock] = []
    for b in paras:
        buf.append(b)
        if ATTR_RE.match(block_text(b)):
            groups.append(buf)
            buf = []
    if buf:
        if prev_major_type in {"part_title", "chapter_title", "heading"}:
            groups.append(buf)
    grouped_count = sum(len(g) for g in groups)
    if groups and (grouped_count == len(paras) or len(groups) * 2 >= len(paras)):
        return groups
    return None


def build_toc_from_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    toc = []
    for b in blocks:
        if b["type"] != "toc_item":
            continue
        attrs = b.get("attrs", {})
        toc.append({
            "title": attrs.get("title", b.get("text")),
            "target_page_label": attrs.get("target_page_label"),
            "level": b.get("level", 1),
            "source_block_id": b.get("block_id"),
        })
    return toc


def _toc_left_edge_clusters(page_blocks: Sequence[RawBlock]) -> List[float]:
    xs: List[float] = []
    for b in page_blocks:
        if b.raw_type not in {"title", "paragraph", "list"}:
            continue
        if not b.bbox:
            continue
        if b.raw_type == "title" and block_text(b) == "目录":
            continue
        if not block_text(b):
            continue
        xs.append(float(b.x0))
    clusters: List[List[float]] = []
    for x in sorted(xs):
        if not clusters or abs(x - median(clusters[-1])) > 12.0:
            clusters.append([x])
        else:
            clusters[-1].append(x)
    return [median(cluster) for cluster in clusters]


def _toc_level_from_indent(block: RawBlock, clusters: Sequence[float]) -> int:
    if not block.bbox or not clusters:
        return 1
    nearest = min(range(len(clusters)), key=lambda i: abs(float(block.x0) - clusters[i]))
    return nearest + 1


def _looks_like_toc_continuation_by_layout(blocks: Sequence[RawBlock], layout: LayoutStats) -> bool:
    text_blocks = [
        b
        for b in blocks
        if b.raw_type in {"title", "paragraph", "list"} and b.bbox and block_text(b)
    ]
    if len(text_blocks) < 6:
        return False
    if any(b.raw_type not in {"title", "paragraph", "list", "page_number"} for b in blocks):
        return False
    clusters = _toc_left_edge_clusters(text_blocks)
    if not clusters or len(clusters) > 3:
        return False
    widths = sorted(float(b.width) for b in text_blocks)
    median_width = median(widths)
    max_width = widths[-1]
    return median_width <= layout.body_width * 0.55 and max_width <= layout.body_width * 0.8


def _process_toc_page(ids: IdFactory, page_blocks: List[RawBlock]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    indent_clusters = _toc_left_edge_clusters(page_blocks)
    for b in page_blocks:
        if b.raw_type == "page_number":
            continue
        if b.raw_type == "title" and block_text(b) == "目录":
            out.append(canonical_block(ids.next(), "heading", "目录", b.page, b.bbox, attrs={"role": "toc_heading"}, level=1))
        elif b.raw_type == "title":
            out.append(make_toc_item(ids, b, level=_toc_level_from_indent(b, indent_clusters)))
        elif b.raw_type == "paragraph":
            out.append(make_toc_item(ids, b, level=_toc_level_from_indent(b, indent_clusters)))
        elif b.raw_type == "list":
            items = b.raw.get("content", {}).get("list_items", [])
            for li in items:
                t, _ = extract_list_item_text(li)
                if t:
                    pseudo = RawBlock(page=b.page, index=b.index, raw_type="list_item", text=t, bbox=b.bbox, raw=li)
                    out.append(make_toc_item(ids, pseudo, text=t, level=_toc_level_from_indent(b, indent_clusters) + 1))
    return out


def _compact_for_duplicate_match(text: str) -> str:
    return "".join(normalize_ws(text or "").split())


def _bbox_mostly_inside(inner: Optional[List[float]], outer: Optional[List[float]], tolerance: float = 6.0) -> bool:
    if not inner or not outer:
        return False
    ix0, iy0, ix1, iy1 = [float(v) for v in inner]
    ox0, oy0, ox1, oy1 = [float(v) for v in outer]
    inner_area = max(1.0, (ix1 - ix0) * (iy1 - iy0))
    overlap_w = max(0.0, min(ix1, ox1 + tolerance) - max(ix0, ox0 - tolerance))
    overlap_h = max(0.0, min(iy1, oy1 + tolerance) - max(iy0, oy0 - tolerance))
    return (overlap_w * overlap_h) >= inner_area * 0.85


def _collect_embedded_image_text_blocks(image: RawBlock, candidates: Sequence[RawBlock]) -> List[RawBlock]:
    content = image.raw.get("content", {})
    ocr_text = content.get("content", "") if isinstance(content, dict) else ""
    compact_ocr = _compact_for_duplicate_match(str(ocr_text))
    if not compact_ocr:
        return []
    absorbed: List[RawBlock] = []
    for candidate in candidates:
        if candidate is image or candidate.raw_type not in {"paragraph", "title"}:
            continue
        text = block_text(candidate)
        compact = _compact_for_duplicate_match(text)
        if not compact:
            continue
        if _bbox_mostly_inside(candidate.bbox, image.bbox) and compact in compact_ocr:
            absorbed.append(candidate)
    return absorbed


def _attach_embedded_image_text_attrs(figure: Dict[str, Any], image: RawBlock, absorbed: Sequence[RawBlock]) -> None:
    if not absorbed:
        return
    attrs = figure.setdefault("attrs", {})
    attrs["embedded_text_absorbed"] = True
    attrs["absorbed_block_count"] = len(absorbed)
    attrs["absorbed_block_ids"] = [f"raw:{b.page}:{b.index}" for b in absorbed]
    attrs["absorbed_raw_types"] = [b.raw_type for b in absorbed]
    attrs["absorbed_text"] = [block_text(b) for b in absorbed]
    source = figure.setdefault("source", {})
    source["bbox"] = union_bbox([image.bbox, *[b.bbox for b in absorbed]])


def _should_process_as_plate_page(blocks: Sequence[RawBlock], layout: LayoutStats, prev_major_type: Optional[str]) -> bool:
    images = [b for b in blocks if b.raw_type == "image" and b.bbox]
    if not images:
        return False
    text_like = [b for b in blocks if b.raw_type in {"paragraph", "title"} and block_text(b)]
    long_text = [b for b in text_like if len(block_text(b)) > 80]
    caption_like_long_text = bool(long_text) and all(b.width <= layout.body_width * 0.65 for b in long_text)
    if len(long_text) >= 2 and not caption_like_long_text:
        return False
    dominant_images = [image for image in images if _dominant_block(image, blocks, layout)]
    embedded_ids = {
        id(text_block)
        for image in dominant_images
        for text_block in _collect_embedded_image_text_blocks(image, blocks)
    }
    if dominant_images and all(id(b) in embedded_ids for b in long_text):
        return True
    if long_text and not caption_like_long_text:
        return False
    if len(blocks) <= 8 and len(text_like) <= 4:
        return True
    if prev_major_type in {"full_page_image", "plate_page"} and len(text_like) <= 8:
        return True
    return False


def _try_process_toc_page(
    ids: IdFactory,
    blocks: List[RawBlock],
    layout: LayoutStats,
    prev_major_type: Optional[str],
    in_toc: bool,
) -> Optional[_PageResult]:
    if any(b.raw_type == "title" and block_text(b) == "目录" for b in blocks):
        return _PageResult(_process_toc_page(ids, blocks), "toc", True)
    if in_toc:
        toc_like_count = 0
        has_list = any(b.raw_type == "list" for b in blocks)
        for b in blocks:
            t = block_text(b)
            if not t:
                continue
            if TOC_LINE_RE.match(t) or b.raw_type == "list":
                toc_like_count += 1
        if has_list or toc_like_count >= 3 or _looks_like_toc_continuation_by_layout(blocks, layout):
            return _PageResult(_process_toc_page(ids, blocks), "toc", True)
    return None


def _try_process_snapshot_page(
    ids: IdFactory,
    blocks: List[RawBlock],
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    prev_major_type: Optional[str],
    in_toc: bool,
) -> Optional[_PageResult]:
    snapshot_page, snapshot_role = should_snapshot_layout_page(blocks, layout)
    if not snapshot_page:
        return None
    if snapshot_role == "page_chart":
        out: List[Dict[str, Any]] = []
        for b in content_blocks:
            if b.raw_type == "title" and block_text(b):
                out.append(make_heading(ids, [b], level=1, role="front_matter_title"))
            elif b.raw_type == "chart":
                out.append(make_chart_table(ids, b))
        if out:
            return _PageResult(out, "table", in_toc)
    if snapshot_role in {"page_diagram", "visual_label_page"}:
        page_num = blocks[0].page
        return _PageResult([make_page_snapshot_figure(ids, page_num, content_blocks, snapshot_role)], "figure", in_toc)
    if snapshot_role in {"designed_media_page", "designed_text_page"}:
        text_blocks = [b for b in content_blocks if b.raw_type in {"paragraph", "title", "list"}]
        out, prev, in_toc = process_normal_flow(ids, text_blocks, layout, prev_major_type, in_toc, text_style=None)
        return _PageResult(out, prev, in_toc)
    return None


def _try_process_title_page(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    in_toc: bool,
) -> Optional[_PageResult]:
    return _PageResult([make_heading(ids, _title_page_titles(content_blocks), level=_title_page_level(content_blocks), role=_title_page_role(content_blocks))], _title_page_role(content_blocks), in_toc)


def _title_page_titles(content_blocks: List[RawBlock]) -> List[RawBlock]:
    return [b for b in content_blocks if b.raw_type in {"paragraph", "title"} and block_text(b)]


def _title_page_role(content_blocks: List[RawBlock]) -> str:
    titles = _title_page_titles(content_blocks)
    if any(PART_RE.match(block_text(b)) for b in titles):
        return "part_title"
    if any(CHAPTER_RE.match(block_text(b)) for b in titles) or len(titles) > 1:
        return "chapter_title"
    return "title_page"


def _title_page_level(content_blocks: List[RawBlock]) -> int:
    return 2 if _title_page_role(content_blocks) == "chapter_title" else 1


def _try_process_sparse_display_page(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    prev_major_type: Optional[str],
    in_toc: bool,
) -> Optional[_PageResult]:
    groups = group_sparse_display_page(content_blocks, prev_major_type)
    if not groups:
        return None
    if len(groups) == 1:
        block = make_display_block(ids, groups[0], layout_role="standalone_display_page", prev_text="")
        block.setdefault("attrs", {})["layout_form"] = "standalone_sparse_page"
        return _PageResult([block], "display_block", in_toc)
    return _PageResult([make_display_group(ids, groups)], "display_block", in_toc)


def _try_process_full_page_image(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    in_toc: bool,
) -> Optional[_PageResult]:
    if not is_full_page_image_page(content_blocks, layout):
        return None
    image = next(b for b in content_blocks if b.raw_type == "image")
    absorbed = [b for b in content_blocks if b is not image and b.raw_type in {"paragraph", "title"} and block_text(b)]
    return _PageResult([make_full_page_figure(ids, image, absorbed)], "full_page_image", in_toc)


def _try_process_plate_page(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    prev_major_type: Optional[str],
    in_toc: bool,
) -> Optional[_PageResult]:
    if not page_has_images(content_blocks):
        return None
    if not _should_process_as_plate_page(content_blocks, layout, prev_major_type):
        return None
    out: List[Dict[str, Any]] = []
    absorbed_by_image: Dict[int, List[RawBlock]] = {}
    absorbed_ids = set()
    for image in [b for b in content_blocks if b.raw_type == "image"]:
        absorbed = _collect_embedded_image_text_blocks(image, content_blocks)
        if absorbed:
            absorbed_by_image[id(image)] = absorbed
            absorbed_ids.update(id(b) for b in absorbed)
    for b in content_blocks:
        if id(b) in absorbed_ids:
            continue
        if b.raw_type == "image":
            figure = make_figure(ids, b)
            _attach_embedded_image_text_attrs(figure, b, absorbed_by_image.get(id(b), []))
            out.append(figure)
        elif b.raw_type == "paragraph" and block_text(b):
            out.append(make_paragraph(ids, b, block_type="caption", extra_attrs={"role": "plate_caption"}))
        elif b.raw_type == "title" and block_text(b):
            out.append(make_heading(ids, [b], level=1, role="front_matter_title"))
    return _PageResult(out, "plate_page", in_toc)


def process_page(
    ids: IdFactory,
    blocks: List[RawBlock],
    layout: LayoutStats,
    prev_major_type: Optional[str],
    in_toc: bool,
    text_style: Optional[_RawTextStyleProvider] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    if not blocks:
        return [], prev_major_type, in_toc

    result = _try_process_toc_page(ids, blocks, layout, prev_major_type, in_toc)
    if result is not None:
        return result

    if in_toc:
        in_toc = False

    content_blocks = [
        b
        for b in blocks
        if b.raw_type not in {"page_number", "page_header"}
        and (b.raw_type != "page_footer" or _looks_like_note_definition_footer(b))
    ]

    for handler in (
        lambda: _try_process_snapshot_page(ids, blocks, content_blocks, layout, prev_major_type, in_toc),
        lambda: _try_process_title_page(ids, content_blocks, in_toc) if is_title_only_page(blocks) else None,
        lambda: _try_process_sparse_display_page(ids, content_blocks, prev_major_type, in_toc),
        lambda: _try_process_full_page_image(ids, content_blocks, layout, in_toc),
        lambda: _try_process_plate_page(ids, content_blocks, layout, prev_major_type, in_toc),
    ):
        result = handler()
        if result is not None:
            return result

    return process_normal_flow(ids, content_blocks, layout, prev_major_type, in_toc, text_style)


def extend_table_source_pages(blocks: List[Dict[str, Any]]) -> None:
    last_table: Optional[Dict[str, Any]] = None
    for b in blocks:
        if b["type"] == "table":
            last_table = b
            pages = b["source"].setdefault("pages", [b["source"]["page"]])
            if b["source"]["page"] not in pages:
                pages.append(b["source"]["page"])
        elif b["type"] == "table_continuation" and last_table is not None:
            pages = last_table["source"].setdefault("pages", [last_table["source"]["page"]])
            p = b["source"].get("page")
            if p and p not in pages:
                pages.append(p)
            last_table["attrs"]["continued"] = True
        elif b["type"] not in {"page_number"}:
            if b["type"] not in {"table_continuation"}:
                last_table = None
