"""Canonical data models. Defines RawBlock, BBox, LayoutStats, IdFactory, NoteRef, and the canonical_block() factory. These are the core data types used throughout the entire pipeline."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from inkline.canonical.types import CanonicalBlock, CanonicalSource, NoteRef as NoteRefDict

BBox = List[float]


@dataclass
class NoteRef:
    marker: str
    position: str = "after_text"
    source: str = "inline"
    raw_marker: str = ""


@dataclass
class RawBlock:
    page: int
    index: int
    raw_type: str
    text: str
    bbox: Optional[BBox]
    raw: Dict[str, Any]
    note_refs: List[NoteRef] = field(default_factory=list)
    inline_runs: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def x0(self) -> float:
        return self.bbox[0] if self.bbox else 0.0

    @property
    def y0(self) -> float:
        return self.bbox[1] if self.bbox else 0.0

    @property
    def x1(self) -> float:
        return self.bbox[2] if self.bbox else 0.0

    @property
    def y1(self) -> float:
        return self.bbox[3] if self.bbox else 0.0

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)


@dataclass
class LayoutStats:
    page_width: float = 1000.0
    page_height: float = 1000.0
    body_left: float = 120.0
    body_right: float = 880.0

    @property
    def body_width(self) -> float:
        return max(1.0, self.body_right - self.body_left)


def canonical_block(
    block_id: str,
    block_type: str,
    text: str,
    page: Optional[int],
    bbox: Optional[BBox],
    attrs: Optional[Dict[str, Any]] = None,
    level: Optional[int] = None,
    source_pages: Optional[List[int]] = None,
) -> CanonicalBlock:
    obj: CanonicalBlock = {
        "block_id": block_id,
        "type": block_type,
        "text": text,
        "source": {"page": page, "bbox": bbox},
        "attrs": attrs or {},
    }
    if source_pages:
        obj["source"]["pages"] = source_pages
    if level is not None:
        obj["level"] = level
    return obj


class IdFactory:
    def __init__(self, prefix: str = "b") -> None:
        self.prefix = prefix
        self.i = 1

    def next(self) -> str:
        out = f"{self.prefix}{self.i:06d}"
        self.i += 1
        return out
