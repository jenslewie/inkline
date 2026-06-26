from __future__ import annotations

import re
from typing import Any

from inkline.epub.chapter.model import Chapter
from inkline.epub.navigation.model import NavItem, NavView


def resolve_nav_view(
    metadata: dict[str, Any],
    chapters: list[Chapter],
    *,
    toc: list[dict[str, Any]] | None = None,
    toc_heading_ids: set[str] | None = None,
) -> NavView:
    toc = toc or []
    toc_heading_ids = toc_heading_ids or set()
    heading_to_chapter = _heading_to_chapter_index(chapters, toc_heading_ids)
    toc_title_to_chapter = _toc_title_to_chapter_index(toc, chapters)

    items: list[NavItem] = []
    for entry in toc:
        toc_title = entry.get("title", "")
        chapter_index = heading_to_chapter.get(
            entry.get("source_block_id") or entry.get("block_id") or ""
        )
        if not chapter_index:
            chapter_index = toc_title_to_chapter.get(toc_title.strip())
        href = f"chapter_{chapter_index:04d}.xhtml" if chapter_index else "chapter_0001.xhtml"
        items.append(NavItem(label=toc_title, href=href))

    return NavView(language=metadata.get("language") or "zh-CN", items=items)


def toc_heading_block_ids(document: dict[str, Any]) -> set[str]:
    """Return the set of heading block_ids that correspond to TOC entries.

    TOC ``source_block_id`` usually points to a ``toc_item`` block (the entry
    on the book's printed TOC page), not the actual heading in the body.  We
    therefore match TOC entries to heading blocks by fuzzy title comparison
    and sequential ordering.
    """
    toc = document.get("toc", [])
    blocks = document["blocks"]
    block_by_id: dict[str, dict[str, Any]] = {}
    for block in blocks:
        block_id = block.get("block_id")
        if block_id:
            block_by_id[block_id] = block

    result: set[str] = set()
    for entry in toc:
        block_id = entry.get("source_block_id") or entry.get("block_id")
        if block_id and block_id in block_by_id and block_by_id[block_id].get("type") == "heading":
            result.add(block_id)

    if result:
        return result

    heading_blocks = [block for block in blocks if block.get("type") == "heading"]
    heading_index = 0

    for entry in toc:
        toc_norm = _normalize_toc_title(entry.get("title", ""))
        if not toc_norm:
            continue
        while heading_index < len(heading_blocks):
            heading_block = heading_blocks[heading_index]
            heading_norm = _normalize_toc_title(heading_block.get("text", ""))
            heading_first_norm = _normalize_toc_title(
                heading_block.get("text", "").split("\n", 1)[0]
            )
            if _toc_title_matches_heading(toc_norm, heading_norm, heading_first_norm):
                result.add(heading_block["block_id"])
                heading_index += 1
                break
            heading_index += 1

    return result


def _heading_to_chapter_index(
    chapters: list[Chapter],
    toc_heading_ids: set[str],
) -> dict[str, int]:
    heading_to_chapter: dict[str, int] = {}
    for index, chapter in enumerate(chapters, 1):
        if chapter.source_block_id and chapter.source_block_id in toc_heading_ids:
            heading_to_chapter[chapter.source_block_id] = index
    return heading_to_chapter


def _toc_title_to_chapter_index(
    toc: list[dict[str, Any]],
    chapters: list[Chapter],
) -> dict[str, int]:
    toc_title_to_chapter: dict[str, int] = {}
    for entry in toc:
        toc_title = entry.get("title", "").strip()
        for index, chapter in enumerate(chapters, 1):
            if chapter.source_block_id and entry.get("source_block_id") == chapter.source_block_id:
                toc_title_to_chapter[toc_title] = index
                break
            ch_first = chapter.title.split("\n", 1)[0].strip()
            if ch_first and (
                ch_first == toc_title
                or toc_title.startswith(ch_first)
                or ch_first.startswith(toc_title.split("：", 1)[0].split(" ", 1)[0])
            ):
                toc_title_to_chapter.setdefault(toc_title, index)
                break
    return toc_title_to_chapter


def _normalize_toc_title(text: str) -> str:
    return re.sub(r"[\s　：:，,。.！！？?·、\-—]+", "", text)


def _toc_title_matches_heading(
    toc_norm: str,
    heading_norm: str,
    heading_first_norm: str,
) -> bool:
    return (
        heading_norm == toc_norm
        or heading_first_norm == toc_norm
        or toc_norm.startswith(heading_first_norm)
        or heading_first_norm.startswith(toc_norm[:6])
        or (
            len(heading_first_norm) >= 3
            and len(toc_norm) >= 3
            and heading_first_norm[:3] == toc_norm[:3]
            and heading_first_norm in toc_norm
        )
    )
