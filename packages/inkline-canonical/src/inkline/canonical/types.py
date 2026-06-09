from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class CanonicalSource(TypedDict):
    page: int | None
    bbox: list[float] | None
    pages: NotRequired[list[int]]


class CanonicalBlock(TypedDict):
    block_id: str
    type: str
    text: str
    source: CanonicalSource
    attrs: dict[str, Any]
    level: NotRequired[int]


class NoteRef(TypedDict, total=False):
    marker: str
    source: str
    source_page: int
    target_note_id: str
    target_block_id: str
    raw_marker: str
    inline_position: str
    inline_position_source: str
    inline_position_confidence: str
    inline_offset: int
    confidence: str
    recovery_reason: str
    evidence: dict[str, Any]
