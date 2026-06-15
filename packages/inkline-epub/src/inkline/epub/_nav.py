from __future__ import annotations

import re
from html import escape
from typing import Any

from inkline.epub._chapter import Chapter


def nav_xhtml(
    metadata: dict[str, Any],
    chapters: list[Chapter],
    *,
    toc: list[dict[str, Any]] | None = None,
    toc_heading_ids: set[str] | None = None,
) -> str:
    toc = toc or []
    toc_heading_ids = toc_heading_ids or set()
    # Build mapping from heading block_id -> chapter index
    heading_to_chapter: dict[str, int] = {}
    for index, chapter in enumerate(chapters, 1):
        if chapter.source_block_id and chapter.source_block_id in toc_heading_ids:
            heading_to_chapter[chapter.source_block_id] = index

    # Build a reverse lookup: toc entry title -> first matching chapter index
    # (for toc entries whose source_block_id is a toc_item, not a heading)
    toc_title_to_chapter: dict[str, int] = {}
    block_by_id: dict[str, dict[str, Any]] = {}
    for b in metadata.get("_blocks", []):
        bid = b.get("block_id")
        if bid:
            block_by_id[bid] = b
    # We don't have blocks here, so match by title
    for entry in toc:
        toc_title = entry.get("title", "").strip()
        # Try to find a chapter whose title matches this toc entry
        for index, chapter in enumerate(chapters, 1):
            # Direct block_id match
            if chapter.source_block_id and entry.get("source_block_id") == chapter.source_block_id:
                toc_title_to_chapter[toc_title] = index
                break
            # Title match: chapter title is first line of heading text,
            # toc title may have different formatting (e.g. "第一章 楼 兰" vs "第一章\n楼兰")
            ch_first = chapter.title.split("\n", 1)[0].strip()
            if ch_first and (
                ch_first == toc_title
                or toc_title.startswith(ch_first)
                or ch_first.startswith(toc_title.split("：", 1)[0].split(" ", 1)[0])
            ):
                toc_title_to_chapter.setdefault(toc_title, index)
                break

    # Build nav items from TOC entries
    items_parts: list[str] = []
    for entry in toc:
        toc_title = entry.get("title", "")
        # Find the chapter this toc entry points to
        chapter_index = heading_to_chapter.get(
            entry.get("source_block_id") or entry.get("block_id") or ""
        )
        if not chapter_index:
            chapter_index = toc_title_to_chapter.get(toc_title.strip())
        href = f"chapter_{chapter_index:04d}.xhtml" if chapter_index else "chapter_0001.xhtml"
        label = escape(toc_title)
        items_parts.append(f'    <li><a href="{href}">{label}</a></li>')
    items = "\n".join(items_parts)
    lang = escape(metadata.get("language") or "zh-CN", quote=True)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">
<head>
  <title>Contents</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Contents</h1>
    <ol>
{items}
    </ol>
  </nav>
</body>
</html>
"""


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
    for b in blocks:
        bid = b.get("block_id")
        if bid:
            block_by_id[bid] = b

    # Direct match: toc source_block_id is a heading
    result: set[str] = set()
    for entry in toc:
        bid = entry.get("source_block_id") or entry.get("block_id")
        if bid and bid in block_by_id and block_by_id[bid].get("type") == "heading":
            result.add(bid)

    if result:
        return result

    # Fuzzy match: normalize both toc titles and heading texts, then walk
    # through headings in order and greedily assign each to the next
    # unmatched toc entry whose normalized title matches.
    heading_blocks = [b for b in blocks if b.get("type") == "heading"]
    toc_queue = list(toc)  # copy so we can pop from front
    h_idx = 0

    def _normalize(s: str) -> str:
        """Strip whitespace, punctuation, and common separators for fuzzy matching."""
        return re.sub(r"[\s　：:，,。.！！？?·、\-—]+", "", s)

    for entry in toc_queue:
        toc_norm = _normalize(entry.get("title", ""))
        if not toc_norm:
            continue
        # Walk through headings starting from h_idx to find a match
        while h_idx < len(heading_blocks):
            hb = heading_blocks[h_idx]
            # Heading text may contain newlines (e.g. "第一章\n楼兰\n...")
            h_norm = _normalize(hb.get("text", ""))
            h_first_norm = _normalize(hb.get("text", "").split("\n", 1)[0])
            # Match if the heading's first line or full normalized text
            # overlaps with the toc title's normalized text.
            if (
                h_norm == toc_norm
                or h_first_norm == toc_norm
                or toc_norm.startswith(h_first_norm)
                or h_first_norm.startswith(toc_norm[:6])  # prefix match on first few chars
                or (
                    len(h_first_norm) >= 3
                    and len(toc_norm) >= 3
                    and h_first_norm[:3] == toc_norm[:3]
                    and h_first_norm in toc_norm
                )
            ):
                result.add(hb["block_id"])
                h_idx += 1
                break
            h_idx += 1

    return result
