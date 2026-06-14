from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any


def image_assets_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    images = document.get("assets", {}).get("images", [])
    if not isinstance(images, list):
        return {}
    return {
        image["image_id"]: image
        for image in images
        if isinstance(image, dict) and image.get("image_id") and image.get("path")
    }


def collect_inline_images(
    document: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
    image_assets: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
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
        resolved = resolve_image_path(image_path, effective_base, doc_id=doc_id)
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


def resolve_image_path(image_path: str, base_dir: str, *, doc_id: str = "") -> Path | None:
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


def asset_image_name(asset: dict[str, Any]) -> str:
    image_id = str(asset.get("image_id") or "image")
    return f"{image_id}_{Path(asset['path']).name}"


def cover_image_id(image_assets: dict[str, dict[str, Any]]) -> str | None:
    for image_id, asset in image_assets.items():
        if asset.get("role") == "cover":
            return image_id
    return None
