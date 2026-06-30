from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from inkline.epub.chapter.model import Chapter
from inkline.epub.figure.html import (
    render_caption_block_html,
    render_figure_html,
)
from inkline.epub.figure.layout import estimate_document_page_width
from inkline.epub.figure.resolver import collect_trailing_captions, resolve_figure_view
from inkline.epub.figure.visual_pages import (
    build_full_page_figure_map,
    build_snapshot_asset_id_map,
    build_visual_page_set,
    snapshot_figure_html,
)
from inkline.epub.navigation.resolver import toc_heading_block_ids
from inkline.epub.table.html import render_table_html
from inkline.epub.table.resolver import resolve_table_view
from inkline.epub.text.html import (
    render_chapter_title_page_html,
    render_display_block_html,
    render_footnote_html,
    render_heading_html,
    render_inline_text,
    render_list_html,
)
from inkline.epub.text.resolver import (
    resolve_chapter_title_view,
    resolve_display_block_view,
    resolve_footnote_view,
    resolve_heading_view,
    resolve_inline_text,
    resolve_list_view,
)

__all__ = ["chapter_documents"]


@dataclass
class _RenderContext:
    document: dict[str, Any]
    blocks: list[dict[str, Any]]
    image_assets: dict[str, dict[str, Any]]
    inline_images: dict[str, dict[str, Any]]
    visual_pages: set[int]
    full_page_figures: dict[int, dict[str, Any]]
    snapshot_asset_ids: dict[int, str]
    page_width: float | None
    toc_split_ids: set[str]
    chapter_level: int


@dataclass
class _RenderState:
    metadata: dict[str, Any]
    chapters: list[tuple[str, list[str], str | None]] = field(default_factory=list)
    current_html: list[str] = field(default_factory=list)
    current_title: str = ""
    current_block_id: str | None = None
    emitted_visual_pages: set[int] = field(default_factory=set)
    footnote_counter: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.current_title:
            self.current_title = self.metadata.get("title") or self.metadata["doc_id"]

    def append(self, html: str) -> None:
        self.current_html.append(html)

    def start_chapter(self, title: str, block_id: str | None) -> None:
        if self.current_html:
            self.chapters.append((self.current_title, self.current_html, self.current_block_id))
            self.current_html = []
        self.footnote_counter = {}
        self.current_title = title or self.current_title
        self.current_block_id = block_id

    def result(self) -> list[Chapter]:
        if self.current_html:
            self.chapters.append((self.current_title, self.current_html, self.current_block_id))
        result = [
            Chapter(title=title, body="\n".join(html_parts), source_block_id=block_id)
            for title, html_parts, block_id in self.chapters
            if html_parts
        ]
        if not result:
            fallback_title = self.metadata.get("title") or self.metadata["doc_id"]
            result = [Chapter(title=fallback_title, body="", source_block_id=None)]
        return result


def chapter_documents(
    document: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]] | None = None,
    inline_images: dict[str, dict[str, Any]] | None = None,
) -> list[Chapter]:
    ctx = _build_render_context(
        document,
        image_assets=image_assets or {},
        inline_images=inline_images or {},
    )
    state = _RenderState(document["metadata"])

    index = 0
    while index < len(ctx.blocks):
        block = ctx.blocks[index]
        if _is_printed_toc_block(block):
            index += 1
        else:
            block_page = _block_page(block)
            should_split = _should_split_chapter(block, ctx)
            if should_split:
                _start_chapter_for_block(state, block, block_page, ctx)
            consumed = _render_visual_page_block(ctx, state, index, block_page)
            if consumed is None:
                consumed = _render_flow_block(ctx, state, index, should_split)
            index += consumed

    return state.result()


def _build_render_context(
    document: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]],
    inline_images: dict[str, dict[str, Any]],
) -> _RenderContext:
    blocks = document["blocks"]
    max_chapter_level = max(
        (b.get("level", 1) for b in blocks if b.get("type") == "heading"), default=1
    )
    return _RenderContext(
        document=document,
        blocks=blocks,
        image_assets=image_assets,
        inline_images=inline_images,
        visual_pages=build_visual_page_set(document),
        full_page_figures=build_full_page_figure_map(document),
        snapshot_asset_ids=build_snapshot_asset_id_map(document),
        page_width=estimate_document_page_width(document),
        toc_split_ids=toc_heading_block_ids(document),
        chapter_level=2 if max_chapter_level >= 2 else 1,
    )


def _is_printed_toc_block(block: dict[str, Any]) -> bool:
    attrs = block.get("attrs") or {}
    return block.get("type") == "toc_item" or attrs.get("role") in {"toc_heading", "toc_entry"}


def _block_page(block: dict[str, Any]) -> int | None:
    source = block.get("source") or {}
    raw_page: Any = source.get("page")
    if isinstance(source.get("pages"), list):
        raw_page = source["pages"][0] if source["pages"] else None
    return raw_page if isinstance(raw_page, int) else None


def _should_split_chapter(block: dict[str, Any], ctx: _RenderContext) -> bool:
    block_id = block.get("block_id")
    block_level = int(block.get("level", 1))
    return (
        block.get("type") == "heading"
        and block_level <= ctx.chapter_level
        and (not ctx.toc_split_ids or block_id in ctx.toc_split_ids or block_level >= 2)
    )


