"""Raw display block detection and collection.

The raw pass starts display blocks from page-local geometry groups and a narrow
page-bottom footnote boundary case. Text content from surrounding paragraphs is
kept only for downstream attrs, not as a display/paragraph classifier.
"""

from __future__ import annotations

from statistics import median
from typing import List, Optional, Protocol, Sequence, Tuple

from ..extraction.text import block_text, normalize_ws
from ..schema.models import LayoutStats, RawBlock
from .display_geometry import collect_geometry_display_group
from .page_detectors import coord_page_size as _coord_page_size


class _RawTextStyleProvider(Protocol):
    def raw_block_style_size(self, block: RawBlock) -> Optional[float]: ...

    def raw_page_body_style_size(
        self, page: int, blocks: Sequence[RawBlock]
    ) -> Optional[float]: ...


def should_start_display_block(
    blocks: List[RawBlock],
    i: int,
    prev_text: str,
    layout: LayoutStats,
    text_style: Optional[_RawTextStyleProvider] = None,
) -> bool:
    b = blocks[i]
    if b.raw_type != "paragraph" or not block_text(b):
        return False
    if _body_flow_resumes_after_float(blocks, i, layout):
        return False
    if collect_geometry_display_group(blocks, i, layout):
        return True
    return is_page_bottom_set_off_before_footnotes(blocks, i, layout, text_style)


def _body_flow_resumes_after_float(blocks: Sequence[RawBlock], i: int, layout: LayoutStats) -> bool:
    cur = blocks[i]
    if cur.raw_type != "paragraph" or not cur.bbox:
        return False
    prev = _previous_non_note_content(blocks, i)
    if prev is None or prev.page != cur.page or prev.raw_type not in {"image", "table"}:
        return False
    nxt = _next_same_page_paragraph(blocks, i)
    if nxt is None:
        return False
    body_x0, body_w = _page_body_lane(blocks, cur.page, layout)
    return _is_body_lane_paragraph(cur, body_x0, body_w, layout) and _is_body_lane_paragraph(
        nxt, body_x0, body_w, layout
    )


def _previous_non_note_content(blocks: Sequence[RawBlock], i: int) -> Optional[RawBlock]:
    j = i - 1
    while j >= 0:
        candidate = blocks[j]
        if candidate.raw_type in {"page_number", "page_header", "page_footer", "page_footnote"}:
            j -= 1
            continue
        return candidate
    return None


def _next_same_page_paragraph(blocks: Sequence[RawBlock], i: int) -> Optional[RawBlock]:
    page = blocks[i].page
    j = i + 1
    while j < len(blocks):
        candidate = blocks[j]
        if candidate.page != page:
            return None
        if candidate.raw_type in {"page_number", "page_header", "page_footer", "page_footnote"}:
            j += 1
            continue
        if candidate.raw_type == "paragraph" and candidate.bbox and block_text(candidate):
            return candidate
        return None
    return None


def _page_body_lane(
    blocks: Sequence[RawBlock], page: int, layout: LayoutStats
) -> tuple[float, float]:
    wide_body: list[RawBlock] = []
    for block in blocks:
        if block.page != page or block.raw_type != "paragraph" or not block.bbox:
            continue
        if len(normalize_ws(block_text(block))) < 30:
            continue
        if block.width < layout.body_width * 0.70:
            continue
        if block.x0 > layout.body_left + max(30.0, layout.body_width * 0.04):
            continue
        wide_body.append(block)
    if len(wide_body) >= 2:
        return median([block.x0 for block in wide_body]), median(
            [block.width for block in wide_body]
        )
    return layout.body_left, layout.body_width


def _is_body_lane_paragraph(
    block: RawBlock, body_x0: float, body_w: float, layout: LayoutStats
) -> bool:
    if not block.bbox:
        return False
    near_page_body_left = block.x0 <= body_x0 + max(24.0, body_w * 0.035)
    near_global_body_left = block.x0 <= layout.body_left + max(30.0, layout.body_width * 0.04)
    wide = block.width >= body_w * 0.70
    return near_page_body_left and near_global_body_left and wide


def is_page_bottom_set_off_before_footnotes(
    blocks: List[RawBlock],
    i: int,
    layout: LayoutStats,
    text_style: Optional[_RawTextStyleProvider],
) -> bool:
    b = blocks[i]
    if b.raw_type != "paragraph" or not b.bbox or not block_text(b):
        return False
    page_blocks = [x for x in blocks if x.page == b.page]
    _, page_height = _coord_page_size(page_blocks, layout)
    if b.y1 < page_height * 0.74:
        return False
    following_same_page = [
        x
        for x in blocks[i + 1 :]
        if x.page == b.page and x.raw_type not in {"page_number", "page_header", "page_footer"}
    ]
    if not following_same_page or not all(
        x.raw_type == "page_footnote" for x in following_same_page
    ):
        return False
    prev = None
    for candidate in reversed(blocks[:i]):
        if candidate.page != b.page:
            break
        if candidate.raw_type in {"page_number", "page_header", "page_footer"}:
            continue
        if candidate.raw_type != "paragraph" or not candidate.bbox or not block_text(candidate):
            return False
        prev = candidate
        break
    if prev is None:
        return False
    gap = b.y0 - prev.y1
    if gap < max(12.0, page_height * 0.015):
        return False
    if prev.width < layout.body_width * 0.84 or prev.x0 > layout.body_left + max(
        55.0, layout.body_width * 0.07
    ):
        return False
    global_indent = b.x0 - layout.body_left
    local_indent = b.x0 - prev.x0
    global_set_off = (
        global_indent >= max(58.0, layout.body_width * 0.07) and b.width <= layout.body_width * 0.95
    )
    local_set_off = local_indent >= max(
        36.0, layout.body_width * 0.045
    ) and b.width <= prev.width - max(24.0, layout.body_width * 0.03)
    if not (global_set_off or local_set_off):
        return False
    if text_style is None:
        return True
    candidate_size = text_style.raw_block_style_size(b)
    body_size = text_style.raw_page_body_style_size(b.page, page_blocks)
    if candidate_size is None or body_size is None:
        return True
    return body_size * 0.84 <= candidate_size <= body_size * 1.12


def collect_display_block(
    blocks: List[RawBlock],
    i: int,
    prev_text: str,
    layout: LayoutStats,
    text_style: Optional[_RawTextStyleProvider] = None,
) -> Tuple[List[RawBlock], int, Optional[str]]:
    geometry_group = collect_geometry_display_group(blocks, i, layout)
    if geometry_group:
        return geometry_group.blocks, i + len(geometry_group.blocks), None
    if is_page_bottom_set_off_before_footnotes(blocks, i, layout, text_style):
        return [blocks[i]], i + 1, None
    return [blocks[i]], i + 1, None


def previous_meaningful_block(blocks: Sequence[RawBlock], start: int) -> Optional[RawBlock]:
    for candidate in reversed(blocks[:start]):
        if candidate.raw_type in {"page_number", "page_header", "page_footer"}:
            continue
        if block_text(candidate) or candidate.raw_type in {"image", "table", "title", "list"}:
            return candidate
    return None


def next_meaningful_block(blocks: Sequence[RawBlock], start: int) -> Optional[RawBlock]:
    for candidate in blocks[start + 1 :]:
        if candidate.raw_type in {"page_number", "page_header", "page_footer"}:
            continue
        if block_text(candidate) or candidate.raw_type in {"image", "table", "title", "list"}:
            return candidate
    return None
