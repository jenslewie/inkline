from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from inkline.canonical import strip_footnote_marker
from inkline.epub._assets import asset_image_name
from inkline.epub._chapter import Chapter


def _build_visual_page_set(document: dict[str, Any]) -> set[int]:
    """Return the set of physical_page numbers where snapshot.required is true.

    These are the pages that need a full-page visual image in the EPUB
    instead of reflow text.
    """
    pages = document.get("pages", [])
    result: set[int] = set()
    for p in pages:
        if not isinstance(p, dict):
            continue
        snapshot = p.get("snapshot")
        if isinstance(snapshot, dict) and snapshot.get("required"):
            pp = p.get("physical_page")
            if isinstance(pp, int):
                result.add(pp)
    return result


def _build_full_page_figure_map(document: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Map physical_page -> full_page_image figure block for pages that have one."""
    result: dict[int, dict[str, Any]] = {}
    for block in document.get("blocks", []):
        if block.get("type") != "figure":
            continue
        attrs = block.get("attrs") or {}
        if attrs.get("layout_role") != "full_page_image":
            continue
        source = block.get("source") or {}
        page = source.get("page")
        if isinstance(page, int):
            result[page] = block
    return result


def _build_snapshot_asset_id_map(document: dict[str, Any]) -> dict[int, str]:
    """Map physical_page -> snapshot asset_id from canonical page metadata.

    Uses the explicit asset_id from pages[*].snapshot.asset_id rather
    than a hardcoded naming convention.
    """
    pages = document.get("pages", [])
    result: dict[int, str] = {}
    for p in pages:
        if not isinstance(p, dict):
            continue
        snapshot = p.get("snapshot")
        if isinstance(snapshot, dict) and snapshot.get("required"):
            pp = p.get("physical_page")
            asset_id = snapshot.get("asset_id")
            if isinstance(pp, int) and isinstance(asset_id, str):
                result[pp] = asset_id
    return result


def _estimate_document_page_width(document: dict[str, Any]) -> float | None:
    """Estimate the canonical page coordinate width from block geometry."""
    right_edges: list[float] = []
    for block in document.get("blocks", []):
        source = block.get("source") or {}
        bbox = source.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            continue
        try:
            right = float(bbox[2])
        except (TypeError, ValueError):
            continue
        if right > 0:
            right_edges.append(right)
    if not right_edges:
        return None
    right_edges.sort()
    index = min(len(right_edges) - 1, int(len(right_edges) * 0.95))
    return max(1.0, right_edges[index])


def chapter_documents(
    document: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]] | None = None,
    inline_images: dict[str, dict[str, Any]] | None = None,
) -> list[Chapter]:
    image_assets = image_assets or {}
    inline_images = inline_images or {}
    visual_pages = _build_visual_page_set(document)
    full_page_figures = _build_full_page_figure_map(document)
    snapshot_asset_ids = _build_snapshot_asset_id_map(document)
    page_width = _estimate_document_page_width(document)

    chapters: list[tuple[str, list[str], str | None]] = []
    current_title = document["metadata"].get("title") or document["metadata"]["doc_id"]
    current_block_id: str | None = None
    current_html: list[str] = []

    # Track which visual pages have already emitted their full-page image
    # so that we never output the same page image twice.
    emitted_visual_pages: set[int] = set()

    # Per-chapter footnote counter (resets on each new chapter split)
    footnote_counter: dict[int, int] = {}  # target_note_id -> chapter-local number

    i = 0
    blocks = document["blocks"]
    from inkline.epub._nav import toc_heading_block_ids

    toc_split_ids = toc_heading_block_ids(document)
    max_chapter_level = max(
        (b.get("level", 1) for b in blocks if b.get("type") == "heading"), default=1
    )
    # Use level 2 as the chapter-split threshold when the document has level-2
    # headings (which typically represent the main chapters), so that each
    # chapter becomes its own EPUB chapter.  When there are only level-1
    # headings, split on level 1.
    chapter_level = 2 if max_chapter_level >= 2 else 1
    while i < len(blocks):
        block = blocks[i]
        block_type = block["type"]
        text = block.get("text", "")
        block_id = block.get("block_id")
        block_level = int(block.get("level", 1))
        block_attrs = block.get("attrs") or {}
        block_role = block_attrs.get("role")

        # === Printed TOC suppression ===
        # Suppress toc_item blocks AND any block explicitly tagged as
        # part of the printed TOC (toc_heading, toc_entry).  Nav.xhtml
        # already provides EPUB navigation.
        if block_type == "toc_item" or block_role in {"toc_heading", "toc_entry"}:
            i += 1
            continue

        # Determine the physical page of this block
        source = block.get("source") or {}
        block_page_raw: Any = source.get("page")
        # For blocks with multi-page source, take the first page
        if isinstance(source.get("pages"), list):
            block_page_raw = source["pages"][0] if source["pages"] else None
        # Type-narrow: only proceed with visual-page logic for int page numbers
        block_page: int | None = block_page_raw if isinstance(block_page_raw, int) else None

        # Pre-compute visual-page status so both chapter-split and
        # visual-page handling can use it.
        is_on_visual_page = block_page is not None and block_page in visual_pages

        # === Chapter-split check (BEFORE visual page early-exit) ===
        # Headings that represent chapter boundaries must be processed
        # regardless of whether they sit on a visual page, otherwise
        # the nav.xhtml chapter structure becomes misaligned.
        should_split = (
            block_type == "heading"
            and block_level <= chapter_level
            # Never split on front-matter title-page headings (book title,
            # imprint, etc.) that appear before the first TOC-referenced
            # heading.  Those small fragments are better kept as a single
            # "front matter" chapter.
            and (not toc_split_ids or block_id in toc_split_ids or block_level >= 2)
        )
        if should_split:
            if current_html:
                chapters.append((current_title, current_html, current_block_id))
                current_html = []
            # Reset chapter-local footnote counter
            footnote_counter = {}
            current_title = text.split("\n", 1)[0] or current_title
            current_block_id = block_id
            # Only append heading text when this block is NOT on a visual
            # page.  Visual pages replace all body content (including the
            # heading) with a snapshot or full-page figure, but the chapter
            # boundary must still be recorded so nav.xhtml links are correct.
            if not is_on_visual_page:
                heading_text = escape(text).replace("\n", "<br/>\n")
                heading_tag = f"<h{block_level}>{heading_text}</h{block_level}>"
                # For chapter-splitting headings, wrap in a title-page div
                # with a page break after the heading.
                current_html.append(f'<div class="chapter-title-page">\n  {heading_tag}\n</div>')

        # === Visual page early-exit ===
        # If this block belongs to a visual page whose image has already
        # been emitted, skip the block entirely (regardless of type).
        if block_page is not None and block_page in emitted_visual_pages:
            i += 1
            continue

        # === Visual page handling ===
        is_on_visual_page = block_page is not None and block_page in visual_pages

        if is_on_visual_page:
            assert block_page is not None
            page_num: int = block_page

            # If this page has a full_page_image figure anchor, we must
            # emit the image at the figure's position in the reading flow.
            # Blocks before the figure anchor on this page are skipped
            # (including already-split headings, which serve as chapter
            # boundaries but whose body content is replaced by the figure).
            has_full_page_figure = page_num in full_page_figures

            if has_full_page_figure and block_type != "figure":
                i += 1
                continue

            if has_full_page_figure and block_type == "figure":
                fig_attrs = block.get("attrs") or {}
                if fig_attrs.get("layout_role") == "full_page_image":
                    emitted_visual_pages.add(page_num)
                    captions = _collect_trailing_captions(blocks, i + 1)
                    current_html.append(
                        _figure_html(
                            block,
                            image_assets=image_assets,
                            inline_images=inline_images,
                            captions=captions,
                            page_width=page_width,
                        )
                    )
                    i += len(captions)
                    i += 1
                    continue
                else:
                    i += 1
                    continue

            # No full_page_image figure on this page — emit the snapshot
            # image and skip the block.
            emitted_visual_pages.add(page_num)
            snapshot_html = _snapshot_figure_html(
                page_num, document, snapshot_asset_ids=snapshot_asset_ids, image_assets=image_assets
            )
            if snapshot_html:
                current_html.append(snapshot_html)
            else:
                # Snapshot asset not found — produce a clean placeholder so
                # the page position is not silently blank.
                current_html.append(
                    '<figure class="visual-page image-placeholder">'
                    '<div role="img" aria-label="Image">[Image]</div>'
                    "</figure>"
                )
            # Skip this block — the snapshot (or placeholder) replaces it.
            # Also skip any trailing captions if the block is a figure.
            if block_type == "figure":
                captions = _collect_trailing_captions(blocks, i + 1)
                i += len(captions)
            i += 1
            continue

        # === Normal block rendering (not on a visual page) ===
        # If this block was already processed via should_split, skip
        # the normal rendering branch.
        if should_split:
            i += 1
            continue
        if block_type == "heading":
            level = min(max(block_level, 2), 6)
            heading_text = escape(text).replace("\n", "<br/>\n")
            current_html.append(f"<h{level}>{heading_text}</h{level}>")
        elif block_type == "paragraph":
            current_html.append(f"<p>{_text_html(block, footnote_counter)}</p>")
        elif block_type == "display_block":
            current_html.append(_display_block_html(block, footnote_counter))
        elif block_type == "list_item":
            items = []
            while i < len(blocks) and blocks[i]["type"] == "list_item":
                items.append(f"<li>{_text_html(blocks[i], footnote_counter)}</li>")
                i += 1
            current_html.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif block_type == "table" or block_type == "table_continuation":
            html = _table_html(block)
            if html is not None:
                current_html.append(html)
        elif block_type == "figure":
            captions = _collect_trailing_captions(blocks, i + 1)
            current_html.append(
                _figure_html(
                    block,
                    image_assets=image_assets,
                    inline_images=inline_images,
                    captions=captions,
                    page_width=page_width,
                )
            )
            i += len(captions)
        elif block_type == "caption":
            current_html.append(_caption_html(block, blocks, i))
        elif block_type == "footnote":
            attrs = block.get("attrs") or {}
            note_id = attrs.get("note_id") or block.get("block_id")
            id_attr = f' id="{escape(str(note_id), quote=True)}"' if note_id else ""
            stripped_text = strip_footnote_marker(text, attrs)
            current_html.append(
                f'<aside epub:type="footnote"{id_attr}><p>{escape(stripped_text)}</p></aside>'
            )

        i += 1

    if current_html:
        chapters.append((current_title, current_html, current_block_id))
    result = [
        Chapter(title=title, body="\n".join(html_parts), source_block_id=block_id)
        for title, html_parts, block_id in chapters
        if html_parts
    ]
    # Ensure at least one chapter exists — an EPUB with zero spine items
    # is structurally invalid.  This can happen when all blocks belong to
    # the printed TOC (toc_item, toc_heading, toc_entry) and are suppressed.
    if not result:
        fallback_title = document["metadata"].get("title") or document["metadata"]["doc_id"]
        result = [Chapter(title=fallback_title, body="", source_block_id=None)]
    return result


def _snapshot_figure_html(
    page_num: int,
    document: dict[str, Any],
    *,
    snapshot_asset_ids: dict[int, str] | None = None,
    image_assets: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Return a <figure> with the page snapshot image for a visual page.

    Uses the canonical snapshot.asset_id from page metadata rather than
    a hardcoded naming convention.

    Returns None if no snapshot asset is found.
    """
    image_assets = image_assets or {}
    snapshot_asset_ids = snapshot_asset_ids or {}
    # Resolve the snapshot asset_id from canonical page metadata
    asset_id = snapshot_asset_ids.get(page_num)
    if not asset_id:
        # Fallback to convention-based name if no metadata available
        asset_id = f"page-{page_num:04d}-snapshot"
    asset = image_assets.get(asset_id)
    if not asset:
        return None
    if not Path(asset["path"]).exists():
        return None
    image_name = asset_image_name(asset)
    alt = f"Page {page_num}"
    return (
        '<figure class="visual-page">'
        f'<img src="images/{escape(image_name, quote=True)}" alt="{escape(alt, quote=True)}"/>'
        "</figure>"
    )


def _text_html(
    block: dict[str, Any],
    footnote_counter: dict[int, int] | None = None,
) -> str:
    """Render block text with inline_runs support, including chapter-local
    footnote renumbering."""
    # Only create a new dict when None is passed, NOT when an empty dict
    # is passed — the caller owns the dict and mutations must flow back.
    if footnote_counter is None:
        footnote_counter = {}
    raw_runs = (block.get("attrs") or {}).get("inline_runs")
    if raw_runs and isinstance(raw_runs, list):
        return _inline_runs_html(block, raw_runs, footnote_counter=footnote_counter)

    text = block.get("text", "")
    if not text:
        return ""
    return escape(text)


def _inline_runs_html(
    block: dict[str, Any],
    runs: list[dict[str, Any]],
    *,
    footnote_counter: dict[int, int],
) -> str:
    parts: list[str] = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        if run.get("type") == "text":
            parts.append(escape(str(run.get("text", ""))))
            continue
        if run.get("type") != "note_ref":
            continue
        marker = str(run.get("marker") or "")
        if not marker:
            continue
        target = run.get("target_note_id")
        # Chapter-local renumbering: assign a sequential number per chapter
        if target is not None:
            local_num = footnote_counter.get(target)
            if local_num is None:
                local_num = len(footnote_counter) + 1
                footnote_counter[target] = local_num
            display_marker = str(local_num)
        else:
            display_marker = marker

        ref_id = f"{block.get('block_id') or 'ref'}_note_ref_{index}"
        if target:
            parts.append(
                f'<a epub:type="noteref" href="#{escape(str(target), quote=True)}" '
                f'id="{escape(ref_id, quote=True)}"><sup>{escape(display_marker)}</sup></a>'
            )
        else:
            parts.append(f"<sup>{escape(display_marker)}</sup>")
    return "".join(parts)


def _figure_html(
    block: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]] | None = None,
    inline_images: dict[str, dict[str, Any]] | None = None,
    captions: list[dict[str, Any]] | None = None,
    page_width: float | None = None,
) -> str:
    text = (block.get("text") or "").strip()
    attrs = block.get("attrs") or {}
    image_assets = image_assets or {}
    inline_images = inline_images or {}
    captions = captions or []
    block_id = block.get("block_id", "")
    image_id = attrs.get("image_id")
    image_asset = image_assets.get(image_id) if image_id else None
    inline_img = inline_images.get(block_id)
    image_dimensions = _image_pixel_dimensions(image_asset or inline_img)
    image_attrs = _figure_image_attrs(block, page_width)

    # Collect caption segments from all sources (figure text, attrs.captions,
    # trailing caption blocks).  Each source part is itself split on newline
    # so that every visual line becomes a paragraph.
    segments: list[str] = []
    all_parts: list[str] = []
    if text:
        all_parts.append(escape(text))
    attrs_captions = attrs.get("captions")
    if isinstance(attrs_captions, list):
        for cap in attrs_captions:
            if isinstance(cap, str) and cap:
                all_parts.append(escape(cap))
    for cap_block in captions:
        cap_text = cap_block.get("text", "")
        if cap_text:
            all_parts.append(escape(cap_text))
    for part in all_parts:
        for line in part.replace("\\n", "\n").split("\n"):
            stripped = line.strip()
            if stripped:
                segments.append(stripped)

    has_caption = len(segments) > 0
    figure_classes = ["figure-block"]
    if _should_use_full_width_image(
        has_caption=has_caption, image_dimensions=image_dimensions
    ):
        figure_classes.append("figure-fullwidth")
    if has_caption:
        figure_classes.append("has-caption")
    figure_class_attr = ' class="' + " ".join(figure_classes) + '"'

    if has_caption:
        cap_parts: list[str] = []
        cap_parts.append(f'<p class="caption-title">{segments[0]}</p>')
        for seg in segments[1:]:
            cap_parts.append(f'<p class="caption-body">{seg}</p>')
        caption_html = "<figcaption>" + "".join(cap_parts) + "</figcaption>"
    else:
        caption_html = ""

    if image_asset and Path(image_asset["path"]).exists():
        image_name = asset_image_name(image_asset)
        alt = text or ""
        image_html = (
            f'<img src="images/{escape(image_name, quote=True)}" '
            f'alt="{escape(alt, quote=True)}"{image_attrs}/>'
        )
        return _figure_with_page_break(
            f"<figure{figure_class_attr}>"
            f"{image_html}"
            f"\n  {caption_html}\n"
            "</figure>"
        )

    if inline_img:
        epub_name = inline_img["epub_name"]
        alt = text or ""
        image_html = (
            f'<img src="images/{escape(epub_name, quote=True)}" '
            f'alt="{escape(alt, quote=True)}"{image_attrs}/>'
        )
        return _figure_with_page_break(
            f"<figure{figure_class_attr}>"
            f"{image_html}"
            f"\n  {caption_html}\n"
            "</figure>"
        )

    # No image available — produce a minimal placeholder without debug text
    if has_caption:
        return _figure_with_page_break(
            f'<figure class="image-placeholder figure-block has-caption">'
            '<div role="img" aria-label="Image">[Image]</div>'
            f"\n  {caption_html}\n"
            "</figure>"
        )
    return _figure_with_page_break(
        '<figure class="image-placeholder figure-block">'
        '<div role="img" aria-label="Image">[Image]</div>'
        "</figure>"
    )


