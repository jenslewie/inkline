from __future__ import annotations

import uuid
import zipfile
from pathlib import Path
from typing import Any

from inkline.epub._assets import asset_image_name, collect_inline_images, image_assets_by_id
from inkline.epub._nav import nav_xhtml, toc_heading_block_ids
from inkline.epub._opf import container_xml, opf, wrap_chapter
from inkline.epub._render import chapter_documents
from inkline.epub._style import BOOK_CSS


def export_epub(
    document: dict[str, Any], output_path: str | Path, *, base_dir: str | Path | None = None
) -> None:
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
    image_assets = image_assets_by_id(document, base_dir=base_dir)
    inline_images = collect_inline_images(document, base_dir=base_dir, image_assets=image_assets)
    toc = document.get("toc", [])
    toc_heading_ids = toc_heading_block_ids(document)
    chapters = chapter_documents(document, image_assets=image_assets, inline_images=inline_images)

    with zipfile.ZipFile(output_file, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container_xml())
        archive.writestr("EPUB/styles/book.css", BOOK_CSS)
        archive.writestr(
            "EPUB/nav.xhtml",
            nav_xhtml(metadata, chapters, toc=toc, toc_heading_ids=toc_heading_ids),
        )
        archive.writestr(
            "EPUB/content.opf", opf(metadata, identifier, chapters, image_assets, inline_images)
        )
        for index, chapter in enumerate(chapters, 1):
            archive.writestr(
                f"EPUB/chapter_{index:04d}.xhtml", wrap_chapter(chapter.body, metadata)
            )
        for asset in image_assets.values():
            path = Path(asset["path"])
            if not path.exists():
                continue
            archive.write(path, f"EPUB/images/{asset_image_name(asset)}")
        for _img_key, img_info in inline_images.items():
            path = Path(img_info["path"])
            if path.exists():
                archive.write(path, f"EPUB/images/{img_info['epub_name']}")
