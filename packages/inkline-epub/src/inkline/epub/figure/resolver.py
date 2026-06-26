from __future__ import annotations

from pathlib import Path
from typing import Any

from inkline.epub.assets.resolver import asset_image_name
from inkline.epub.figure.image_probe import image_pixel_dimensions
from inkline.epub.figure.layout import (
    infer_figure_classes,
    infer_image_max_width_percent,
    infer_side_caption_layout,
)
from inkline.epub.figure.model import Caption, FigureView, ImageRef


def resolve_figure_view(
    block: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]] | None = None,
    inline_images: dict[str, dict[str, Any]] | None = None,
    captions: list[dict[str, Any]] | None = None,
    page_width: float | None = None,
) -> FigureView:
    image_assets = image_assets or {}
    inline_images = inline_images or {}
    captions = captions or []
    caption = normalize_figure_caption(block, captions)
    image = resolve_figure_image(
        block,
        image_assets=image_assets,
        inline_images=inline_images,
        caption=caption,
        page_width=page_width,
    )
    side_layout = (
        infer_side_caption_layout(block)
        if caption is not None and image.kind != "placeholder"
        else None
    )
    classes = infer_figure_classes(image=image, caption=caption, side_layout=side_layout)
    return FigureView(
        image=image,
        caption=caption,
        side_layout=side_layout,
        classes=classes,
        page_break_before=True,
    )


def resolve_figure_image(
    block: dict[str, Any],
    *,
    image_assets: dict[str, dict[str, Any]],
    inline_images: dict[str, dict[str, Any]],
    caption: Caption | None,
    page_width: float | None,
) -> ImageRef:
    text = (block.get("text") or "").strip()
    attrs = block.get("attrs") or {}
    block_id = block.get("block_id", "")
    image_id = attrs.get("image_id")
    image_asset = image_assets.get(image_id) if image_id else None
    inline_img = inline_images.get(block_id)
    max_width_percent = None if caption else infer_image_max_width_percent(block, page_width)

    if image_asset and Path(image_asset["path"]).exists():
        width, height = _dimensions_or_empty(image_asset)
        return ImageRef(
            kind="asset",
            src=asset_image_name(image_asset),
            alt=text,
            width=width,
            height=height,
            max_width_percent=max_width_percent,
        )
    if inline_img:
        width, height = _dimensions_or_empty(inline_img)
        return ImageRef(
            kind="inline",
            src=inline_img["epub_name"],
            alt=text,
            width=width,
            height=height,
            max_width_percent=max_width_percent,
        )
    return ImageRef(kind="placeholder", src=None, alt=text)


def normalize_figure_caption(
    block: dict[str, Any],
    trailing_captions: list[dict[str, Any]],
) -> Caption | None:
    segments: list[str] = []
    for part in _caption_text_parts(block, trailing_captions):
        for line in part.replace("\\n", "\n").split("\n"):
            stripped = line.strip()
            if stripped:
                segments.append(stripped)
    if not segments:
        return None
    return Caption(title=segments[0], body=segments[1:])


def collect_trailing_captions(blocks: list[dict[str, Any]], start: int) -> list[dict[str, Any]]:
    captions: list[dict[str, Any]] = []
    index = start
    while index < len(blocks) and blocks[index]["type"] == "caption":
        captions.append(blocks[index])
        index += 1
    return captions


def _caption_text_parts(
    block: dict[str, Any],
    trailing_captions: list[dict[str, Any]],
) -> list[str]:
    parts: list[str] = []
    text = (block.get("text") or "").strip()
    if text:
        parts.append(text)
    attrs_captions = (block.get("attrs") or {}).get("captions")
    if isinstance(attrs_captions, list):
        parts.extend(cap for cap in attrs_captions if isinstance(cap, str) and cap)
    for caption_block in trailing_captions:
        caption_text = caption_block.get("text", "")
        if caption_text:
            parts.append(caption_text)
    return parts


def _dimensions_or_empty(image_asset: dict[str, Any]) -> tuple[int | None, int | None]:
    dimensions = image_pixel_dimensions(image_asset)
    if not dimensions:
        return None, None
    return dimensions
