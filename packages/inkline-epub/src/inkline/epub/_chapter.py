from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chapter:
    title: str
    body: str
    source_block_id: str | None
