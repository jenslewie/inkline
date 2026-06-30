from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from inkline.epub.figure.model import Caption, CaptionSide, ImageRef, SideCaptionLayout

FULL_WIDTH_IMAGE_MIN_PERCENT = 80.0


@dataclass(frozen=True)
class _Box:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return max(1.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)


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
    image = _box_from_bbox(attrs.get("image_bbox"))
    caption = _box_from_bbox(attrs.get("caption_bbox"))
    source_bbox = (block.get("source") or {}).get("bbox")
    if image is None or caption is None or not is_bbox(source_bbox):
        return None

    if _vertical_overlap(image, caption) < min(image.height, caption.height) * 0.25:
        return None

    side = _caption_side(image, caption)
    if side is None:
        return None
    source_width = bbox_width(source_bbox)
    if source_width <= 0:
        return None
    return SideCaptionLayout(
        side=side,
        image_percent=_width_percent(image, source_width),
        caption_percent=_width_percent(caption, source_width),
    )


def _box_from_bbox(bbox: Any) -> _Box | None:
    if not is_bbox(bbox):
        return None
    try:
        left, top, right, bottom = (float(v) for v in bbox[:4])
    except (TypeError, ValueError):
        return None
    return _Box(left, top, right, bottom)


def _vertical_overlap(left: _Box, right: _Box) -> float:
    return min(left.bottom, right.bottom) - max(left.top, right.top)


def _caption_side(image: _Box, caption: _Box) -> CaptionSide | None:
    if caption.left >= image.right - image.width * 0.05:
        return "right"
    if caption.right <= image.left + image.width * 0.05:
        return "left"
    return None


def _width_percent(box: _Box, source_width: float) -> float:
    return min(100.0, max(1.0, box.width / source_width * 100.0))


def infer_image_max_width_percent(block: dict[str, Any], page_width: float | None) -> float | None:
    percent = infer_image_width_percent(block, page_width)
    if percent is None or percent >= FULL_WIDTH_IMAGE_MIN_PERCENT:
        return None
    return percent


def infer_image_width_percent(block: dict[str, Any], page_width: float | None) -> float | None:
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
    if image.full_width:
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
