"""I/O utilities for MinerU source data. Loads content_list_v2, content_list, middle.json, and model JSON files. Flattens nested content structures into page-level block lists."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from ..schema.models import NoteRef, RawBlock
from .text import extract_list_item_text, extract_text_notes_and_runs, normalize_ws

def load_json(path: Optional[str]) -> Any:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def page_sizes_from_middle(middle: Any) -> Dict[int, Tuple[float, float]]:
    sizes: Dict[int, Tuple[float, float]] = {}
    if isinstance(middle, dict) and isinstance(middle.get("pdf_info"), list):
        for i, p in enumerate(middle["pdf_info"], 1):
            ps = p.get("page_size") or []
            if len(ps) >= 2:
                sizes[i] = (float(ps[0]), float(ps[1]))
    return sizes


def flatten_content_list_v2(content_list_v2: List[Any]) -> Dict[int, List[RawBlock]]:
    pages: Dict[int, List[RawBlock]] = {}
    for p_idx, page_items in enumerate(content_list_v2, 1):
        pages[p_idx] = []
        if not isinstance(page_items, list):
            continue
        for i, item in enumerate(page_items):
            if not isinstance(item, dict):
                continue
            typ = item.get("type", "unknown")
            text = ""
            notes: List[NoteRef] = []
            inline_runs: List[Dict[str, Any]] = []
            if typ == "list":
                # Keep list as a block; list items are expanded later when needed.
                text, notes, inline_runs = extract_text_notes_and_runs(item.get("content", {}))
            elif typ in {"image", "table"}:
                # Image/table text is handled from typed fields, not via full recursion.
                text = ""
            else:
                text, notes, inline_runs = extract_text_notes_and_runs(item.get("content", {}))
            bbox = item.get("bbox")
            pages[p_idx].append(RawBlock(page=p_idx, index=i, raw_type=typ, text=text, bbox=bbox, raw=item, note_refs=notes, inline_runs=inline_runs))
    return pages


def flatten_content_list_legacy(content_list: List[Any]) -> Dict[int, List[RawBlock]]:
    pages: Dict[int, List[RawBlock]] = {}
    for i, item in enumerate(content_list):
        if not isinstance(item, dict):
            continue
        p = int(item.get("page_idx", 0)) + 1
        pages.setdefault(p, [])
        typ = item.get("type", "unknown")
        text = normalize_ws(str(item.get("text", "")))
        pages[p].append(RawBlock(page=p, index=len(pages[p]), raw_type=typ, text=text, bbox=item.get("bbox"), raw=item, note_refs=[]))
    return pages