def _start_chapter_for_block(
    state: _RenderState,
    block: dict[str, Any],
    block_page: int | None,
    ctx: _RenderContext,
) -> None:
    text = block.get("text", "")
    state.start_chapter(text.split("\n", 1)[0], block.get("block_id"))
    if block_page in ctx.visual_pages:
        return
    state.append(render_chapter_title_page_html(resolve_chapter_title_view(block)))


def _render_visual_page_block(
    ctx: _RenderContext,
    state: _RenderState,
    index: int,
    block_page: int | None,
) -> int | None:
    if block_page is None or block_page not in ctx.visual_pages:
        return None
    if block_page in state.emitted_visual_pages:
        return 1

    block = ctx.blocks[index]
    page_num = block_page
    has_full_page_figure = page_num in ctx.full_page_figures
    if has_full_page_figure:
        return _render_full_page_figure_anchor(ctx, state, index, page_num)

    state.emitted_visual_pages.add(page_num)
    state.append(_snapshot_or_placeholder(ctx, page_num))
    if block.get("type") != "figure":
        return 1
    return 1 + len(collect_trailing_captions(ctx.blocks, index + 1))


def _render_full_page_figure_anchor(
    ctx: _RenderContext,
    state: _RenderState,
    index: int,
    page_num: int,
) -> int:
    block = ctx.blocks[index]
    if block.get("type") != "figure":
        return 1
    attrs = block.get("attrs") or {}
    if attrs.get("layout_role") != "full_page_image":
        return 1

    state.emitted_visual_pages.add(page_num)
    captions = collect_trailing_captions(ctx.blocks, index + 1)
    state.append(_figure_html(ctx, block, captions))
    return 1 + len(captions)


def _snapshot_or_placeholder(ctx: _RenderContext, page_num: int) -> str:
    snapshot_html = snapshot_figure_html(
        page_num,
        snapshot_asset_ids=ctx.snapshot_asset_ids,
        image_assets=ctx.image_assets,
    )
    if snapshot_html:
        return snapshot_html
    return "\n".join(
        [
            '<figure class="visual-page image-placeholder">',
            '  <div role="img" aria-label="Image">[Image]</div>',
            "</figure>",
        ]
    )


def _render_flow_block(
    ctx: _RenderContext,
    state: _RenderState,
    index: int,
    should_split: bool,
) -> int:
    if should_split:
        return 1
    block = ctx.blocks[index]
    block_type = block["type"]
    if block_type == "heading":
        _render_heading_block(state, block)
    elif block_type == "paragraph":
        state.append(
            f"<p>{render_inline_text(resolve_inline_text(block, state.footnote_counter))}</p>"
        )
    elif block_type == "display_block":
        state.append(
            render_display_block_html(resolve_display_block_view(block, state.footnote_counter))
        )
    elif block_type == "list_item":
        return _render_list_items(ctx, state, index)
    elif block_type == "table" or block_type == "table_continuation":
        _render_table_block(state, block)
    elif block_type == "figure":
        return _render_figure_block(ctx, state, index)
    elif block_type == "caption":
        state.append(_caption_html(block, ctx.blocks, index))
    elif block_type == "footnote":
        _render_footnote_block(state, block)
    return 1


def _render_heading_block(state: _RenderState, block: dict[str, Any]) -> None:
    state.append(render_heading_html(resolve_heading_view(block)))


def _render_list_items(ctx: _RenderContext, state: _RenderState, index: int) -> int:
    state.append(render_list_html(resolve_list_view(ctx.blocks, index, state.footnote_counter)))
    return _list_item_count(ctx.blocks, index)


def _list_item_count(blocks: list[dict[str, Any]], start: int) -> int:
    cursor = start
    while cursor < len(blocks) and blocks[cursor]["type"] == "list_item":
        cursor += 1
    return cursor - start


def _render_table_block(state: _RenderState, block: dict[str, Any]) -> None:
    table = resolve_table_view(block)
    if table is not None:
        state.append(render_table_html(table))


def _render_figure_block(ctx: _RenderContext, state: _RenderState, index: int) -> int:
    block = ctx.blocks[index]
    captions = collect_trailing_captions(ctx.blocks, index + 1)
    state.append(_figure_html(ctx, block, captions))
    return 1 + len(captions)


def _figure_html(
    ctx: _RenderContext,
    block: dict[str, Any],
    captions: list[dict[str, Any]],
) -> str:
    figure = resolve_figure_view(
        block,
        image_assets=ctx.image_assets,
        inline_images=ctx.inline_images,
        captions=captions,
        page_width=ctx.page_width,
    )
    return render_figure_html(figure)


def _caption_html(block: dict[str, Any], blocks: list[dict[str, Any]], index: int) -> str:
    text = block.get("text", "")
    prev_block = blocks[index - 1] if index > 0 else None
    return render_caption_block_html(
        text, follows_figure=bool(prev_block and prev_block["type"] == "figure")
    )


def _render_footnote_block(state: _RenderState, block: dict[str, Any]) -> None:
    state.append(render_footnote_html(resolve_footnote_view(block)))
