from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from inkline.epub._assets import asset_image_name
from inkline.epub._chapter import Chapter

# Superscript-to-digit translation table, matching the normalization
# used in the parser's normalize_note_marker().
_SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

# Required-delimiter pattern for footnote marker stripping.
# After a marker, at least one delimiter must follow to avoid false
# positives (e.g. "3rd" is NOT stripped when marker is "3").
# Covers: whitespace, period/dot, comma, Chinese punctuation (、．),
# closing paren (ASCII and fullwidth ), and end-of-string.
_DELIMITER_PATTERN = r"(?:[\s.、．,)）]\s*|$)"


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
                current_html.append(
                    f'<div class="chapter-title-page">\n  {heading_tag}\n</div>'
                )

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
            stripped_text = _strip_footnote_marker(text, attrs)
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
) -> str:
    text = (block.get("text") or "").strip()
    source = block.get("source") or {}
    attrs = block.get("attrs") or {}
    image_assets = image_assets or {}
    inline_images = inline_images or {}
    captions = captions or []
    image_id = attrs.get("image_id")
    image_asset = image_assets.get(image_id) if image_id else None

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
        return (
            f"<figure{figure_class_attr}>"
            f'<img src="images/{escape(image_name, quote=True)}" alt="{escape(alt, quote=True)}"/>'
            f"\n  {caption_html}\n"
            "</figure>"
        )

    block_id = block.get("block_id", "")
    inline_img = inline_images.get(block_id)
    if inline_img:
        epub_name = inline_img["epub_name"]
        alt = text or ""
        return (
            f"<figure{figure_class_attr}>"
            f'<img src="images/{escape(epub_name, quote=True)}" alt="{escape(alt, quote=True)}"/>'
            f"\n  {caption_html}\n"
            "</figure>"
        )

    # No image available — produce a minimal placeholder without debug text
    if has_caption:
        return (
            f'<figure class="image-placeholder figure-block has-caption">'
            '<div role="img" aria-label="Image">[Image]</div>'
            f"\n  {caption_html}\n"
            "</figure>"
        )
    return (
        '<figure class="image-placeholder figure-block">'
        '<div role="img" aria-label="Image">[Image]</div>'
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


def _strip_footnote_marker(text: str, attrs: dict[str, Any]) -> str:
    """Strip the leading original note marker from footnote block text.

    Footnotes from the canonical pipeline often include the original
    marker (e.g. "³ Lothar..." or "3. Note text") as the first word
    or two.  The EPUB noteref links provide chapter-local numbering,
    so the duplicate leading marker should be removed.

    When attrs.note_marker is available (the most reliable source), it
    is used.  Otherwise a local heuristic strips a leading sequence
    matching common marker patterns.
    """
    marker = attrs.get("note_marker")
    if isinstance(marker, str) and marker:
        marker_stripped = marker.strip()
        if not marker_stripped:
            pass  # empty marker — skip to fallback
        else:
            # Normalize the leading superscript run in the text to its
            # digit equivalent, then match the marker against the
            # normalised form.  This handles multi-digit superscript
            # sequences (e.g. ¹² → "12") and single superscripts
            # (³ → "3") equally.
            m = re.match(
                r"^([¹²³⁴⁵⁶⁷⁸⁹⁰]+)",
                text,
            )
            if m:
                normalized_head = m.group(1).translate(_SUPERSCRIPT_MAP)
                if normalized_head == marker_stripped:
                    # Consume the superscript run plus delimiter
                    delim_m = re.match(
                        rf"^[¹²³⁴⁵⁶⁷⁸⁹⁰]+{_DELIMITER_PATTERN}",
                        text,
                    )
                    if delim_m:
                        rest = text[delim_m.end():]
                        if rest:
                            return rest
            # Literal marker form — must be followed by a required delimiter
            # so "3rd" is NOT stripped when marker is "3".
            pattern = rf"^({re.escape(marker_stripped)}){_DELIMITER_PATTERN}"
            m2 = re.match(pattern, text)
            if m2:
                rest = text[m2.end():]
                if rest:
                    return rest
    # Fallback: strip a leading numeric/symbol/superscript marker
    # Covers: plain digits, circled/boxed digits (①-⓿❶-➓),
    # superscript digits (¹²³⁴⁵⁶⁷⁸⁹⁰), and common reference
    # symbols (*, †, ‡, §).  A required delimiter prevents false
    # positives like stripping "3" from "3rd edition".
    m = re.match(
        rf"^[\d①-⓿❶-➓¹²³⁴⁵⁶⁷⁸⁹⁰\*†‡§]+{_DELIMITER_PATTERN}",
        text,
    )
    if m and m.end() > 0:
        rest = text[m.end():]
        if rest:
            return rest
    return text


def _caption_html(block: dict[str, Any], blocks: list[dict[str, Any]], index: int) -> str:
    text = block.get("text", "")
    prev_block = blocks[index - 1] if index > 0 else None
    if prev_block and prev_block["type"] == "figure":
        # Legacy path for figure-trailing captions not consumed by
        # _collect_trailing_captions — structure multi-line text.
        return _figcaption_structured(text)
    lines = [l for l in text.split("\n") if l.strip()]
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
    lines = [l for l in text.split("\n") if l.strip()]
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
    return f'<blockquote class="{escape(class_attr, quote=True)}">{"".join(paragraphs)}</blockquote>'
