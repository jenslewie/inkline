from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
import mimetypes
import posixpath
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
.epigraph {
  margin: 1.2em 2em;
  text-indent: 0;
  font-style: italic;
  white-space: pre-line;
}
.blockquote {
  margin: 1em 2em;
  text-indent: 0;
}
.signature {
  margin: 1.2em 0;
  text-align: right;
  text-indent: 0;
}
""".strip()


def export_epub(document: dict[str, Any], output_path: str | Path) -> None:
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    metadata = document["metadata"]
    identifier = f"{metadata['doc_id']}-{metadata['parser_name']}-{uuid.uuid4()}"
    image_assets = _image_assets_by_id(document)
    chapters = _chapter_documents(document, image_assets=image_assets)

    with zipfile.ZipFile(output_file, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", _container_xml())
        archive.writestr("EPUB/styles/book.css", CSS)
        archive.writestr("EPUB/nav.xhtml", _nav_xhtml(metadata, chapters))
        archive.writestr("EPUB/content.opf", _opf(metadata, identifier, chapters, image_assets))
        for index, (_title, html) in enumerate(chapters, 1):
            archive.writestr(f"EPUB/chapter_{index:04d}.xhtml", _wrap_chapter(html, metadata))
        for asset in image_assets.values():
            path = Path(asset["path"])
            if not path.exists():
                continue
            archive.write(path, f"EPUB/images/{path.name}")


def _chapter_documents(
    document: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    image_assets = image_assets or {}
    chapters: list[tuple[str, list[str]]] = []
    current_title = document["metadata"].get("title") or document["metadata"]["doc_id"]
    current_html: list[str] = []

    for block in document["blocks"]:
        block_type = block["type"]
        text = block.get("text", "")
        if block_type == "heading" and int(block.get("level", 1)) == 1:
            if current_html:
                chapters.append((current_title, current_html))
                current_html = []
            current_title = text or current_title
            current_html.append(f"<h1>{escape(current_title)}</h1>")
        elif block_type == "heading":
            level = min(max(int(block.get("level", 2)), 2), 6)
            current_html.append(f"<h{level}>{escape(text)}</h{level}>")
        elif block_type == "paragraph":
            current_html.append(f"<p>{_text_html(block)}</p>")
        elif block_type == "epigraph":
            current_html.append(f'<blockquote class="epigraph">{escape(text)}</blockquote>')
        elif block_type == "blockquote":
            current_html.append(f'<blockquote class="blockquote">{escape(text)}</blockquote>')
        elif block_type == "signature":
            current_html.append(f'<p class="signature">{escape(text)}</p>')
        elif block_type == "list":
            current_html.append(f"<ul><li>{escape(text)}</li></ul>")
        elif block_type == "table":
            current_html.append(f"<table><tr><td>{escape(text)}</td></tr></table>")
        elif block_type == "figure":
            current_html.append(_figure_html(block, image_assets=image_assets))
        elif block_type == "caption":
            current_html.append(f"<figcaption>{escape(text)}</figcaption>")
        elif block_type == "footnote":
            attrs = block.get("attrs") or {}
            note_id = attrs.get("note_id") or block.get("block_id")
            id_attr = f' id="{escape(str(note_id), quote=True)}"' if note_id else ""
            current_html.append(f'<aside epub:type="footnote"{id_attr}><p>{escape(text)}</p></aside>')

    if current_html:
        chapters.append((current_title, current_html))
    if not chapters:
        chapters.append((current_title, ["<p></p>"]))

    return [(title, "\n".join(html_parts)) for title, html_parts in chapters]


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


def _figure_html(block: dict[str, Any], *, image_assets: dict[str, dict[str, Any]] | None = None) -> str:
    text = (block.get("text") or "").strip()
    source = block.get("source") or {}
    attrs = block.get("attrs") or {}
    image_assets = image_assets or {}
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
    if image_asset:
        image_name = Path(image_asset["path"]).name
        alt = text or fallback
        return (
            "<figure>"
            f'<img src="images/{escape(image_name, quote=True)}" alt="{escape(alt, quote=True)}"/>'
            f"<figcaption>{escape(caption)}</figcaption>"
            "</figure>"
        )

    return (
        '<figure class="image-placeholder">'
        '<div role="img" aria-label="Image placeholder">[Image]</div>'
        f"<figcaption>{escape(caption)}</figcaption>"
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


def _nav_xhtml(metadata: dict[str, Any], chapters: list[tuple[str, str]]) -> str:
    items = "\n".join(
        f'<li><a href="chapter_{index:04d}.xhtml">{escape(title)}</a></li>'
        for index, (title, _html) in enumerate(chapters, 1)
    )
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
    chapters: list[tuple[str, str]],
    image_assets: dict[str, dict[str, Any]],
) -> str:
    title = escape(metadata.get("title") or metadata["doc_id"])
    language = escape(metadata.get("language") or "zh-CN")
    author = escape(metadata.get("author") or "Unknown")
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
        href = posixpath.join("images", path.name)
        manifest_items.append(
            f'<item id="{escape(image_id, quote=True)}" href="{escape(href, quote=True)}" media-type="{escape(media_type, quote=True)}"/>'
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{escape(identifier)}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:language>{language}</dc:language>
    <dc:creator>{author}</dc:creator>
    <meta property="dcterms:modified">2026-06-03T00:00:00Z</meta>
  </metadata>
  <manifest>
    {"".join(manifest_items)}
  </manifest>
  <spine>
    {"".join(spine_items)}
  </spine>
</package>
"""


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.1f}"
