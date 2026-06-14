from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from inkline.epub._assets import asset_image_name
from inkline.epub._chapter import Chapter


def chapter_documents(
    document: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]] | None = None,
    inline_images: dict[str, dict[str, Any]] | None = None,
) -> list[Chapter]:
    image_assets = image_assets or {}
    inline_images = inline_images or {}
    chapters: list[tuple[str, list[str], str | None]] = []
    current_title = document["metadata"].get("title") or document["metadata"]["doc_id"]
    current_block_id: str | None = None
    current_html: list[str] = []

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
            current_title = text.split("\n", 1)[0] or current_title
            current_block_id = block_id
            current_html.append(f"<h{block_level}>{escape(text)}</h{block_level}>")
        elif block_type == "heading":
            level = min(max(block_level, 2), 6)
            current_html.append(f"<h{level}>{escape(text)}</h{level}>")
        elif block_type == "paragraph":
            current_html.append(f"<p>{_text_html(block)}</p>")
        elif block_type == "display_block":
            current_html.append(_display_block_html(block))
        elif block_type == "list_item":
            items = []
            while i < len(blocks) and blocks[i]["type"] == "list_item":
                items.append(f"<li>{_text_html(blocks[i])}</li>")
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
                    block, image_assets=image_assets, inline_images=inline_images, captions=captions
                )
            )
            i += len(captions)
        elif block_type == "caption":
            current_html.append(_caption_html(block, blocks, i))
        elif block_type == "footnote":
            attrs = block.get("attrs") or {}
            note_id = attrs.get("note_id") or block.get("block_id")
            id_attr = f' id="{escape(str(note_id), quote=True)}"' if note_id else ""
            current_html.append(
                f'<aside epub:type="footnote"{id_attr}><p>{escape(text)}</p></aside>'
            )
        elif block_type == "toc_item":
            pass
        i += 1

    if current_html:
        chapters.append((current_title, current_html, current_block_id))
    if not chapters:
        chapters.append((current_title, ["<p></p>"], None))

    return [
        Chapter(title=title, body="\n".join(html_parts), source_block_id=block_id)
        for title, html_parts, block_id in chapters
    ]


def _text_html(block: dict[str, Any]) -> str:
    attrs = block.get("attrs") or {}
    runs = attrs.get("inline_runs")
    if not isinstance(runs, list) or not any(
        isinstance(run, dict) and run.get("type") == "note_ref" for run in runs
    ):
        return escape(str(block.get("text", "")))
    parts: list[str] = []
    for index, run in enumerate(runs, 1):
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
        ref_id = f"{block.get('block_id') or 'ref'}_note_ref_{index}"
        if target:
            parts.append(
                f'<a epub:type="noteref" href="#{escape(str(target), quote=True)}" '
                f'id="{escape(ref_id, quote=True)}"><sup>{escape(marker)}</sup></a>'
            )
        else:
            parts.append(f"<sup>{escape(marker)}</sup>")
    return "".join(parts)


def _figure_html(
    block: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]] | None = None,
    inline_images: dict[str, dict[str, Any]] | None = None,
    captions: list[dict[str, Any]] | None = None,
) -> str:
    text = (block.get("text") or "").strip()
    source = block.get("source") or {}
    attrs = block.get("attrs") or {}
    image_assets = image_assets or {}
    inline_images = inline_images or {}
    captions = captions or []
    image_id = attrs.get("image_id")
    image_asset = image_assets.get(image_id) if image_id else None
    page = source.get("page")
    bbox = source.get("bbox")
    raw_id = attrs.get("parser_raw_id")

    details = []
    if page is not None:
        details.append(f"page {page}")
    if bbox:
        details.append("bbox " + ", ".join(_format_number(value) for value in bbox))
    if raw_id:
        details.append(str(raw_id))
    fallback = "Image placeholder"
    if details:
        fallback += " (" + "; ".join(details) + ")"

    caption = text or fallback

    caption_parts: list[str] = []
    if caption and caption != fallback:
        caption_parts.append(escape(caption))
    for cap_block in captions:
        cap_text = cap_block.get("text", "")
        if cap_text:
            caption_parts.append(escape(cap_text))
    caption_html = (
        "<figcaption>" + "<br/>".join(caption_parts) + "</figcaption>" if caption_parts else ""
    )
    if not caption_html:
        caption_html = f"<figcaption>{escape(fallback)}</figcaption>"

    if image_asset and Path(image_asset["path"]).exists():
        image_name = asset_image_name(image_asset)
        alt = text or fallback
        return (
            "<figure>"
            f'<img src="images/{escape(image_name, quote=True)}" alt="{escape(alt, quote=True)}"/>'
            f"{caption_html}"
            "</figure>"
        )

    block_id = block.get("block_id", "")
    inline_img = inline_images.get(block_id)
    if inline_img:
        epub_name = inline_img["epub_name"]
        alt = text or fallback
        return (
            "<figure>"
            f'<img src="images/{escape(epub_name, quote=True)}" alt="{escape(alt, quote=True)}"/>'
            f"{caption_html}"
            "</figure>"
        )

    return (
        '<figure class="image-placeholder">'
        '<div role="img" aria-label="Image placeholder">[Image]</div>'
        f"{caption_html}"
        "</figure>"
    )


def _collect_trailing_captions(blocks: list[dict[str, Any]], start: int) -> list[dict[str, Any]]:
    captions: list[dict[str, Any]] = []
    i = start
    while i < len(blocks) and blocks[i]["type"] == "caption":
        captions.append(blocks[i])
        i += 1
    return captions


def _table_html(block: dict[str, Any]) -> str | None:
    attrs = block.get("attrs") or {}
    html = attrs.get("html", "")
    if html and isinstance(html, str) and html.strip():
        sanitized = _sanitize_html_fragment(html)
        if sanitized is not None:
            return sanitized
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
            return "<table>" + "".join(rows) + "</table>"
    return None


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
        return f"<figcaption>{escape(text)}</figcaption>"
    return f'<p class="caption">{escape(text)}</p>'


def _display_block_html(block: dict[str, Any]) -> str:
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
        classes.append("display-block-right")
    class_attr = " ".join(classes)
    return f'<blockquote class="{escape(class_attr, quote=True)}">{_text_html(block)}</blockquote>'


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.1f}"