def _figure_with_page_break(figure_html: str) -> str:
    return '<div class="figure-page-break" aria-hidden="true"></div>\n' + figure_html


def _figure_image_attrs(block: dict[str, Any], page_width: float | None) -> str:
    if not page_width or page_width <= 0:
        return ""
    attrs = block.get("attrs") or {}
    bbox = attrs.get("image_bbox") or (block.get("source") or {}).get("bbox")
    width = _bbox_width(bbox)
    if width <= 0:
        return ""
    percent = min(100.0, max(1.0, width / page_width * 100.0))
    return f' style="max-width: {_format_percent(percent)}%;"'


def _bbox_width(bbox: Any) -> float:
    if not isinstance(bbox, list) or len(bbox) < 4:
        return 0.0
    try:
        left = float(bbox[0])
        right = float(bbox[2])
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, right - left)


def _format_percent(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _image_pixel_dimensions(image_asset: dict[str, Any] | None) -> tuple[int, int] | None:
    if not image_asset:
        return None
    width = image_asset.get("width")
    height = image_asset.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return width, height
    path = image_asset.get("path")
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return _png_dimensions(data) or _jpeg_dimensions(data)


def _should_use_full_width_image(
    *, has_caption: bool, image_dimensions: tuple[int, int] | None
) -> bool:
    if has_caption or not image_dimensions:
        return False
    width, height = image_dimensions
    return width > 0 and height > 0 and width / height >= 0.6


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return None
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            return None
        if marker in sof_markers and segment_length >= 7:
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return width, height
        offset += segment_length
    return None


def _collect_trailing_captions(blocks: list[dict[str, Any]], start: int) -> list[dict[str, Any]]:
    captions: list[dict[str, Any]] = []
    i = start
    while i < len(blocks) and blocks[i]["type"] == "caption":
        captions.append(blocks[i])
        i += 1
    return captions


def _is_continuation_marker_text(text: str) -> bool:
    """Check whether a note string is a table continuation marker.

    Handles parenthesized/bracketed forms like "(接上页)", "（续表）", "【接下页】"
    by stripping surrounding delimiters before matching the core keyword.
    """
    t = text.strip()
    t = t.strip("()（）[]【】")
    return t in {"接上页", "接下页", "续表", "续上表"}


def _table_html(block: dict[str, Any]) -> str | None:
    attrs = block.get("attrs") or {}
    html = attrs.get("html", "")
    table_part: str | None = None
    if html and isinstance(html, str) and html.strip():
        sanitized = _sanitize_html_fragment(html)
        if sanitized is not None:
            table_part = _apply_cell_alignments(sanitized, attrs.get("cell_alignments"))
    if table_part is None:
        text = block.get("text", "")
        if text.strip():
            rows: list[str] = []
            for line in text.split("\n"):
                line = line.strip()
                if not line or set(line) <= {"|", "-", ":", " "}:
                    continue
                cells = [escape(c.strip()) for c in line.split("|")]
                cells = [c for c in cells if c]
                if cells:
                    rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            if rows:
                table_part = "<table>" + "".join(rows) + "</table>"
                table_part = _apply_cell_alignments(table_part, attrs.get("cell_alignments"))

    if table_part is None:
        return None

    # Append table notes (structural source/attribution notes) after the table.
    # Prefer table_notes (excludes continuation markers); fall back to footnotes.
    table_notes = attrs.get("table_notes") or attrs.get("footnotes") or []
    # Filter out continuation-marker text that may have slipped through.
    notes = [n for n in table_notes if n and not _is_continuation_marker_text(n)]
    if notes:
        notes_html = "".join(f'<p class="table-note">{escape(n)}</p>' for n in notes)
        return f'{table_part}\n<div class="table-notes">{notes_html}</div>'
    return table_part


def _apply_cell_alignments(html: str, cell_alignments: Any) -> str:
    """Apply cell alignment classes to <td>/<th> elements.

    cell_alignments dict keys (all optional):
      "default": str — fallback alignment for all cells
      "rows": [[row_index, alignment], ...] — alignment for entire rows
      "cells": [[row, col, alignment], ...] — alignment for specific cells

    Returns the HTML unchanged when cell_alignments is None/empty.
    Alignment values: "center", "right", "left".
    """
    if not cell_alignments:
        return html

    default = cell_alignments.get("default", "")
    rows_map: dict[int, str] = {}
    for row_alignment in cell_alignments.get("rows") or []:
        if isinstance(row_alignment, (list, tuple)) and len(row_alignment) >= 2:
            rows_map[row_alignment[0]] = row_alignment[1]

    cells_map: dict[tuple[int, int], str] = {}
    for cell_alignment in cell_alignments.get("cells") or []:
        if isinstance(cell_alignment, (list, tuple)) and len(cell_alignment) >= 3:
            cells_map[(cell_alignment[0], cell_alignment[1])] = cell_alignment[2]

    row = 0
    col = 0
    result: list[str] = []
    tag_pattern = re.compile(r"(<tr[^>]*>)|(<(t[dh])((?:\s[^>]*?)?)>)", re.I)
    pos = 0
    for m in tag_pattern.finditer(html):
        result.append(html[pos : m.start()])
        if m.group(1):
            # <tr> tag: advance row, reset column
            if row > 0 or col > 0:
                row += 1
                col = 0
            # First row starts at row 0 — only advance after processing row cells.
            # row is already 0 at the start, so the first <tr> leaves it at 0.
            result.append(m.group(1))
        elif m.group(2):
            # <td> or <th> tag: determine alignment
            tag = m.group(3)
            attrs_str = m.group(4) or ""

            alignment = cells_map.get((row, col)) or rows_map.get(row) or default
            col += 1

            if alignment in {"left", "center", "right"}:
                class_match = re.search(r'\bclass\s*=\s*(["\'])(.*?)\1', attrs_str)
                if class_match:
                    quote = class_match.group(1)
                    existing = class_match.group(2)
                    merged = f"{existing} td-align-{alignment}"
                    full_class = f"class={quote}{merged}{quote}"
                    new_attrs = (
                        attrs_str[: class_match.start()]
                        + full_class
                        + attrs_str[class_match.end() :]
                    )
                    result.append(f"<{tag}{new_attrs}>")
                else:
                    result.append(f'<{tag}{attrs_str} class="td-align-{alignment}">')
            else:
                result.append(f"<{tag}{attrs_str}>")
        pos = m.end()
    result.append(html[pos:])
    return "".join(result)


_XML_ENTITIES = {"amp", "lt", "gt", "apos", "quot"}

_HTML_NAMED_ENTITIES: dict[str, str] = {
    "nbsp": " ",
    "copy": "©",
    "reg": "®",
    "trade": "™",
    "mdash": "—",
    "ndash": "–",
    "lsquo": "‘",
    "rsquo": "’",
    "ldquo": "“",
    "rdquo": "”",
    "bull": "•",
    "hellip": "…",
    "laquo": "«",
    "raquo": "»",
    "middot": "·",
    "times": "×",
    "divide": "÷",
    "deg": "°",
    "plusmn": "±",
    "para": "¶",
    "sect": "§",
    "euro": "€",
    "pound": "£",
    "yen": "¥",
    "cent": "¢",
    "rarr": "→",
    "larr": "←",
    "uarr": "↑",
    "darr": "↓",
    "infin": "∞",
    "ne": "≠",
    "le": "≤",
    "ge": "≥",
    "micro": "µ",
}


def _sanitize_html_fragment(html: str) -> str | None:
    try:
        ET.fromstring(html)
        return html
    except ET.ParseError:
        pass
    fixed = re.sub(
        r"&([a-zA-Z][a-zA-Z0-9]*);",
        lambda m: (
            f"&{m.group(1)};"
            if m.group(1) in _XML_ENTITIES
            else escape(_HTML_NAMED_ENTITIES.get(m.group(1), f"&{m.group(1)};"))
        ),
        html,
    )
    fixed = re.sub(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#x[0-9a-fA-F]+);)", "&amp;", fixed)
    fixed = re.sub(
        r"<(br|hr|img|input|meta|link)(\s[^>]*)?>",
        lambda m: f"<{m.group(1)}{m.group(2) or ''}/>",
        fixed,
    )
    try:
        ET.fromstring(fixed)
        return fixed
    except ET.ParseError:
        return None


def _caption_html(block: dict[str, Any], blocks: list[dict[str, Any]], index: int) -> str:
    text = block.get("text", "")
    prev_block = blocks[index - 1] if index > 0 else None
    if prev_block and prev_block["type"] == "figure":
        # Legacy path for figure-trailing captions not consumed by
        # _collect_trailing_captions — structure multi-line text.
        return _figcaption_structured(text)
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) <= 1:
        return f'<p class="caption">{escape(text)}</p>'
    parts: list[str] = []
    parts.append(f'<p class="caption-title">{escape(lines[0])}</p>')
    for line in lines[1:]:
        parts.append(f'<p class="caption-body">{escape(line)}</p>')
    return f'<div class="caption">{"".join(parts)}</div>'


def _figcaption_structured(text: str) -> str:
    """Render raw text as structured <figcaption> with caption-title/caption-body.
    Handles escaping internally — callers should pass unescaped text."""
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) <= 1:
        return f"<figcaption>{escape(text)}</figcaption>"
    parts: list[str] = []
    parts.append(f'<p class="caption-title">{escape(lines[0])}</p>')
    for line in lines[1:]:
        parts.append(f'<p class="caption-body">{escape(line)}</p>')
    return f"<figcaption>{''.join(parts)}</figcaption>"


def _display_block_html(
    block: dict[str, Any],
    footnote_counter: dict[int, int] | None = None,
) -> str:
    attrs = block.get("attrs") or {}
    classes = ["display-block"]
    layout_role = attrs.get("layout_role")
    if layout_role in {"standalone_display_page", "standalone_display_group"}:
        classes.append("display-block-standalone")
    raw_style_hints = attrs.get("style_hints")
    style_hints = raw_style_hints if isinstance(raw_style_hints, dict) else {}
    if (
        layout_role == "flush_right_terminal_block"
        or attrs.get("alignment") == "right"
        or style_hints.get("text_align") == "right"
    ):
        classes.append("display-block-signature")
    class_attr = " ".join(classes)

    rendered = _text_html(block, footnote_counter)
    if not rendered:
        return f'<blockquote class="{escape(class_attr, quote=True)}"></blockquote>'
    paragraphs = []
    for segment in rendered.split("\n"):
        stripped = segment.strip()
        if stripped:
            paragraphs.append(f'<div class="display-block-paragraph">{stripped}</div>')
    return (
        f'<blockquote class="{escape(class_attr, quote=True)}">{"".join(paragraphs)}</blockquote>'
    )
