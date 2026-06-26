from __future__ import annotations

import mimetypes
import posixpath
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inkline.epub.assets.resolver import asset_image_name, cover_image_id
from inkline.epub.chapter.model import Chapter
from inkline.epub.package.model import ManifestItem, PackageView


def resolve_package_view(
    metadata: dict[str, Any],
    identifier: str,
    chapters: list[Chapter],
    image_assets: dict[str, dict[str, Any]],
    inline_images: dict[str, dict[str, Any]] | None = None,
) -> PackageView:
    inline_images = inline_images or {}
    manifest_items = [
        ManifestItem(
            id="nav",
            href="nav.xhtml",
            media_type="application/xhtml+xml",
            properties="nav",
        ),
        ManifestItem(id="css", href="styles/book.css", media_type="text/css"),
    ]
    spine_item_ids: list[str] = []

    for index, _chapter in enumerate(chapters, 1):
        chapter_id = f"chapter_{index:04d}"
        manifest_items.append(
            ManifestItem(
                id=chapter_id,
                href=f"{chapter_id}.xhtml",
                media_type="application/xhtml+xml",
            )
        )
        spine_item_ids.append(chapter_id)

    cover_image_id_val = cover_image_id(image_assets)
    for image_id, asset in image_assets.items():
        path = Path(asset["path"])
        if not path.exists():
            continue
        media_type = asset.get("media_type") or mimetypes.guess_type(path.name)[0] or "image/png"
        properties = "cover-image" if image_id == cover_image_id_val else None
        manifest_items.append(
            ManifestItem(
                id=image_id,
                href=posixpath.join("images", asset_image_name(asset)),
                media_type=media_type,
                properties=properties,
            )
        )

    for block_id, img_info in inline_images.items():
        manifest_items.append(
            ManifestItem(
                id=block_id,
                href=f"images/{img_info['epub_name']}",
                media_type=img_info["media_type"],
            )
        )

    return PackageView(
        identifier=identifier,
        title=metadata.get("title") or metadata["doc_id"],
        language=metadata.get("language") or "zh-CN",
        author=metadata.get("author") or "Unknown",
        modified=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        cover_image_id=cover_image_id_val,
        manifest_items=manifest_items,
        spine_item_ids=spine_item_ids,
    )
