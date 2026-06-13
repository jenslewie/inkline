from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
import mimetypes
import posixpath
import re
import uuid
import zipfile


CSS = """
body {
  font-family: serif;
  line-height: 1.7;
  margin: 0;
  padding: 0;
}
main {
  max-width: 42em;
  margin: 0 auto;
  padding: 1.4em 5% 2.2em;
}
p {
  text-indent: 2em;
  margin: 0 0 0.8em;
  text-align: justify;
}
h1, h2, h3, h4, h5, h6 {
  text-align: center;
}
table {
  border-collapse: collapse;
  width: 100%;
}
td, th {
  border: 1px solid #999;
  padding: 0.25em 0.4em;
}
figure {
  margin: 1em 0;
  text-align: center;
}
img {
  display: block;
  height: auto;
  margin: 0 auto;
  max-width: 100%;
}
.image-placeholder {
  border: 1px solid #aaa;
  padding: 0.75em;
  color: #555;
  background: #f7f7f7;
}
figcaption {
  font-size: 0.9em;
}
.caption {
  font-size: 0.9em;
  text-align: center;
  margin: 0.2em 0 0.8em;
  text-indent: 0;
}
.display-block {
  margin: 1.2em 2em;
  text-indent: 0;
  white-space: pre-line;
}
.display-block-standalone {
  margin-top: 1.6em;
  margin-bottom: 1.6em;
}
.display-block-right {
  margin: 1.2em 0;
  text-align: right;
  text-indent: 0;
}
""".strip()


