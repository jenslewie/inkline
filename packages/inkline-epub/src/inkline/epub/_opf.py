from __future__ import annotations

import posixpath
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from inkline.epub._assets import asset_image_name, cover_image_id
from inkline.epub._chapter import Chapter


def container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def wrap_chapter(body: str, metadata: dict[str, Any]) -> str:
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


def opf(
    metadata: dict[str, Any],
    identifier: str,
    chapters: list[Chapter],
    image_assets: dict[str, dict[str, Any]],
    inline_images: dict[str, dict[str, Any]] | None = None,
) -> str:
    import mimetypes

    inline_images = inline_images or {}
    title = escape(metadata.get("title") or metadata["doc_id"])
    language = escape(metadata.get("language") or "zh-CN")
    author = escape(metadata.get("author") or "Unknown")
    cover_image_id_val = cover_image_id(image_assets)
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
        href = posixpath.join("images", asset_image_name(asset))
        properties = ' properties="cover-image"' if image_id == cover_image_id_val else ""
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
    cover_meta = (
        f'<meta name="cover" content="{escape(cover_image_id_val, quote=True)}"/>'
        if cover_image_id_val
        else ""
    )
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
