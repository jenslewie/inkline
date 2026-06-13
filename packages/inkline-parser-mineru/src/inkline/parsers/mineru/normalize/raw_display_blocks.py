"""Display block detection and collection rules. Pure rule functions for deciding when a raw block starts a display block (should_start_display_block) and how far the display block run extends (collect_display_block). Also contains left-shifted intro detection, page-bottom set-off detection, and body-layout resumption guards."""

from __future__ import annotations

from statistics import median
from typing import List, Optional, Protocol, Sequence, Tuple

from ..analysis.layout import (
    is_display_block_layout_raw,
    is_right_aligned_short,
    is_short_or_indented,
)
from ..extraction.text import block_text, normalize_ws
from ..schema.models import LayoutStats, RawBlock
from ..schema.patterns import ATTR_RE
from .display_block_detectors import RawSetOffDisplayRunDetector
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
    t = block_text(b)
    next_t = block_text(blocks[i + 1]) if i + 1 < len(blocks) else ""
    if ATTR_RE.match(next_t) and is_short_or_indented(b, layout):
        return True
    colon_intro = prev_text.rstrip().endswith(("：", ":"))
    if colon_intro and is_display_block_layout_raw(b, layout):
        return True
    if is_left_shifted_intro_before_display_lane(blocks, i, layout):
        return False
    next_raw_type = blocks[i + 1].raw_type if i + 1 < len(blocks) else ""
    strongly_indented = bool(
        b.bbox and b.x0 >= layout.body_left + 55 and b.width <= layout.body_width * 0.95
    )
    short_intro_context = (
        bool(prev_text.strip())
        and len(normalize_ws(prev_text)) <= 90
        and prev_text.rstrip().endswith(("。", "！", "？", ".", "）", ")"))
    )
    if (
        strongly_indented
        and len(t) >= 100
        and short_intro_context
        and next_raw_type == "page_footnote"
    ):
        return True
    if is_page_bottom_set_off_before_footnotes(blocks, i, layout, text_style):
        return True
    if i + 2 < len(blocks):
        tri = blocks[i : i + 3]
        if all(
            x.raw_type == "paragraph"
            and len(block_text(x)) <= 24
            and is_short_or_indented(x, layout)
            for x in tri
        ):
            return True
    return bool(RawSetOffDisplayRunDetector(layout).collect(blocks, i)[0])


def ends_with_terminal_punctuation(text: str) -> bool:
    return normalize_ws(text).endswith(("。", "！", "？", ".", "!", "?", "）", ")"))


def is_left_shifted_intro_before_display_lane(
    blocks: Sequence[RawBlock],
    i: int,
    layout: LayoutStats,
    *,
    reference_x0: Optional[float] = None,
) -> bool:
    b = blocks[i]
    if b.raw_type != "paragraph" or not b.bbox:
        return False
    text = normalize_ws(block_text(b))
    if not text or len(text) > 80 or not text.endswith(("：", ":")):
        return False
    lane_x0 = reference_x0
    following: List[RawBlock] = []
    k = i + 1
    while k < len(blocks) and len(following) < 3:
        nxt = blocks[k]
        if nxt.page != b.page:
            break
        if nxt.raw_type in {"page_number", "page_header", "page_footer", "page_footnote"}:
            k += 1
            continue
        if nxt.raw_type != "paragraph" or not nxt.bbox or not block_text(nxt):
            break
        nxt_text = normalize_ws(block_text(nxt))
        if len(nxt_text) > 40 or nxt.width > layout.body_width * 0.58:
            break
        if lane_x0 is not None and abs(nxt.x0 - lane_x0) > 32:
            break
        following.append(nxt)
        if lane_x0 is None:
            lane_x0 = nxt.x0
        k += 1
    if len(following) < 2 or lane_x0 is None:
        return False
    left_shift = lane_x0 - b.x0
    if left_shift < max(34.0, layout.body_width * 0.04):
        return False
    if b.x0 > layout.body_left + max(82.0, layout.body_width * 0.1):
        return False
    follow_width = median([x.width for x in following])
    return b.width >= follow_width * 1.15 or b.width >= layout.body_width * 0.25


