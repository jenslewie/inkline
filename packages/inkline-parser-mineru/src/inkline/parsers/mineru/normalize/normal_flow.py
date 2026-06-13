"""Normal flow page processing for canonical block types.

Handles paragraph, heading, figure, table, footnote, list_item, and
display_block output during the per-page canonicalization pass. Falls through
from page_handlers when no special page type is detected.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..analysis.layout import is_right_aligned_short
from ..extraction.text import block_text, extract_list_item_text, normalize_ws
from ..schema.block_types import (
    DISPLAY_BLOCK,
    FIGURE,
    FOOTNOTE,
    HEADING,
    LIST_ITEM,
    PARAGRAPH,
    TABLE,
    TABLE_CONTINUATION,
)
from ..schema.models import IdFactory, LayoutStats, RawBlock, canonical_block
from ..schema.patterns import CHAPTER_RE, CN_LIST_ITEM_RE
from .builders import (
    make_chart_table,
    make_display_block,
    make_figure,
    make_flush_right_terminal_block,
    make_heading,
    make_paragraph,
    make_table,
)
from .page_detectors import coord_page_size as _coord_page_size
from .raw_display_blocks import (
    _RawTextStyleProvider,
    collect_display_block,
    ends_with_terminal_punctuation,
    should_start_display_block,
)
from .raw_display_blocks import (
    next_meaningful_block as _next_meaningful_block,
)
from .raw_display_blocks import (
    previous_meaningful_block as _previous_meaningful_block,
)


def process_normal_flow(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    prev_major_type: Optional[str],
    in_toc: bool,
    text_style: Optional[_RawTextStyleProvider] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    out: List[Dict[str, Any]] = []
    i = 0
    last_text_context = ""
    display_boundary_attrs: Dict[int, str] = {}
    while i < len(content_blocks):
        b = content_blocks[i]
        if b.raw_type in {"page_number", "page_header"}:
            i += 1
            continue
        if b.raw_type == "page_footer" and _looks_like_note_definition_footer(b):
            out.append(
                make_paragraph(
                    ids,
                    b,
                    block_type=LIST_ITEM,
                    extra_attrs={
                        "promoted_from": "page_footer",
                        "promote_reason": "note_definition_footer",
                    },
                )
            )
            prev_major_type = LIST_ITEM
            i += 1
            continue
        if b.raw_type == "title":
            group = [b]
            j = i + 1
            while (
                j < len(content_blocks)
                and content_blocks[j].raw_type == "title"
                and abs(content_blocks[j].y0 - group[-1].y1) < 80
            ):
                group.append(content_blocks[j])
                j += 1
            role = (
                "chapter_title"
                if any(CHAPTER_RE.match(block_text(x)) for x in group) or len(group) > 1
                else HEADING
            )
            level = 2 if role == "chapter_title" else 1
            out.append(make_heading(ids, group, level=level, role=role))
            prev_major_type = role
            i = j
            continue
        if b.raw_type == "image":
            out.append(make_figure(ids, b))
            prev_major_type = FIGURE
            i += 1
            continue
        if b.raw_type == "chart":
            out.append(make_chart_table(ids, b))
            prev_major_type = TABLE
            i += 1
            continue
        if b.raw_type == "table":
            content = b.raw.get("content", {})
            html = content.get("html", "") if isinstance(content, dict) else ""
            if html.strip():
                out.append(make_table(ids, b))
                prev_major_type = TABLE
            else:
                out.append(
                    canonical_block(
                        ids.next(),
                        TABLE_CONTINUATION,
                        "",
                        b.page,
                        b.bbox,
                        attrs={"role": "continued_table_region", "html_empty": True},
                    )
                )
            prev_major_type = TABLE_CONTINUATION
            i += 1
            continue
        if b.raw_type in {"page_footnote", "ref_text"} and block_text(b):
            footnote_attrs: Dict[str, Any] = {"role": "page_footnote"}
            middle_markers = b.raw.get("_middle_page_inline_markers")
            if isinstance(middle_markers, list) and middle_markers:
                footnote_attrs["_middle_page_inline_markers"] = list(middle_markers)
            out.append(make_paragraph(ids, b, block_type=FOOTNOTE, extra_attrs=footnote_attrs))
            i += 1
            continue
        if b.raw_type == "list":
            content = b.raw.get("content", {})
            items = content.get("list_items", [])
            list_type = content.get("list_type")
            for li in items:
                t, _ = extract_list_item_text(li)
                if t:
                    pseudo = RawBlock(
                        page=b.page,
                        index=b.index,
                        raw_type="list_item",
                        text=t,
                        bbox=b.bbox,
                        raw=li,
                    )
                    list_attrs = {"list_type": list_type} if list_type else None
                    out.append(
                        make_paragraph(ids, pseudo, block_type=LIST_ITEM, extra_attrs=list_attrs)
                    )
            prev_major_type = "list"
            i += 1
            continue
        if b.raw_type == "paragraph" and block_text(b):
            if _is_centered_table_heading_continuation(content_blocks, i, layout):
                out.append(make_heading(ids, [b], level=2, role="table_heading_byline"))
                prev_major_type = HEADING
                i += 1
                continue

            if _is_flush_right_terminal_line_before_section_boundary(content_blocks, i, layout):
                out.append(make_flush_right_terminal_block(ids, [b]))
                prev_major_type = "flush_right_terminal_block"
                i += 1
                continue

            terminal_after_body_line = _following_flush_right_terminal_lines(
                content_blocks, i, layout
            )
            if terminal_after_body_line and _is_left_body_line_before_terminal_block(
                content_blocks, i, layout
            ):
                out.append(make_paragraph(ids, b))
                out.append(make_flush_right_terminal_block(ids, terminal_after_body_line))
                prev_major_type = "flush_right_terminal_block"
                i += 1 + len(terminal_after_body_line)
                continue

            tail_blocks = [
                x
                for x in content_blocks[i:]
                if block_text(x) or x.raw_type in {"image", "table", "title", "list"}
            ]
            remaining = [x for x in tail_blocks if x.raw_type == "paragraph" and block_text(x)]
            if (
                len(remaining) == len(tail_blocks)
                and 1 <= len(remaining) <= 4
                and (
                    len(remaining) > 1
                    or len(block_text(remaining[0])) >= 8
                    or remaining[0].width >= layout.body_width * 0.16
                )
                and all(_is_flush_right_terminal_line(x, layout) for x in remaining)
            ):
                out.append(make_flush_right_terminal_block(ids, remaining))
                prev_major_type = "flush_right_terminal_block"
                i = len(content_blocks)
                continue

            if CN_LIST_ITEM_RE.match(block_text(b)):
                out.append(
                    make_paragraph(
                        ids,
                        b,
                        block_type=LIST_ITEM,
                        extra_attrs={"list_marker_style": "cjk_decimal"},
                    )
                )
                last_text_context = block_text(b)
                prev_major_type = LIST_ITEM
                i += 1
                continue

            prev_text = last_text_context or (
                out[-1]["text"] if out and out[-1]["type"] in {PARAGRAPH, HEADING} else ""
            )
            if should_start_display_block(
                content_blocks, i, prev_text, layout, text_style=text_style
            ):
                group, j, boundary_reason = collect_display_block(
                    content_blocks, i, prev_text, layout, text_style=text_style
                )
                if boundary_reason and j < len(content_blocks):
                    display_boundary_attrs[id(content_blocks[j])] = boundary_reason
                out.append(
                    make_display_block(
                        ids, group, layout_role="inline_display_block", prev_text=prev_text
                    )
                )
                prev_major_type = DISPLAY_BLOCK
                last_text_context = ""
                i = j
                continue

            extra_attrs = None
            boundary_reason = display_boundary_attrs.get(id(b))
            if boundary_reason:
                extra_attrs = {"display_boundary_before": boundary_reason}
            out.append(make_paragraph(ids, b, extra_attrs=extra_attrs))
            last_text_context = block_text(b)
            prev_major_type = PARAGRAPH
            i += 1
            continue
        if block_text(b):
            out.append(make_paragraph(ids, b, block_type=b.raw_type))
            prev_major_type = b.raw_type
        i += 1

    return out, prev_major_type, in_toc


def _is_centered_table_heading_continuation(
    blocks: Sequence[RawBlock], i: int, layout: LayoutStats
) -> bool:
    block = blocks[i]
    if block.raw_type != "paragraph" or not block.bbox:
        return False
    text = normalize_ws(block_text(block))
    if not text or len(text) > 40 or ends_with_terminal_punctuation(text):
        return False

    prev = _previous_meaningful_block(blocks, i)
    nxt = _next_meaningful_block(blocks, i)
    if prev is None or nxt is None or prev.page != block.page or nxt.page != block.page:
        return False
    if prev.raw_type != "title" or nxt.raw_type != "table":
        return False

    page_width, page_height = _coord_page_size([x for x in blocks if x.page == block.page], layout)
    center_x = page_width / 2.0
    block_center = (block.x0 + block.x1) / 2.0
    centered = abs(block_center - center_x) <= max(45.0, page_width * 0.055)
    compact = block.width <= min(layout.body_width * 0.45, page_width * 0.38)
    near_title = 0 <= block.y0 - prev.y1 <= max(70.0, page_height * 0.075)
    near_table = 0 <= nxt.y0 - block.y1 <= max(120.0, page_height * 0.13)
    high_on_page = block.y0 <= page_height * 0.38
    return centered and compact and near_title and near_table and high_on_page


def _is_flush_right_terminal_line(block: RawBlock, layout: LayoutStats) -> bool:
    if block.raw_type != "paragraph" or not block.bbox:
        return False
    text = normalize_ws(block_text(block))
    if not text or len(text) > 40:
        return False
    near_body_right = abs(block.x1 - layout.body_right) <= max(24.0, layout.body_width * 0.04)
    right_lane = block.x0 >= layout.body_left + layout.body_width * 0.33
    return (
        is_right_aligned_short(block, layout)
        or block.x0 > layout.body_left + layout.body_width * 0.45
        or (near_body_right and right_lane)
    )


def _following_flush_right_terminal_lines(
    blocks: Sequence[RawBlock], start: int, layout: LayoutStats
) -> List[RawBlock]:
    tail_blocks = [
        x
        for x in blocks[start + 1 :]
        if block_text(x) or x.raw_type in {"image", "table", "title", "list"}
    ]
    terminal: List[RawBlock] = []
    rest = tail_blocks
    for pos, x in enumerate(tail_blocks):
        if x.raw_type == "paragraph" and block_text(x):
            terminal.append(x)
            continue
        rest = tail_blocks[pos:]
        break
    else:
        rest = []

    if not (1 <= len(terminal) <= 3):
        return []
    if rest and rest[0].raw_type not in {"title", "list", "table", "image"}:
        return []
    if all(_is_flush_right_terminal_line(x, layout) for x in terminal):
        return terminal
    return []


def _is_left_body_line_before_terminal_block(
    blocks: Sequence[RawBlock], i: int, layout: LayoutStats
) -> bool:
    block = blocks[i]
    if block.raw_type != "paragraph" or not block.bbox:
        return False
    text = normalize_ws(block_text(block))
    if not text or len(text) > 90 or ends_with_terminal_punctuation(text):
        return False
    if _is_flush_right_terminal_line(block, layout):
        return False
    if block.x0 > layout.body_left + max(90.0, layout.body_width * 0.14):
        return False
    return bool(_following_flush_right_terminal_lines(blocks, i, layout))


def _is_flush_right_terminal_line_before_section_boundary(
    blocks: Sequence[RawBlock], i: int, layout: LayoutStats
) -> bool:
    block = blocks[i]
    if not _is_flush_right_terminal_line(block, layout):
        return False
    prev = _previous_meaningful_block(blocks, i)
    nxt = _next_meaningful_block(blocks, i)
    if prev is None or prev.page != block.page or prev.raw_type != "paragraph":
        return False
    if nxt is None or nxt.page != block.page or nxt.raw_type not in {"title", "list"}:
        return False
    return block.y0 - prev.y1 <= max(50.0, layout.page_height * 0.07)


def _looks_like_note_definition_footer(block: RawBlock) -> bool:
    text = normalize_ws(block_text(block))
    if len(text) < 8:
        return False
    return bool(re.match(r"^\s*(?:\d{1,3}|[*＊]{1,3}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)\s+[^\d\s]", text))
