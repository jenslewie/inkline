"""Block navigation helpers for reconciliation passes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import FLOAT_LIKE_TYPES


def _prev_text_non_float(blocks: List[Dict[str, Any]], idx: int) -> str:
    k = idx - 1
    while k >= 0:
        if blocks[k].get("type") not in FLOAT_LIKE_TYPES:
            return str(blocks[k].get("text", ""))
        k -= 1
    return ""


def _prev_text_non_float_idx(blocks: List[Dict[str, Any]], idx: int) -> Optional[int]:
    k = idx - 1
    while k >= 0:
        if blocks[k].get("type") not in FLOAT_LIKE_TYPES:
            return k
        k -= 1
    return None


def _next_text_non_float_idx(blocks: List[Dict[str, Any]], idx: int) -> Optional[int]:
    k = idx + 1
    while k < len(blocks):
        if blocks[k].get("type") not in FLOAT_LIKE_TYPES:
            return k
        k += 1
    return None