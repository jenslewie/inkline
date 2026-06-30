"""Normal flow page processing for canonical block types.

Handles paragraph, heading, figure, table, footnote, list_item, and
display_block output during the per-page canonicalization pass. Falls through
from page_handlers when no special page type is detected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
from ..schema.patterns import CHAPTER_RE
from .builders import (
    make_chart_table,
    make_display_block,
    make_figure,
    make_flush_right_terminal_block,
    make_heading,
    make_paragraph,
    make_table,
)
from .display_geometry import display_attrs_for_group
from .page_detectors import coord_page_size as _coord_page_size
from .raw_display_blocks import (
    _RawTextStyleProvider,
    collect_display_block,
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
    state = _NormalFlowState(prev_major_type=prev_major_type, in_toc=in_toc)
    while state.i < len(content_blocks):
        block = content_blocks[state.i]
        if _should_skip_raw_block(block):
            state.i += 1
            continue
        if block.raw_type == "paragraph" and block_text(block):
            _handle_paragraph_block(ids, content_blocks, layout, state, text_style)
            continue
        if _handle_known_non_paragraph_block(ids, content_blocks, state, block):
            continue
        if block_text(block):
            state.out.append(make_paragraph(ids, block, block_type=block.raw_type))
            state.prev_major_type = block.raw_type
        state.i += 1

    return state.out, state.prev_major_type, state.in_toc


@dataclass
class _NormalFlowState:
    out: List[Dict[str, Any]] = field(default_factory=list)
    i: int = 0
    prev_major_type: Optional[str] = None
    in_toc: bool = False
    last_text_context: str = ""
    display_boundary_attrs: Dict[int, str] = field(default_factory=dict)


def _should_skip_raw_block(block: RawBlock) -> bool:
    return block.raw_type in {"page_number", "page_header"}


def _handle_known_non_paragraph_block(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    state: _NormalFlowState,
    block: RawBlock,
) -> bool:
    if block.raw_type == "page_footer" and _looks_like_note_definition_footer(block):
        _append_note_footer_as_list_item(ids, state, block)
        return True
    if block.raw_type == "title":
        _append_title_group(ids, content_blocks, state)
        return True
    if block.raw_type == "image":
        state.out.append(make_figure(ids, block))
        state.prev_major_type = FIGURE
        state.i += 1
        return True
    if block.raw_type == "chart":
        state.out.append(make_chart_table(ids, block))
        state.prev_major_type = TABLE
        state.i += 1
        return True
    if block.raw_type == "table":
        _append_table_or_continuation(ids, state, block)
        return True
    if block.raw_type in {"page_footnote", "ref_text"} and block_text(block):
        _append_page_footnote(ids, state, block)
        return True
    if block.raw_type == "list":
        _append_list_items(ids, state, block)
        return True
    return False


def _append_note_footer_as_list_item(
    ids: IdFactory, state: _NormalFlowState, block: RawBlock
) -> None:
    state.out.append(
        make_paragraph(
            ids,
            block,
            block_type=LIST_ITEM,
            extra_attrs={
                "promoted_from": "page_footer",
                "promote_reason": "note_definition_footer",
            },
        )
    )
    state.prev_major_type = LIST_ITEM
    state.i += 1


def _append_title_group(
    ids: IdFactory, content_blocks: List[RawBlock], state: _NormalFlowState
) -> None:
    group, next_index = _collect_title_group(content_blocks, state.i)
    role = "chapter_title" if _is_chapter_title_group(group) else HEADING
    level = 2 if role == "chapter_title" else 1
    state.out.append(make_heading(ids, group, level=level, role=role))
    state.prev_major_type = role
    state.i = next_index


def _collect_title_group(blocks: List[RawBlock], start: int) -> Tuple[List[RawBlock], int]:
    group = [blocks[start]]
    index = start + 1
    while (
        index < len(blocks)
        and blocks[index].raw_type == "title"
        and abs(blocks[index].y0 - group[-1].y1) < 80
    ):
        group.append(blocks[index])
        index += 1
    return group, index


def _is_chapter_title_group(group: List[RawBlock]) -> bool:
    return len(group) > 1 or any(CHAPTER_RE.match(block_text(block)) for block in group)


def _append_table_or_continuation(
    ids: IdFactory, state: _NormalFlowState, block: RawBlock
) -> None:
    content = block.raw.get("content", {})
    html = content.get("html", "") if isinstance(content, dict) else ""
    if html.strip():
        state.out.append(make_table(ids, block))
        state.prev_major_type = TABLE
    else:
        state.out.append(
            canonical_block(
                ids.next(),
                TABLE_CONTINUATION,
                "",
                block.page,
                block.bbox,
                attrs={"role": "continued_table_region", "html_empty": True},
            )
        )
    state.prev_major_type = TABLE_CONTINUATION
    state.i += 1


def _append_page_footnote(ids: IdFactory, state: _NormalFlowState, block: RawBlock) -> None:
    footnote_attrs: Dict[str, Any] = {"role": "page_footnote"}
    middle_markers = block.raw.get("_middle_page_inline_markers")
    if isinstance(middle_markers, list) and middle_markers:
        footnote_attrs["_middle_page_inline_markers"] = list(middle_markers)
    state.out.append(make_paragraph(ids, block, block_type=FOOTNOTE, extra_attrs=footnote_attrs))
    state.i += 1


def _append_list_items(ids: IdFactory, state: _NormalFlowState, block: RawBlock) -> None:
    content = block.raw.get("content", {})
    items = content.get("list_items", [])
    list_type = content.get("list_type")
    for item in items:
        text, _ = extract_list_item_text(item)
        if not text:
            continue
        pseudo = RawBlock(
            page=block.page,
            index=block.index,
            raw_type="list_item",
            text=text,
            bbox=block.bbox,
            raw=item,
        )
        list_attrs = {"list_type": list_type} if list_type else None
        state.out.append(make_paragraph(ids, pseudo, block_type=LIST_ITEM, extra_attrs=list_attrs))
    state.prev_major_type = "list"
    state.i += 1


def _handle_paragraph_block(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    state: _NormalFlowState,
    text_style: Optional[_RawTextStyleProvider],
) -> None:
    block = content_blocks[state.i]
    if _append_centered_table_heading(ids, content_blocks, layout, state):
        return
    if _append_flush_right_terminal_before_boundary(ids, content_blocks, layout, state):
        return
    if _append_body_line_with_following_terminal(ids, content_blocks, layout, state):
        return
    if _append_tail_terminal_group(ids, content_blocks, layout, state):
        return
    if _append_inline_display_block(ids, content_blocks, layout, state, text_style):
        return
    _append_plain_paragraph(ids, state, block)


def _append_centered_table_heading(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    state: _NormalFlowState,
) -> bool:
    if not _is_centered_table_heading_continuation(content_blocks, state.i, layout):
        return False
    state.out.append(make_heading(ids, [content_blocks[state.i]], level=2, role="table_heading_byline"))
    state.prev_major_type = HEADING
    state.i += 1
    return True


def _append_flush_right_terminal_before_boundary(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    state: _NormalFlowState,
) -> bool:
    if not _is_flush_right_terminal_line_before_section_boundary(content_blocks, state.i, layout):
        return False
    state.out.append(make_flush_right_terminal_block(ids, [content_blocks[state.i]]))
    state.prev_major_type = DISPLAY_BLOCK
    state.i += 1
    return True


def _append_body_line_with_following_terminal(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    state: _NormalFlowState,
) -> bool:
    terminal_after_body_line = _following_flush_right_terminal_lines(
        content_blocks, state.i, layout
    )
    if not terminal_after_body_line or not _is_left_body_line_before_terminal_block(
        content_blocks, state.i, layout
    ):
        return False
    state.out.append(make_paragraph(ids, content_blocks[state.i]))
    state.out.append(make_flush_right_terminal_block(ids, terminal_after_body_line))
    state.prev_major_type = DISPLAY_BLOCK
    state.i += 1 + len(terminal_after_body_line)
    return True


def _append_tail_terminal_group(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    state: _NormalFlowState,
) -> bool:
    remaining = _remaining_paragraph_tail(content_blocks, state.i)
    tail_blocks = _meaningful_tail_blocks(content_blocks, state.i)
    if not _is_terminal_paragraph_tail(remaining, tail_blocks, layout):
        return False
    state.out.append(make_flush_right_terminal_block(ids, remaining))
    state.prev_major_type = DISPLAY_BLOCK
    state.i = len(content_blocks)
    return True


def _meaningful_tail_blocks(blocks: List[RawBlock], start: int) -> List[RawBlock]:
    return [
        block
        for block in blocks[start:]
        if block_text(block) or block.raw_type in {"image", "table", "title", "list"}
    ]


def _remaining_paragraph_tail(blocks: List[RawBlock], start: int) -> List[RawBlock]:
    return [
        block
        for block in _meaningful_tail_blocks(blocks, start)
        if block.raw_type == "paragraph" and block_text(block)
    ]


def _is_terminal_paragraph_tail(
    remaining: List[RawBlock], tail_blocks: List[RawBlock], layout: LayoutStats
) -> bool:
    return bool(
        len(remaining) == len(tail_blocks)
        and 1 <= len(remaining) <= 4
        and _tail_has_enough_visual_weight(remaining, layout)
        and all(_is_flush_right_terminal_line(block, layout) for block in remaining)
    )


def _tail_has_enough_visual_weight(remaining: List[RawBlock], layout: LayoutStats) -> bool:
    return bool(
        len(remaining) > 1
        or len(block_text(remaining[0])) >= 8
        or remaining[0].width >= layout.body_width * 0.16
    )


def _append_inline_display_block(
    ids: IdFactory,
    content_blocks: List[RawBlock],
    layout: LayoutStats,
    state: _NormalFlowState,
    text_style: Optional[_RawTextStyleProvider],
) -> bool:
    prev_text = _previous_text_context(state)
    if not should_start_display_block(
        content_blocks, state.i, prev_text, layout, text_style=text_style
    ):
        return False
    group, next_index, boundary_reason = collect_display_block(
        content_blocks, state.i, prev_text, layout, text_style=text_style
    )
    if boundary_reason and next_index < len(content_blocks):
        state.display_boundary_attrs[id(content_blocks[next_index])] = boundary_reason
    state.out.append(
        make_display_block(
            ids,
            group,
            layout_role="inline_display_block",
            prev_text=prev_text,
            extra_attrs=display_attrs_for_group(group, content_blocks, layout),
        )
    )
    state.prev_major_type = DISPLAY_BLOCK
    state.last_text_context = ""
    state.i = next_index
    return True


def _previous_text_context(state: _NormalFlowState) -> str:
    if state.last_text_context:
        return state.last_text_context
    if state.out and state.out[-1]["type"] in {PARAGRAPH, HEADING}:
        return str(state.out[-1]["text"])
    return ""


def _append_plain_paragraph(
    ids: IdFactory, state: _NormalFlowState, block: RawBlock
) -> None:
    boundary_reason = state.display_boundary_attrs.get(id(block))
    extra_attrs = {"display_boundary_before": boundary_reason} if boundary_reason else None
    state.out.append(make_paragraph(ids, block, extra_attrs=extra_attrs))
    state.last_text_context = block_text(block)
    state.prev_major_type = PARAGRAPH
    state.i += 1


def _is_centered_table_heading_continuation(
    blocks: Sequence[RawBlock], i: int, layout: LayoutStats
) -> bool:
    block = blocks[i]
    if block.raw_type != "paragraph" or not block.bbox:
        return False
    text = normalize_ws(block_text(block))
    if not text or len(text) > 40:
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
    if not text or len(text) > 90:
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
