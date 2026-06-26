from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CaptionSide = Literal["left", "right"]
ImageSourceKind = Literal["asset", "inline", "placeholder"]


@dataclass(frozen=True)
class ImageRef:
    kind: ImageSourceKind
    src: str | None
    alt: str
    width: int | None = None
    height: int | None = None
    max_width_percent: float | None = None


@dataclass(frozen=True)
class Caption:
    title: str
    body: list[str]


@dataclass(frozen=True)
class SideCaptionLayout:
    side: CaptionSide
    image_percent: float
    caption_percent: float


@dataclass(frozen=True)
class FigureView:
    image: ImageRef
    caption: Caption | None
    side_layout: SideCaptionLayout | None
    classes: list[str]
    page_break_before: bool = True
