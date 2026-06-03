"""Block accessor helpers. Low-level functions for reading canonical block metadata: block_page(), block_bbox(), block_id(), block_pages(). Extracted from common.py; used by nearly every reconciliation module."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schema.models import BBox


def block_id(b: Dict[str, Any]) -> str:
    return str(b.get("block_id") or b.get("id") or "")


def block_page(b: Dict[str, Any]) -> Optional[int]:
    return (b.get("source") or {}).get("page")


def block_pages(b: Dict[str, Any]) -> List[int]:
    src = b.get("source") or {}
    pages = src.get("pages") or ([src.get("page")] if src.get("page") is not None else [])
    return [int(p) for p in pages if p is not None]


def block_bbox(b: Dict[str, Any]) -> Optional[BBox]:
    src = b.get("source") or {}
    box = src.get("bbox")
    if isinstance(box, list) and len(box) >= 4:
        return box
    return None