def is_page_bottom_body_tail_before_footnotes(
    blocks: List[RawBlock], i: int, layout: LayoutStats
) -> bool:
    b = blocks[i]
    if not b.bbox:
        return False
    t = block_text(b)
    if not t or ends_with_terminal_punctuation(t):
        return False
    page_blocks = [x for x in blocks if x.page == b.page]
    _, page_height = _coord_page_size(page_blocks, layout)
    line_height = b.height
    if b.y1 < page_height * 0.76 or line_height > max(32.0, page_height * 0.04) or len(t) > 100:
        return False
    following_same_page = [
        x
        for x in blocks[i + 1 :]
        if x.page == b.page and x.raw_type not in {"page_number", "page_header", "page_footer"}
    ]
    if not following_same_page:
        return False
    return all(x.raw_type == "page_footnote" for x in following_same_page)


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
    set_off_group, set_off_end = RawSetOffDisplayRunDetector(layout).collect(blocks, i)
    if set_off_group:
        return set_off_group, set_off_end, None

    group: List[RawBlock] = []
    j = i
    started_by_intro = prev_text.rstrip().endswith(("：", ":"))
    while j < len(blocks):
        b = blocks[j]
        if b.raw_type != "paragraph" or not block_text(b):
            break
        t = block_text(b)
        if not group:
            group.append(b)
            j += 1
            continue
        prev = group[-1]
        if ends_with_terminal_punctuation(
            block_text(prev)
        ) and is_page_bottom_body_tail_before_footnotes(blocks, j, layout):
            break
        if ATTR_RE.match(t):
            group.append(b)
            j += 1
            break
        if is_right_aligned_short(b, layout):
            group.append(b)
            j += 1
            continue
        if _body_layout_resumes_after_completed_display(
            group[0], prev, b, blocks, layout, text_style
        ):
            break
        if _short_line_before_body_layout_resumes(group, prev, b, blocks, j, layout, text_style):
            return group, j, "body_sized_short_line_before_body_resume"
        if is_left_shifted_intro_before_display_lane(
            blocks, j, layout, reference_x0=group[0].x0 if group[0].bbox else None
        ):
            break
        if len(group) >= 2 and all(len(block_text(x)) <= 36 for x in group) and len(t) > 36:
            break
        if len(t) <= 36 and is_short_or_indented(b, layout):
            group.append(b)
            j += 1
            continue
        if (
            started_by_intro
            and is_display_block_layout_raw(b, layout)
            and b.x0 >= group[0].x0 - 5
            and (not b.bbox or not group[0].bbox or b.x1 <= group[0].x1 + 20)
        ):
            group.append(b)
            j += 1
            continue
        break
    return group, j, None


def _body_layout_resumes_after_completed_display(
    first: RawBlock,
    previous: RawBlock,
    candidate: RawBlock,
    blocks: Sequence[RawBlock],
    layout: LayoutStats,
    text_style: Optional[_RawTextStyleProvider],
) -> bool:
    if not ends_with_terminal_punctuation(block_text(previous)):
        return False
    if not first.bbox or not candidate.bbox:
        return False
    returns_left = candidate.x0 <= first.x0 - max(28.0, layout.body_width * 0.035)
    near_body_indent = candidate.x0 <= layout.body_left + max(48.0, layout.body_width * 0.055)
    body_width = candidate.width >= layout.body_width * 0.86
    if not (returns_left and (near_body_indent or body_width)):
        return False
    if _next_same_page_body_aligned(blocks, candidate, layout):
        return True
    if text_style is None:
        return True
    candidate_size = text_style.raw_block_style_size(candidate)
    body_size = text_style.raw_page_body_style_size(candidate.page, blocks)
    first_size = text_style.raw_block_style_size(first)
    if candidate_size is None:
        return True
    if body_size is not None and candidate_size >= body_size * 0.94:
        return True
    return first_size is not None and candidate_size >= first_size * 0.95


def _short_line_before_body_layout_resumes(
    group: Sequence[RawBlock],
    previous: RawBlock,
    candidate: RawBlock,
    blocks: Sequence[RawBlock],
    candidate_index: int,
    layout: LayoutStats,
    text_style: Optional[_RawTextStyleProvider],
) -> bool:
    first = group[0]
    if len(group) >= 2 and all(len(normalize_ws(block_text(x))) <= 42 for x in group):
        return False
    if not ends_with_terminal_punctuation(block_text(previous)):
        return False
    if not first.bbox or not candidate.bbox:
        return False
    text = normalize_ws(block_text(candidate))
    if not text or len(text) > 42:
        return False
    if candidate.x0 > first.x0 + max(16.0, layout.body_width * 0.02):
        return False
    if candidate.height > max(34.0, first.height * 1.35):
        return False
    nxt = _next_body_block_after(blocks, candidate_index)
    if nxt is None or not nxt.bbox:
        return False
    near_body_left = nxt.x0 <= layout.body_left + max(48.0, layout.body_width * 0.055)
    body_width = nxt.width >= layout.body_width * 0.86
    if not (near_body_left and body_width):
        return False
    if text_style is None:
        return candidate.width <= layout.body_width * 0.7
    candidate_size = text_style.raw_block_style_size(candidate)
    body_size = text_style.raw_page_body_style_size(candidate.page, blocks)
    first_size = text_style.raw_block_style_size(first)
    if candidate_size is None:
        return candidate.width <= layout.body_width * 0.7
    if body_size is not None and candidate_size >= body_size * 0.98:
        return True
    return first_size is not None and candidate_size >= first_size * 1.04


def _next_body_block_after(blocks: Sequence[RawBlock], start: int) -> Optional[RawBlock]:
    if start + 1 >= len(blocks):
        return None
    page = blocks[start].page
    for nxt in blocks[start + 1 :]:
        if nxt.page != page:
            return None
        if nxt.raw_type in {"page_number", "page_header", "page_footer", "page_footnote"}:
            continue
        if nxt.raw_type == "paragraph" and block_text(nxt):
            return nxt
        return None
    return None


def _next_same_page_body_aligned(
    blocks: Sequence[RawBlock], candidate: RawBlock, layout: LayoutStats
) -> bool:
    try:
        start = blocks.index(candidate) + 1
    except ValueError:
        return False
    for nxt in blocks[start:]:
        if nxt.page != candidate.page:
            return False
        if nxt.raw_type in {"page_number", "page_header", "page_footer", "page_footnote"}:
            continue
        if nxt.raw_type != "paragraph" or not nxt.bbox or not block_text(nxt):
            return False
        return (
            abs(nxt.x0 - candidate.x0) <= max(12.0, layout.body_width * 0.025)
            and nxt.width >= layout.body_width * 0.86
        )
    return False


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
