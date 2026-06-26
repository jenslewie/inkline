from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class TextSegment:
    text: str


@dataclass(frozen=True)
class NoteRef:
    marker: str
    target: object | None
    ref_id: str


InlinePart: TypeAlias = TextSegment | NoteRef


@dataclass(frozen=True)
class InlineText:
    parts: list[InlinePart]


@dataclass(frozen=True)
class DisplayBlockView:
    classes: list[str]
    paragraphs: list[InlineText]


@dataclass(frozen=True)
class HeadingView:
    level: int
    text: str


@dataclass(frozen=True)
class ListView:
    items: list[InlineText]


@dataclass(frozen=True)
class FootnoteView:
    note_id: str | None
    text: str
