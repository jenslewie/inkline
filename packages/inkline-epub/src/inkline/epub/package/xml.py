from __future__ import annotations

from html import escape
from typing import Any

from inkline.epub.package.model import ManifestItem, PackageView


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
    indented_body = "\n".join(
        "      " + line if line.strip() else line for line in body.split("\n")
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">
  <head>
    <title>{escape(metadata.get("title") or metadata.get("doc_id") or "Book")}</title>
    <link href="styles/book.css" rel="stylesheet" type="text/css"/>
  </head>
  <body>
    <main>
{indented_body}
    </main>
  </body>
</html>
"""


def render_opf_xml(package: PackageView) -> str:
    cover_meta = (
        f'<meta name="cover" content="{escape(package.cover_image_id, quote=True)}"/>'
        if package.cover_image_id
        else ""
    )
    manifest_lines = "\n    ".join(_manifest_item_xml(item) for item in package.manifest_items)
    spine_lines = "\n    ".join(
        f'<itemref idref="{escape(item_id, quote=True)}"/>' for item_id in package.spine_item_ids
    )
    cover_meta_line = f"\n    {cover_meta}" if cover_meta else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{escape(package.identifier)}</dc:identifier>
    <dc:title>{escape(package.title)}</dc:title>
    <dc:language>{escape(package.language)}</dc:language>
    <dc:creator>{escape(package.author)}</dc:creator>{cover_meta_line}
    <meta property="dcterms:modified">{escape(package.modified)}</meta>
  </metadata>
  <manifest>
    {manifest_lines}
  </manifest>
  <spine>
    {spine_lines}
  </spine>
</package>
"""


def _manifest_item_xml(item: ManifestItem) -> str:
    properties = f' properties="{escape(item.properties, quote=True)}"' if item.properties else ""
    return (
        f'<item id="{escape(item.id, quote=True)}" '
        f'href="{escape(item.href, quote=True)}" '
        f'media-type="{escape(item.media_type, quote=True)}"{properties}/>'
    )