def export_epub(document: dict[str, Any], output_path: str | Path, *, base_dir: str | Path | None = None) -> None:
    """Export a canonical document to an EPUB 3.0 archive.

    *base_dir* is used to resolve relative ``attrs.image_path`` values found
    on figure blocks.  When the canonical document was loaded from a JSON file
    on disk, pass the directory containing that file so that relative image
    paths can be found.  If omitted, the parent of ``metadata.source_file`` is
    used as a fallback – which may not contain the VLM output images.
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    metadata = document["metadata"]
    identifier = f"{metadata['doc_id']}-{metadata['parser_name']}-{uuid.uuid4()}"
    image_assets = _image_assets_by_id(document)
    inline_images = _collect_inline_images(document, base_dir=base_dir, image_assets=image_assets)
    toc = document.get("toc", [])
    chapters = _chapter_documents(document, image_assets=image_assets, inline_images=inline_images)

    with zipfile.ZipFile(output_file, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", _container_xml())
        archive.writestr("EPUB/styles/book.css", CSS)
        archive.writestr("EPUB/nav.xhtml", _nav_xhtml(metadata, chapters, toc=toc))
        archive.writestr("EPUB/content.opf", _opf(metadata, identifier, chapters, image_assets, inline_images))
        for index, (_title, html, _block_id) in enumerate(chapters, 1):
            archive.writestr(f"EPUB/chapter_{index:04d}.xhtml", _wrap_chapter(html, metadata))
        for asset in image_assets.values():
            path = Path(asset["path"])
            if not path.exists():
                continue
            archive.write(path, f"EPUB/images/{_asset_image_name(asset)}")
        for img_key, img_info in inline_images.items():
            path = Path(img_info["path"])
            if path.exists():
                archive.write(path, f"EPUB/images/{img_info['epub_name']}")


def _collect_inline_images(document: dict[str, Any], *, base_dir: str | Path | None = None, image_assets: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    source_file = document["metadata"].get("source_file", "")
    doc_id = document["metadata"].get("doc_id", "")
    fallback_dir = str(Path(source_file).parent) if source_file else ""
    effective_base = str(base_dir) if base_dir else fallback_dir
    image_assets = image_assets or {}
    result: dict[str, dict[str, Any]] = {}
    for block in document["blocks"]:
        if block["type"] != "figure":
            continue
        attrs = block.get("attrs") or {}
        image_id = attrs.get("image_id")
        if image_id:
            asset = image_assets.get(image_id)
            if asset and Path(asset["path"]).exists():
                continue
        image_path = attrs.get("image_path")
        if not image_path:
            continue
        resolved = _resolve_image_path(image_path, effective_base, doc_id=doc_id)
        if not resolved or not resolved.exists():
            continue
        block_id = block.get("block_id", "")
        epub_name = f"{block_id}_{resolved.name}"
        media_type = mimetypes.guess_type(resolved.name)[0] or "image/jpeg"
        result[block_id] = {
            "path": str(resolved),
            "epub_name": epub_name,
            "media_type": media_type,
        }
    return result


def _resolve_image_path(image_path: str, base_dir: str, *, doc_id: str = "") -> Path | None:
    candidate = Path(image_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if base_dir:
        joined = Path(base_dir) / image_path
        if joined.exists():
            return joined
        parent = Path(base_dir)
        for vlm_dir in parent.rglob("vlm/images"):
            filename = Path(image_path).name
            candidate = vlm_dir / filename
            if candidate.exists():
                return candidate
        if doc_id:
            for candidate_dir in [
                parent / "mineru_raw" / doc_id / "vlm" / "images",
                parent / doc_id / "mineru_raw" / doc_id / "vlm" / "images",
            ]:
                if candidate_dir.is_dir():
                    filename = Path(image_path).name
                    candidate = candidate_dir / filename
                    if candidate.exists():
                        return candidate
    return None


def _chapter_documents(
    document: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]] | None = None,
    inline_images: dict[str, dict[str, Any]] | None = None,
) -> list[tuple[str, str, str | None]]:
    image_assets = image_assets or {}
    inline_images = inline_images or {}
    chapters: list[tuple[str, list[str], str | None]] = []
    current_title = document["metadata"].get("title") or document["metadata"]["doc_id"]
    current_block_id: str | None = None
    current_html: list[str] = []

    i = 0
    blocks = document["blocks"]
    while i < len(blocks):
        block = blocks[i]
        block_type = block["type"]
        text = block.get("text", "")
        if block_type == "heading" and int(block.get("level", 1)) == 1:
            if current_html:
                chapters.append((current_title, current_html, current_block_id))
                current_html = []
            current_title = text or current_title
            current_block_id = block.get("block_id")
            current_html.append(f"<h1>{escape(current_title)}</h1>")
        elif block_type == "heading":
            level = min(max(int(block.get("level", 2)), 2), 6)
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
        elif block_type == "table":
            html = _table_html(block)
            if html is not None:
                current_html.append(html)
        elif block_type == "table_continuation":
            html = _table_html(block)
            if html is not None:
                current_html.append(html)
        elif block_type == "figure":
            captions = _collect_trailing_captions(blocks, i + 1)
            current_html.append(_figure_html(block, image_assets=image_assets, inline_images=inline_images, captions=captions))
            i += len(captions)
        elif block_type == "caption":
            current_html.append(_caption_html(block, blocks, i))
        elif block_type == "footnote":
            attrs = block.get("attrs") or {}
            note_id = attrs.get("note_id") or block.get("block_id")
            id_attr = f' id="{escape(str(note_id), quote=True)}"' if note_id else ""
            current_html.append(f'<aside epub:type="footnote"{id_attr}><p>{escape(text)}</p></aside>')
        elif block_type == "toc_item":
            pass
        i += 1

    if current_html:
        chapters.append((current_title, current_html, current_block_id))
    if not chapters:
        chapters.append((current_title, ["<p></p>"], None))

    return [(title, "\n".join(html_parts), block_id) for title, html_parts, block_id in chapters]


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
    "nbsp": "\u00a0",
    "copy": "\u00a9",
    "reg": "\u00ae",
    "trade": "\u2122",
    "mdash": "\u2014",
    "ndash": "\u2013",
    "lsquo": "\u2018",
    "rsquo": "\u2019",
    "ldquo": "\u201c",
    "rdquo": "\u201d",
    "bull": "\u2022",
    "hellip": "\u2026",
    "laquo": "\u00ab",
    "raquo": "\u00bb",
    "middot": "\u00b7",
    "times": "\u00d7",
    "divide": "\u00f7",
    "deg": "\u00b0",
    "plusmn": "\u00b1",
    "para": "\u00b6",
    "sect": "\u00a7",
    "euro": "\u20ac",
    "pound": "\u00a3",
    "yen": "\u00a5",
    "cent": "\u00a2",
    "rarr": "\u2192",
    "larr": "\u2190",
    "uarr": "\u2191",
    "darr": "\u2193",
    "infin": "\u221e",
    "ne": "\u2260",
    "le": "\u2264",
    "ge": "\u2265",
    "micro": "\u00b5",
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
    fixed = re.sub(r"<(br|hr|img|input|meta|link)(\s[^>]*)?>", lambda m: f"<{m.group(1)}{m.group(2) or ''}/>", fixed)
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


def _text_html(block: dict[str, Any]) -> str:
    attrs = block.get("attrs") or {}
    runs = attrs.get("inline_runs")
    if not isinstance(runs, list) or not any(isinstance(run, dict) and run.get("type") == "note_ref" for run in runs):
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


def _image_assets_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    images = document.get("assets", {}).get("images", [])
    if not isinstance(images, list):
        return {}
    return {
        image["image_id"]: image
        for image in images
        if isinstance(image, dict) and image.get("image_id") and image.get("path")
    }


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
    caption_html = "<figcaption>" + "<br/>".join(caption_parts) + "</figcaption>" if caption_parts else ""
    if not caption_html:
        caption_html = f"<figcaption>{escape(fallback)}</figcaption>"

    if image_asset and Path(image_asset["path"]).exists():
        image_name = _asset_image_name(image_asset)
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


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _wrap_chapter(body: str, metadata: dict[str, Any]) -> str:
    lang = escape(metadata.get("language") or "zh-CN", quote=True)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">
<head>
  <title>{escape(metadata.get("title") or metadata.get("doc_id") or "Book")}</title>
  <link href="styles/book.css" rel="stylesheet" type="text/css"/>
</head>
<body><main>
{body}
</main></body>
</html>
"""


def _nav_xhtml(metadata: dict[str, Any], chapters: list[tuple[str, str, str | None]], *, toc: list[dict[str, Any]] | None = None) -> str:
    toc = toc or []
    toc_by_block_id: dict[str, dict[str, Any]] = {}
    unique_titles: dict[str, dict[str, Any]] = {}
    title_counts: dict[str, int] = {}
    for entry in toc:
        block_id = entry.get("source_block_id") or entry.get("block_id")
        if block_id:
            toc_by_block_id[block_id] = entry
        title = entry.get("title", "")
        if title:
            title_counts[title] = title_counts.get(title, 0) + 1
    for entry in toc:
        title = entry.get("title", "")
        if title and title_counts.get(title) == 1:
            unique_titles[title] = entry
    items_parts: list[str] = []
    for index, (title, _html, block_id) in enumerate(chapters, 1):
        page_label = ""
        entry = toc_by_block_id.get(block_id) if block_id else None
        if not entry:
            entry = unique_titles.get(title)
        if entry:
            page_label = entry.get("target_page_label") or entry.get("page_hint") or ""
        href = f"chapter_{index:04d}.xhtml"
        label = escape(title)
        if page_label:
            label = f"{label} ({escape(page_label)})"
        items_parts.append(f"<li><a href=\"{href}\">{label}</a></li>")
    items = "\n".join(items_parts)
    lang = escape(metadata.get("language") or "zh-CN", quote=True)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">
<head><title>Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Contents</h1>
    <ol>{items}</ol>
  </nav>
</body>
</html>
"""


def _opf(
    metadata: dict[str, Any],
    identifier: str,
    chapters: list[tuple[str, str, str | None]],
    image_assets: dict[str, dict[str, Any]],
    inline_images: dict[str, dict[str, Any]] | None = None,
) -> str:
    inline_images = inline_images or {}
    title = escape(metadata.get("title") or metadata["doc_id"])
    language = escape(metadata.get("language") or "zh-CN")
    author = escape(metadata.get("author") or "Unknown")
    cover_image_id = _cover_image_id(image_assets)
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="css" href="styles/book.css" media-type="text/css"/>',
    ]
    spine_items = []
    for index, _chapter in enumerate(chapters, 1):
        manifest_items.append(
            f'<item id="chapter_{index:04d}" href="chapter_{index:04d}.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine_items.append(f'<itemref idref="chapter_{index:04d}"/>')
    for image_id, asset in image_assets.items():
        path = Path(asset["path"])
        if not path.exists():
            continue
        media_type = asset.get("media_type") or mimetypes.guess_type(path.name)[0] or "image/png"
        href = posixpath.join("images", _asset_image_name(asset))
        properties = ' properties="cover-image"' if image_id == cover_image_id else ""
        manifest_items.append(
            f'<item id="{escape(image_id, quote=True)}" href="{escape(href, quote=True)}" media-type="{escape(media_type, quote=True)}"{properties}/>'
        )
    for block_id, img_info in inline_images.items():
        epub_name = img_info["epub_name"]
        media_type = img_info["media_type"]
        manifest_items.append(
            f'<item id="{escape(block_id, quote=True)}" href="images/{escape(epub_name, quote=True)}" media-type="{escape(media_type, quote=True)}"/>'
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cover_meta = f'<meta name="cover" content="{escape(cover_image_id, quote=True)}"/>' if cover_image_id else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{escape(identifier)}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:language>{language}</dc:language>
    <dc:creator>{author}</dc:creator>
    {cover_meta}
    <meta property="dcterms:modified">{escape(now)}</meta>
  </metadata>
  <manifest>
    {"".join(manifest_items)}
  </manifest>
  <spine>
    {"".join(spine_items)}
  </spine>
</package>
"""


def _cover_image_id(image_assets: dict[str, dict[str, Any]]) -> str | None:
    for image_id, asset in image_assets.items():
        if asset.get("role") == "cover":
            return image_id
    return None


def _asset_image_name(asset: dict[str, Any]) -> str:
    image_id = str(asset.get("image_id") or "image")
    return f"{image_id}_{Path(asset['path']).name}"


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.1f}"
