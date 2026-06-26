from __future__ import annotations

import uuid
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from inkline.epub.assets.resolver import (
    asset_image_name,
    collect_inline_images,
    image_assets_by_id,
)
from inkline.epub.navigation.html import render_nav_xhtml
from inkline.epub.navigation.resolver import resolve_nav_view, toc_heading_block_ids
from inkline.epub.package.resolver import resolve_package_view
from inkline.epub.package.xml import container_xml, render_opf_xml, wrap_chapter
from inkline.epub.renderer import chapter_documents
from inkline.epub.theme.style import BOOK_CSS


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

    with TemporaryDirectory(prefix="inkline-epub-assets-") as temp_dir:
        image_assets = _materialize_cropped_full_page_assets(
            document, image_assets=image_assets, temp_dir=Path(temp_dir)
        )
        chapters = chapter_documents(
            document, image_assets=image_assets, inline_images=inline_images
        )

        with zipfile.ZipFile(output_file, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            archive.writestr("META-INF/container.xml", container_xml())
            archive.writestr("EPUB/styles/book.css", BOOK_CSS)
            archive.writestr(
                "EPUB/nav.xhtml",
                render_nav_xhtml(
                    resolve_nav_view(metadata, chapters, toc=toc, toc_heading_ids=toc_heading_ids)
                ),
            )
            archive.writestr(
                "EPUB/content.opf",
                render_opf_xml(
                    resolve_package_view(
                        metadata,
                        identifier,
                        chapters,
                        image_assets,
                        inline_images,
                    )
                ),
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


def _materialize_cropped_full_page_assets(
    document: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]],
    temp_dir: Path,
) -> dict[str, dict[str, Any]]:
    cropped_assets = dict(image_assets)
    for block in document.get("blocks", []):
        if block.get("type") != "figure":
            continue
        attrs = block.get("attrs") or {}
        if attrs.get("layout_role") != "full_page_image":
            continue
        image_id = attrs.get("image_id")
        if not image_id or image_id not in cropped_assets:
            continue
        cropped = _crop_asset_to_content(cropped_assets[image_id], temp_dir=temp_dir)
        if cropped:
            cropped_assets[image_id] = cropped
    return cropped_assets


def _crop_asset_to_content(asset: dict[str, Any], *, temp_dir: Path) -> dict[str, Any] | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    path = Path(asset["path"])
    if not path.exists():
        return None
    try:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            bbox = _non_blank_bbox(rgb)
            if bbox is None:
                return None
            left, top, right, bottom = bbox
            width, height = rgb.size
            pad = max(12, min(width, height) // 100)
            crop_box = (
                max(0, left - pad),
                max(0, top - pad),
                min(width, right + pad),
                min(height, bottom + pad),
            )
            crop_width = crop_box[2] - crop_box[0]
            crop_height = crop_box[3] - crop_box[1]
            if crop_width >= width * 0.98 and crop_height >= height * 0.98:
                return None
            output = temp_dir / f"{path.stem}_cropped.png"
            rgb.crop(crop_box).save(output)
    except OSError:
        return None
    cropped = dict(asset)
    cropped["path"] = str(output)
    cropped["media_type"] = "image/png"
    return cropped


def _non_blank_bbox(image: Any) -> tuple[int, int, int, int] | None:
    width, height = image.size
    pixels = image.load()
    left = width
    top = height
    right = 0
    bottom = 0
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            if min(r, g, b) < 245:
                if x < left:
                    left = x
                if y < top:
                    top = y
                if x + 1 > right:
                    right = x + 1
                if y + 1 > bottom:
                    bottom = y + 1
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom
