from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManifestItem:
    id: str
    href: str
    media_type: str
    properties: str | None = None


@dataclass(frozen=True)
class PackageView:
    identifier: str
    title: str
    language: str
    author: str
    modified: str
    cover_image_id: str | None
    manifest_items: list[ManifestItem]
    spine_item_ids: list[str]
