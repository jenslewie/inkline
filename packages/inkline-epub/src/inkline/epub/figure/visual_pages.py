from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from inkline.epub.assets.resolver import asset_image_name


def build_visual_page_set(document: dict[str, Any]) -> set[int]:
    pages = document.get("pages", [])
    result: set[int] = set()
    for page in pages:
        if not isinstance(page, dict):
            continue
        snapshot = page.get("snapshot")
        if isinstance(snapshot, dict) and snapshot.get("required"):
            physical_page = page.get("physical_page")
            if isinstance(physical_page, int):
                result.add(physical_page)
    return result


def build_full_page_figure_map(document: dict[str, Any]) -> dict[int, dict[str, Any]]:
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


def build_snapshot_asset_id_map(document: dict[str, Any]) -> dict[int, str]:
    pages = document.get("pages", [])
    result: dict[int, str] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        snapshot = page.get("snapshot")
        if isinstance(snapshot, dict) and snapshot.get("required"):
            physical_page = page.get("physical_page")
            asset_id = snapshot.get("asset_id")
            if isinstance(physical_page, int) and isinstance(asset_id, str):
                result[physical_page] = asset_id
    return result


def resolve_snapshot_image(
    page_num: int,
    *,
    snapshot_asset_ids: dict[int, str],
    image_assets: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    asset_id = snapshot_asset_ids.get(page_num) or f"page-{page_num:04d}-snapshot"
    asset = image_assets.get(asset_id)
    if not asset or not Path(asset["path"]).exists():
        return None
    return asset


def render_snapshot_figure_html(page_num: int, asset: dict[str, Any]) -> str:
    image_name = asset_image_name(asset)
    alt = f"Page {page_num}"
    return "\n".join(
        [
            '<figure class="visual-page">',
            f'  <img src="images/{escape(image_name, quote=True)}" alt="{escape(alt, quote=True)}"/>',
            "</figure>",
        ]
    )


def snapshot_figure_html(
    page_num: int,
    *,
    snapshot_asset_ids: dict[int, str] | None = None,
    image_assets: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    image_assets = image_assets or {}
    snapshot_asset_ids = snapshot_asset_ids or {}
    asset = resolve_snapshot_image(
        page_num,
        snapshot_asset_ids=snapshot_asset_ids,
        image_assets=image_assets,
    )
    if asset is None:
        return None
    return render_snapshot_figure_html(page_num, asset)
