"""Page-level metadata classification for canonical output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

from ..extraction.text import normalize_ws
from ..schema.block_types import DISPLAY_BLOCK, HEADING, LIST_ITEM, PARAGRAPH, TABLE
from ..schema.models import LayoutStats, RawBlock
from .page_detectors import body_text_like_page, should_snapshot_layout_page

_COPYRIGHT_RE = re.compile(r"(?:ISBN|CIP|版权|Copyright|出版|印刷|定价|版权所有)")
_STRICT_COPYRIGHT_RE = re.compile(r"(?:CIP|版权|Copyright|版权所有)")
_AUTHOR_RE = re.compile(r"(?:著|作者|出版社|Publishing|Press)", re.IGNORECASE)


@dataclass(frozen=True)
class PageAnalysis:
    physical_page: int
    snapshot: bool
    snapshot_role: str
    region: str
    page_role: str
    confidence: str
    signals: tuple[str, ...]


def build_page_metadata(
    pages: Dict[int, List[RawBlock]],
    layout: LayoutStats,
    *,
    title: str | None,
    blocks: Sequence[dict[str, Any]],
) -> List[dict[str, Any]]:
    """Build parser-neutral metadata for physical pages.

    Roles intentionally use high-confidence deterministic signals only. Unknown
    or ambiguous pages keep a coarse ``generic`` role instead of guessing.
    """

    analyses = _analyze_pages(pages, layout, title=title, blocks=blocks)
    return [
        {
            "physical_page": item.physical_page,
            "region": item.region,
            "page_role": item.page_role,
            "snapshot": {
                "required": item.snapshot,
                "role": item.snapshot_role or None,
            },
            "classification": {
                "method": "position_layout_text_rule",
                "confidence": item.confidence,
                "signals": list(item.signals),
            },
        }
        for item in analyses
    ]


def _analyze_pages(
    pages: Dict[int, List[RawBlock]],
    layout: LayoutStats,
    *,
    title: str | None,
    blocks: Sequence[dict[str, Any]],
) -> List[PageAnalysis]:
    first_content_page = _first_content_page(blocks)
    last_content_page = _last_content_page(blocks)
    out: List[PageAnalysis] = []
    page_numbers = sorted(pages)
    for page in page_numbers:
        raw_blocks = pages[page]
        snapshot, snapshot_role = should_snapshot_layout_page(raw_blocks, layout)
        region = _region_for_page(page, first_content_page, last_content_page)
        page_role, confidence, signals = _page_role_for_page(
            page,
            raw_blocks,
            layout,
            title=title,
            region=region,
            snapshot=snapshot,
            snapshot_role=snapshot_role,
            first_page=page_numbers[0] if page_numbers else page,
            last_page=page_numbers[-1] if page_numbers else page,
        )
        out.append(
            PageAnalysis(
                physical_page=page,
                snapshot=snapshot,
                snapshot_role=snapshot_role,
                region=region,
                page_role=page_role,
                confidence=confidence,
                signals=tuple(signals),
            )
        )
    return out


def _first_content_page(blocks: Sequence[dict[str, Any]]) -> int | None:
    for block in blocks:
        role = (block.get("attrs") or {}).get("role")
        text = normalize_ws(str(block.get("text") or ""))
        page = (block.get("source") or {}).get("page")
        if not isinstance(page, int):
            continue
        if role in {"chapter_title", "part_title"} or re.match(
            r"^(?:第[一二三四五六七八九十百零〇0-9]+[章节部篇]|[一二三四五六七八九十百零〇0-9]+[、.．])",
            text,
        ):
            return page
    return None


def _last_content_page(blocks: Sequence[dict[str, Any]]) -> int | None:
    pages = [
        (block.get("source") or {}).get("page")
        for block in blocks
        if block.get("type") in {HEADING, PARAGRAPH, DISPLAY_BLOCK, TABLE, LIST_ITEM}
        and (block.get("source") or {}).get("page")
    ]
    return max((int(page) for page in pages if isinstance(page, int)), default=None)


def _region_for_page(
    page: int, first_content_page: int | None, last_content_page: int | None
) -> str:
    if first_content_page is not None and page < first_content_page:
        return "front_matter"
    if last_content_page is not None and page > last_content_page:
        return "back_matter"
    return "content" if first_content_page is not None else "unknown"


def _page_role_for_page(
    page: int,
    raw_blocks: Sequence[RawBlock],
    layout: LayoutStats,
    *,
    title: str | None,
    region: str,
    snapshot: bool,
    snapshot_role: str,
    first_page: int,
    last_page: int,
) -> tuple[str, str, List[str]]:
    text = _page_text(raw_blocks)
    compact_text = _compact(text)
    compact_title = _compact(title or "")
    signals: List[str] = []
    if snapshot:
        signals.append(f"snapshot:{snapshot_role}")
    if compact_title and compact_title in compact_text:
        signals.append("metadata_title_match")
    if body_text_like_page(raw_blocks, layout):
        signals.append("body_text_layout")

    if page == first_page and snapshot and compact_title and compact_title in compact_text:
        return "cover", "high", [*signals, "first_page"]
    if (
        region == "front_matter"
        and _STRICT_COPYRIGHT_RE.search(text)
        and len(_COPYRIGHT_RE.findall(text)) >= 3
    ):
        return "copyright_page", "high", [*signals, "copyright_markers"]
    text_like_count = sum(
        1 for block in raw_blocks if block.raw_type in {"paragraph", "title"} and block.text
    )
    if (
        region == "front_matter"
        and text_like_count <= 8
        and compact_title
        and compact_title in compact_text
        and _AUTHOR_RE.search(text)
    ):
        return "title_page", "high", [*signals, "title_author_publisher_markers"]
    if page == last_page and snapshot and region == "back_matter":
        return "back_cover", "medium", [*signals, "last_page"]
    if region in {"front_matter", "back_matter", "content"}:
        return "generic", "medium", signals or [f"region:{region}"]
    return "unknown", "low", signals


def _page_text(blocks: Iterable[RawBlock]) -> str:
    return normalize_ws("\n".join(block.text for block in blocks if block.text))


def _compact(text: str) -> str:
    return "".join(normalize_ws(text).lower().split())
