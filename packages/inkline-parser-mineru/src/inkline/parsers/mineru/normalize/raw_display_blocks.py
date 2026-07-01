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
from .display_geometry import PageLayoutProfile, collect_geometry_display_group
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
    return _is_body_lane_paragraph(cur, body_x0, body_w) and _is_body_lane_paragraph(
        nxt, body_x0, body_w
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
    profile = PageLayoutProfile.from_blocks(blocks, layout, page=page)
    wide_body: list[RawBlock] = []
    for block in blocks:
        if block.page != page or block.raw_type != "paragraph" or not block.bbox:
            continue
        if len(normalize_ws(block_text(block))) < 30:
            continue
        if block.width < profile.body_w * 0.70:
            continue
        if block.x0 > profile.body_x0 + max(30.0, profile.body_w * 0.04):
            continue
        wide_body.append(block)
    if len(wide_body) >= 2:
        return median([block.x0 for block in wide_body]), median(
            [block.width for block in wide_body]
        )
    return profile.body_x0, profile.body_w


def _is_body_lane_paragraph(block: RawBlock, body_x0: float, body_w: float) -> bool:
    if not block.bbox:
        return False
    near_page_body_left = block.x0 <= body_x0 + max(24.0, body_w * 0.035)
    wide = block.width >= body_w * 0.70
    return near_page_body_left and wide


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
    if not _only_page_footnotes_follow(blocks, i, b.page):
        return False
    prev = _previous_same_page_paragraph(blocks, i, b.page)
    if prev is None:
        return False
    gap = b.y0 - prev.y1
    if gap < max(12.0, page_height * 0.015):
        return False
    profile = PageLayoutProfile.from_blocks(page_blocks, layout, page=b.page)
    if not _is_set_off_from_body(b, prev, profile):
        return False
    return _matches_body_font_size(b, page_blocks, text_style)


def _only_page_footnotes_follow(blocks: Sequence[RawBlock], i: int, page: int) -> bool:
    following_same_page = [
        block
        for block in blocks[i + 1 :]
        if block.page == page
        and block.raw_type not in {"page_number", "page_header", "page_footer"}
    ]
    return bool(
        following_same_page
        and all(block.raw_type == "page_footnote" for block in following_same_page)
    )


def _previous_same_page_paragraph(
    blocks: Sequence[RawBlock], i: int, page: int
) -> Optional[RawBlock]:
    for candidate in reversed(blocks[:i]):
        if candidate.page != page:
            return None
        if candidate.raw_type in {"page_number", "page_header", "page_footer"}:
            continue
        if candidate.raw_type != "paragraph" or not candidate.bbox or not block_text(candidate):
            return None
        return candidate
    return None


def _is_set_off_from_body(block: RawBlock, prev: RawBlock, profile: PageLayoutProfile) -> bool:
    if prev.width < profile.body_w * 0.84 or prev.x0 > profile.body_x0 + max(
        55.0, profile.body_w * 0.07
    ):
        return False
    return _is_global_set_off(block, profile) or _is_local_set_off(block, prev, profile)


def _is_global_set_off(block: RawBlock, profile: PageLayoutProfile) -> bool:
    global_indent = block.x0 - profile.body_x0
    return bool(
        global_indent >= max(58.0, profile.body_w * 0.07)
        and block.width <= profile.body_w * 0.95
    )


def _is_local_set_off(block: RawBlock, prev: RawBlock, profile: PageLayoutProfile) -> bool:
    local_indent = block.x0 - prev.x0
    return bool(
        local_indent >= max(36.0, profile.body_w * 0.045)
        and block.width <= prev.width - max(24.0, profile.body_w * 0.03)
    )


def _matches_body_font_size(
    block: RawBlock,
    page_blocks: Sequence[RawBlock],
    text_style: Optional[_RawTextStyleProvider],
) -> bool:
    if text_style is None:
        return True
    candidate_size = text_style.raw_block_style_size(block)
    body_size = text_style.raw_page_body_style_size(block.page, page_blocks)
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
