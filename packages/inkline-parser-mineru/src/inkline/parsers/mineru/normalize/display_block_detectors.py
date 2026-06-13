"""Raw set-off display run detection. Identifies spans of raw blocks that share a visual display lane (indented, set-off from body text). Used by the display block collection logic during page processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from ..analysis.layout import is_display_block_layout_raw
from ..extraction.text import block_text
from ..schema.models import LayoutStats, RawBlock


@dataclass(frozen=True)
class RawSetOffDisplayRunDetector:
    """Detect same-page runs visually set off from surrounding body text."""

    layout: LayoutStats

    def collect(self, blocks: List[RawBlock], start: int) -> Tuple[List[RawBlock], int]:
        if start >= len(blocks) or not self._is_candidate(blocks[start]):
            return [], start
        group = [blocks[start]]
        end = start + 1
        while end < len(blocks) and self._is_adjacent_to_run(group[-1], blocks[end]):
            group.append(blocks[end])
            end += 1
        if len(group) < 2 or not self._has_body_boundaries(blocks, start, end):
            return [], start
        return group, end

    def _is_candidate(self, block: RawBlock) -> bool:
        if block.raw_type != "paragraph" or not block.bbox or not block_text(block):
            return False
        if block.width > self.layout.body_width * 0.96:
            return False
        return is_display_block_layout_raw(block, self.layout)

    def _is_adjacent_to_run(self, previous: RawBlock, candidate: RawBlock) -> bool:
        if candidate.page != previous.page or not self._is_candidate(candidate):
            return False
        aligned_left = abs(candidate.x0 - previous.x0) <= 28
        within_run_width = candidate.x1 <= max(previous.x1, self.layout.body_right) + 32
        return aligned_left and within_run_width

    def _has_body_boundaries(self, blocks: List[RawBlock], start: int, end: int) -> bool:
        first = blocks[start]
        last = blocks[end - 1]
        if block_text(first).rstrip().endswith(("：", ":")):
            return False
        gap_threshold = max(20.0, min(first.height, last.height) * 0.55)
        return self._has_previous_body_boundary(
            blocks, start, first, gap_threshold
        ) and self._has_next_body_boundary(blocks, end, last, gap_threshold)

    def _has_previous_body_boundary(
        self, blocks: List[RawBlock], start: int, first: RawBlock, gap_threshold: float
    ) -> bool:
        if start <= 0:
            return False
        prev = blocks[start - 1]
        if prev.page != first.page or prev.raw_type != "paragraph" or not prev.bbox:
            return False
        if first.y0 - prev.y1 < gap_threshold:
            return False
        return len(block_text(prev)) >= 60 and prev.width >= self.layout.body_width * 0.88

    def _has_next_body_boundary(
        self, blocks: List[RawBlock], end: int, last: RawBlock, gap_threshold: float
    ) -> bool:
        if end >= len(blocks):
            return False
        nxt = blocks[end]
        if nxt.page != last.page or nxt.raw_type != "paragraph" or not nxt.bbox:
            return False
        if nxt.y0 - last.y1 < gap_threshold:
            return False
        if self._is_candidate(nxt) and abs(nxt.x0 - last.x0) <= 28:
            return False
        return len(block_text(nxt)) >= 30 and nxt.width >= self.layout.body_width * 0.88
