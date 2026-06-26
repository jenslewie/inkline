"""Geometry-first display block classification helpers.

These helpers keep display-block detection centered on page-local layout:
body-column estimates, visual groups, short-line lanes, and right alignment.
Callers should use these geometry signals before any non-display structural
classification so text shape cannot override visual layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional, Sequence

from ..extraction.text import block_text, normalize_ws
from ..schema.models import LayoutStats, RawBlock


@dataclass(frozen=True)
class PageLayoutProfile:
    page_width: float
    page_height: float
    body_x0: float
    body_x1: float

    @property
    def body_w(self) -> float:
        return max(1.0, self.body_x1 - self.body_x0)

    @classmethod
    def from_blocks(
        cls, blocks: Sequence[RawBlock], layout: LayoutStats, page: Optional[int] = None
    ) -> "PageLayoutProfile":
        page_blocks = [b for b in blocks if page is None or b.page == page]
        boxes = [b for b in page_blocks if b.bbox]
        page_width, page_height = _bbox_coord_page_size(boxes, layout)
        scale = page_width / layout.page_width if layout.page_width else 1.0
        fallback_body_x0 = layout.body_left * scale
        fallback_body_x1 = layout.body_right * scale
        fallback_body_w = max(1.0, fallback_body_x1 - fallback_body_x0)

        wide_text = [
            b
            for b in page_blocks
            if b.raw_type == "paragraph"
            and b.bbox
            and block_text(b)
            and len(normalize_ws(block_text(b))) >= 30
            and b.width >= max(fallback_body_w * 0.70, page_width * 0.45)
        ]
        if len(wide_text) >= 2:
            return cls(
                page_width=page_width,
                page_height=page_height,
                body_x0=median(float(b.x0) for b in wide_text),
                body_x1=median(float(b.x1) for b in wide_text),
            )
        return cls(
            page_width=page_width,
            page_height=page_height,
            body_x0=fallback_body_x0,
            body_x1=fallback_body_x1,
        )

    def is_body_like(self, block: RawBlock) -> bool:
        if not block.bbox:
            return False
        near_left = block.x0 <= self.body_x0 + max(36.0, self.body_w * 0.055)
        wide = block.width >= self.body_w * 0.86
        return near_left and wide

    def is_short_line(self, block: RawBlock) -> bool:
        return bool(block.bbox and block.width <= self.body_w * 0.58)

    def is_indented(self, block: RawBlock) -> bool:
        return bool(block.bbox and block.x0 >= self.body_x0 + max(34.0, self.body_w * 0.045))

    def is_set_off(self, block: RawBlock) -> bool:
        if not block.bbox:
            return False
        return (self.is_indented(block) and block.width <= self.body_w * 0.98) or (
            block.width <= self.body_w * 0.82
        )

    def is_right_aligned_short(self, block: RawBlock) -> bool:
        if not block.bbox:
            return False
        near_right = abs(block.x1 - self.body_x1) <= max(28.0, self.body_w * 0.045)
        compact = block.width <= self.body_w * 0.55
        right_lane = block.x0 >= self.body_x0 + self.body_w * 0.40
        return near_right and compact and right_lane


@dataclass(frozen=True)
class GeometryDisplayGroup:
    blocks: list[RawBlock]
    layout_form: str
    alignment: Optional[str] = None


def _bbox_coord_page_size(boxes: Sequence[RawBlock], layout: LayoutStats) -> tuple[float, float]:
    max_x1 = max((float(b.x1) for b in boxes), default=0.0)
    max_y1 = max((float(b.y1) for b in boxes), default=0.0)
    page_width = _bbox_coord_axis_size(max_x1, layout.page_width)
    page_height = _bbox_coord_axis_size(max_y1, layout.page_height)
    return page_width, page_height


def _bbox_coord_axis_size(max_coord: float, layout_axis_size: float) -> float:
    if layout_axis_size > 1100.0 and 0 < max_coord <= 1050.0:
        return 1000.0
    return max(layout_axis_size, max_coord, 1.0)


def collect_geometry_display_group(
    blocks: Sequence[RawBlock], start: int, layout: LayoutStats
) -> Optional[GeometryDisplayGroup]:
    """Collect a display group starting at ``start`` using page-local geometry.

    The collector intentionally handles strong geometry cases only. Ambiguous
    single-block cases are left to later geometry-aware reconciliation.
    """

    if start >= len(blocks):
        return None
    first = blocks[start]
    if first.raw_type != "paragraph" or not first.bbox or not block_text(first):
        return None

    profile = PageLayoutProfile.from_blocks(blocks, layout, page=first.page)
    if _has_body_flow_continuity(blocks, start, profile):
        return None

    bridged_set_off = _collect_set_off_around_narrow_bridge(blocks, start, profile)
    if bridged_set_off:
        return bridged_set_off
    if _is_narrow_bridge_between_wide_set_off_blocks(blocks, start, profile):
        return None

    multiline_set_off = _collect_multiline_set_off_block(blocks, start, profile)
    if multiline_set_off:
        return multiline_set_off

    short_group = _collect_short_line_group(blocks, start, profile)
    if short_group:
        return short_group

    set_off = _collect_set_off_group(blocks, start, profile)
    if set_off:
        return set_off
    return None


def display_attrs_for_group(
    group: Sequence[RawBlock], all_blocks: Sequence[RawBlock], layout: LayoutStats
) -> dict[str, object]:
    """Return public display attrs implied by geometry for an emitted group."""

    if not group:
        return {}
    profile = PageLayoutProfile.from_blocks(all_blocks, layout, page=group[0].page)
    attrs: dict[str, object] = {}
    if _looks_like_short_line_group(group, profile):
        attrs["layout_form"] = "short_line_group"
        attrs["classification_evidence"] = ["geometry_short_line_group"]
    if all(profile.is_right_aligned_short(block) for block in group if block.bbox):
        attrs["alignment"] = "right"
        attrs["style_hints"] = {"text_align": "right"}
        attrs.setdefault("classification_evidence", []).append("geometry_right_aligned_group")
    return attrs


def _has_body_flow_continuity(
    blocks: Sequence[RawBlock], start: int, profile: PageLayoutProfile
) -> bool:
    cur = blocks[start]
    if cur.raw_type != "paragraph" or not cur.bbox or not block_text(cur):
        return False
    prev = _previous_same_page_paragraph(blocks, start, cur.page)
    if prev is None or not profile.is_body_like(prev):
        return False

    vertical_gap = cur.y0 - prev.y1
    tight_body_gap = 0 <= vertical_gap <= max(18.0, profile.page_height * 0.018)
    if not tight_body_gap:
        return False

    indent = cur.x0 - profile.body_x0
    first_line_indent_band = (
        max(34.0, profile.body_w * 0.045) <= indent <= max(82.0, profile.body_w * 0.11)
    )
    return first_line_indent_band


def _previous_same_page_paragraph(
    blocks: Sequence[RawBlock], start: int, page: int
) -> Optional[RawBlock]:
    for candidate in reversed(blocks[:start]):
        if candidate.page != page:
            return None
        if candidate.raw_type in {"page_number", "page_header", "page_footer", "page_footnote"}:
            continue
        if candidate.raw_type == "paragraph" and candidate.bbox and block_text(candidate):
            return candidate
        return None
    return None


def _collect_multiline_set_off_block(
    blocks: Sequence[RawBlock], start: int, profile: PageLayoutProfile
) -> Optional[GeometryDisplayGroup]:
    first = blocks[start]
    if not profile.is_set_off(first) or profile.is_body_like(first):
        return None
    if not _looks_like_multiline_raw_block(blocks, first, profile):
        return None
    if _is_wide_set_off_block(first, profile):
        return GeometryDisplayGroup([first], layout_form="set_off_text")
    prev = _previous_same_page_paragraph(blocks, start, first.page)
    if prev is not None:
        gap = first.y0 - prev.y1
        if gap < max(24.0, profile.page_height * 0.025):
            return None
    return GeometryDisplayGroup([first], layout_form="set_off_text")


def _looks_like_multiline_raw_block(
    blocks: Sequence[RawBlock], block: RawBlock, profile: PageLayoutProfile
) -> bool:
    explicit_lines = [line for line in block_text(block).splitlines() if line.strip()]
    if len(explicit_lines) >= 2:
        return True
    line_height = _page_local_line_height(blocks, block.page, profile)
    return block.height >= line_height * 2.2


def _page_local_line_height(
    blocks: Sequence[RawBlock], page: int, profile: PageLayoutProfile
) -> float:
    max_single_line_height = max(44.0, profile.page_height * 0.05)
    heights = [
        block.height
        for block in blocks
        if block.page == page
        and block.raw_type == "paragraph"
        and block.bbox
        and block_text(block)
        and 0 < block.height <= max_single_line_height
    ]
    if heights:
        return max(1.0, median(heights))
    return max(18.0, profile.page_height * 0.022)


def _collect_short_line_group(
    blocks: Sequence[RawBlock], start: int, profile: PageLayoutProfile
) -> Optional[GeometryDisplayGroup]:
    group: list[RawBlock] = []
    first = blocks[start]
    right_aligned = profile.is_right_aligned_short(first)
    left_lane = first.x0
    right_lane = first.x1
    i = start
    while i < len(blocks):
        cur = blocks[i]
        if cur.page != first.page or cur.raw_type != "paragraph" or not cur.bbox:
            break
        if not block_text(cur) or profile.is_body_like(cur):
            break
        short = profile.is_short_line(cur)
        right_match = right_aligned and profile.is_right_aligned_short(cur)
        left_match = abs(cur.x0 - left_lane) <= max(24.0, profile.body_w * 0.04)
        right_edge_match = abs(cur.x1 - right_lane) <= max(28.0, profile.body_w * 0.045)
        if not short or not (right_match or left_match or right_edge_match):
            break
        if group:
            prev = group[-1]
            gap = cur.y0 - prev.y1
            if gap < -8.0 or gap > max(42.0, prev.height * 1.9, cur.height * 1.9):
                break
        group.append(cur)
        i += 1

    if len(group) < 2:
        return None
    widths = [b.width for b in group]
    if median(widths) > profile.body_w * 0.62:
        return None
    alignment = (
        "right" if right_aligned and all(profile.is_right_aligned_short(b) for b in group) else None
    )
    return GeometryDisplayGroup(group, layout_form="short_line_group", alignment=alignment)


def _collect_set_off_group(
    blocks: Sequence[RawBlock], start: int, profile: PageLayoutProfile
) -> Optional[GeometryDisplayGroup]:
    first = blocks[start]
    if not profile.is_set_off(first) or profile.is_body_like(first):
        return None

    group = [first]
    i = start + 1
    while i < len(blocks):
        cur = blocks[i]
        if cur.page != first.page or cur.raw_type != "paragraph" or not cur.bbox:
            break
        if not block_text(cur) or profile.is_body_like(cur) or not profile.is_set_off(cur):
            break
        aligned_left = abs(cur.x0 - group[-1].x0) <= max(32.0, profile.body_w * 0.05)
        contained_width = cur.x1 <= max(group[-1].x1, profile.body_x1) + max(
            28.0, profile.body_w * 0.05
        )
        gap = cur.y0 - group[-1].y1
        if not aligned_left or not contained_width:
            break
        if gap < -8.0 or gap > max(55.0, group[-1].height * 2.4, cur.height * 2.4):
            break
        group.append(cur)
        i += 1

    if len(group) >= 2:
        return GeometryDisplayGroup(group, layout_form="set_off_text")
    return None


def _collect_set_off_around_narrow_bridge(
    blocks: Sequence[RawBlock],
    start: int,
    profile: PageLayoutProfile,
) -> Optional[GeometryDisplayGroup]:
    cur = blocks[start]
    if not _is_wide_set_off_block(cur, profile):
        return None
    if _is_wide_set_off_before_narrow_bridge(blocks, start, profile):
        return GeometryDisplayGroup([cur], layout_form="set_off_text")
    if _is_wide_set_off_after_narrow_bridge(blocks, start, profile):
        return GeometryDisplayGroup([cur], layout_form="set_off_text")
    return None


def _is_wide_set_off_before_narrow_bridge(
    blocks: Sequence[RawBlock],
    start: int,
    profile: PageLayoutProfile,
) -> bool:
    if start + 3 >= len(blocks):
        return False
    cur = blocks[start]
    bridge = blocks[start + 1]
    after = blocks[start + 2]
    body = blocks[start + 3]
    return (
        _is_narrow_bridge_between(cur, bridge, after, profile)
        and _is_following_body_boundary(body, cur.page, profile)
        and _has_tight_vertical_chain(cur, bridge, after, profile)
    )


def _is_wide_set_off_after_narrow_bridge(
    blocks: Sequence[RawBlock],
    start: int,
    profile: PageLayoutProfile,
) -> bool:
    if start < 2 or start + 1 >= len(blocks):
        return False
    before = blocks[start - 2]
    bridge = blocks[start - 1]
    cur = blocks[start]
    body = blocks[start + 1]
    return (
        _is_narrow_bridge_between(before, bridge, cur, profile)
        and _is_following_body_boundary(body, cur.page, profile)
        and _has_tight_vertical_chain(before, bridge, cur, profile)
    )


def _is_narrow_bridge_between_wide_set_off_blocks(
    blocks: Sequence[RawBlock],
    start: int,
    profile: PageLayoutProfile,
) -> bool:
    if start < 1 or start + 2 >= len(blocks):
        return False
    before = blocks[start - 1]
    bridge = blocks[start]
    after = blocks[start + 1]
    body = blocks[start + 2]
    return (
        _is_narrow_bridge_between(before, bridge, after, profile)
        and _is_following_body_boundary(body, bridge.page, profile)
        and _has_tight_vertical_chain(before, bridge, after, profile)
    )


def _is_narrow_bridge_between(
    before: RawBlock,
    bridge: RawBlock,
    after: RawBlock,
    profile: PageLayoutProfile,
) -> bool:
    if before.page != bridge.page or after.page != bridge.page:
        return False
    if not (
        _is_wide_set_off_block(before, profile)
        and _is_narrow_set_off_block(bridge, profile)
        and _is_wide_set_off_block(after, profile)
    ):
        return False
    left_aligned = abs(before.x0 - bridge.x0) <= max(32.0, profile.body_w * 0.05) and abs(
        after.x0 - bridge.x0
    ) <= max(32.0, profile.body_w * 0.05)
    bridge_narrower = before.width >= max(bridge.width * 1.35, profile.body_w * 0.45) and (
        after.width >= max(bridge.width * 1.35, profile.body_w * 0.45)
    )
    return left_aligned and bridge_narrower


def _is_wide_set_off_block(block: RawBlock, profile: PageLayoutProfile) -> bool:
    return (
        block.raw_type == "paragraph"
        and bool(block.bbox)
        and bool(block_text(block))
        and profile.is_set_off(block)
        and not profile.is_body_like(block)
        and block.width >= profile.body_w * 0.45
    )


def _is_narrow_set_off_block(block: RawBlock, profile: PageLayoutProfile) -> bool:
    return (
        block.raw_type == "paragraph"
        and bool(block.bbox)
        and bool(block_text(block))
        and profile.is_set_off(block)
        and not profile.is_body_like(block)
        and block.width <= profile.body_w * 0.58
    )


def _is_following_body_boundary(
    block: RawBlock,
    page: int,
    profile: PageLayoutProfile,
) -> bool:
    return (
        block.page == page
        and block.raw_type == "paragraph"
        and bool(block.bbox)
        and bool(block_text(block))
        and profile.is_body_like(block)
    )


def _has_tight_vertical_chain(
    before: RawBlock,
    bridge: RawBlock,
    after: RawBlock,
    profile: PageLayoutProfile,
) -> bool:
    first_gap = bridge.y0 - before.y1
    second_gap = after.y0 - bridge.y1
    gap_limit = max(58.0, profile.body_w * 0.08)
    return 0 <= first_gap <= gap_limit and 0 <= second_gap <= gap_limit


def _looks_like_short_line_group(group: Sequence[RawBlock], profile: PageLayoutProfile) -> bool:
    text_blocks = [b for b in group if b.bbox and block_text(b)]
    if len(text_blocks) < 2:
        return False
    short_count = sum(1 for b in text_blocks if profile.is_short_line(b))
    return short_count / len(text_blocks) >= 0.75
