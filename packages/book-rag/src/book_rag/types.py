from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    doc_id: str
    book_id: str
    title: str
    author: str | None
    language: str | None
    source_path: str | None
    parser: str
    parser_mode: str
    chunk_type: str
    chunk_strategy: str
    text: str
    heading_path: list[str] = field(default_factory=list)
    chapter_title: str = ""
    page_start: int | None = None
    page_end: int | None = None
    block_ids: list[str] = field(default_factory=list)
    bbox_refs: list[dict] = field(default_factory=list)
    token_count: int = 0


@dataclass(slots=True)
class SearchResult:
    rank: int
    vector_id: int
    chunk_id: str
    book_id: str
    score: float
    title: str
    chapter_title: str
    source_path: str
    text: str


def dataclass_to_dict(value) -> dict:
    return asdict(value)
