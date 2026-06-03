from __future__ import annotations

from typing import Any


def bbox_ref(block: dict[str, Any]) -> dict[str, Any] | None:
    source = block.get("source") or {}
    page = source.get("page")
    bbox = source.get("bbox")
    if page is None:
        return None
    return {"page": page, "bbox": bbox}
