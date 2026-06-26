from __future__ import annotations

from typing import Any, cast

from inkline.epub.figure.model import Caption, CaptionSide, ImageRef, SideCaptionLayout


def estimate_document_page_width(document: dict[str, Any]) -> float | None:
    right_edges: list[float] = []
    for block in document.get("blocks", []):
        source = block.get("source") or {}
        bbox = source.get("bbox")
        if not is_bbox(bbox):
            continue
        box = cast(list[Any], bbox)
        try:
            right = float(box[2])
        except (TypeError, ValueError):
            continue
        if right > 0:
            right_edges.append(right)
    if not right_edges:
        return None
    right_edges.sort()
    index = min(len(right_edges) - 1, int(len(right_edges) * 0.95))
    return max(1.0, right_edges[index])


def infer_side_caption_layout(block: dict[str, Any]) -> SideCaptionLayout | None:
    attrs = block.get("attrs") or {}
    image_bbox = attrs.get("image_bbox")
    caption_bbox = attrs.get("caption_bbox")
    source_bbox = (block.get("source") or {}).get("bbox")
    if not (is_bbox(image_bbox) and is_bbox(caption_bbox) and is_bbox(source_bbox)):
        return None
    image_box = cast(list[Any], image_bbox)
    caption_box = cast(list[Any], caption_bbox)
    image_left, image_top, image_right, image_bottom = [float(v) for v in image_box[:4]]
    caption_left, caption_top, caption_right, caption_bottom = [float(v) for v in caption_box[:4]]
    image_width = max(1.0, image_right - image_left)
    image_height = max(1.0, image_bottom - image_top)
    caption_width = max(1.0, caption_right - caption_left)
    caption_height = max(1.0, caption_bottom - caption_top)
    vertical_overlap = min(image_bottom, caption_bottom) - max(image_top, caption_top)
    min_height = min(image_height, caption_height)
    if vertical_overlap < min_height * 0.25:
        return None
    side: CaptionSide | None = None
    if caption_left >= image_right - image_width * 0.05:
        side = "right"
    elif caption_right <= image_left + image_width * 0.05:
        side = "left"
    if side is None:
        return None
    source_width = bbox_width(source_bbox)
    if source_width <= 0:
        return None
    return SideCaptionLayout(
        side=side,
        image_percent=min(100.0, max(1.0, image_width / source_width * 100.0)),
        caption_percent=min(100.0, max(1.0, caption_width / source_width * 100.0)),
    )


def infer_image_max_width_percent(block: dict[str, Any], page_width: float | None) -> float | None:
    attrs = block.get("attrs") or {}
    bbox = attrs.get("image_bbox") or (block.get("source") or {}).get("bbox")
    if not page_width or page_width <= 0:
        return None
    width = bbox_width(bbox)
    if width <= 0:
        return None
    return min(100.0, max(1.0, width / page_width * 100.0))


def infer_figure_classes(
    *,
    image: ImageRef,
    caption: Caption | None,
    side_layout: SideCaptionLayout | None,
) -> list[str]:
    classes = ["figure-block"]
    if image.kind == "placeholder":
        classes.insert(0, "image-placeholder")
    if should_use_full_width_image(caption=caption, image=image):
        classes.append("figure-fullwidth")
    if caption:
        classes.append("has-caption")
        if not side_layout and is_portrait_image(image):
            classes.append("figure-portrait")
        if side_layout:
            classes.append("caption-side")
    return classes


def is_portrait_image(image: ImageRef | None) -> bool:
    if not image or not image.width or not image.height:
        return False
    return image.width > 0 and image.height > 0 and image.height / image.width >= 1.25


def should_use_full_width_image(*, caption: Caption | None, image: ImageRef) -> bool:
    if caption or not image.width or not image.height:
        return False
    return image.width > 0 and image.height > 0 and image.width / image.height >= 0.6


def bbox_width(bbox: Any) -> float:
    if not is_bbox(bbox):
        return 0.0
    try:
        left = float(bbox[0])
        right = float(bbox[2])
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, right - left)


def is_bbox(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 4


def format_percent(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")
