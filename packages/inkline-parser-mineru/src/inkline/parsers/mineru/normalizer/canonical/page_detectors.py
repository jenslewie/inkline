"""Page-level classification helpers. Detects full-page images, title-only pages, snapshot/layout pages, and dominant blocks. Provides the coord_page_size heuristic shared by display quote detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .builders import union_bbox
from ..extraction.text import block_text
from ..schema.models import LayoutStats, RawBlock


def coord_page_size(blocks: Sequence[RawBlock], layout: LayoutStats) -> Tuple[float, float]:
    max_x = max((b.x1 for b in blocks if b.bbox), default=layout.page_width)
    max_y = max((b.y1 for b in blocks if b.bbox), default=layout.page_height)
    if max_x > layout.page_width * 1.2 or max_y > layout.page_height * 1.2 or max_x > 650 or max_y > 750:
        return 1000.0, 1000.0
    return layout.page_width, layout.page_height


def dominant_block(b: RawBlock, blocks: Sequence[RawBlock], layout: LayoutStats) -> bool:
    if not b.bbox:
        return False
    page_width, page_height = coord_page_size(blocks, layout)
    width_ratio = b.width / max(1.0, page_width)
    height_ratio = b.height / max(1.0, page_height)
    area_ratio = (b.width * b.height) / max(1.0, page_width * page_height)
    return (width_ratio >= 0.6 and height_ratio >= 0.45) or area_ratio >= 0.35


@dataclass(frozen=True)
class _LayoutSnapshotPageDetector:
    """Detect pages better represented as a single visual snapshot."""

    layout: LayoutStats
    prev_major_type: Optional[str]

    def detect(self, blocks: Sequence[RawBlock]) -> Tuple[bool, str]:
        page_edge_blocks = [b for b in blocks if b.raw_type in {"page_header", "page_footer"}]
        content_blocks = [b for b in blocks if b.raw_type not in {"page_number", "page_header", "page_footer"}]
        meaningful = [
            b
            for b in content_blocks
            if block_text(b) or b.raw_type in {"image", "chart", "table"}
        ]
        if not meaningful:
            return False, ""

        text_like = [b for b in meaningful if b.raw_type in {"paragraph", "title"} and block_text(b)]
        media_like = [b for b in meaningful if b.raw_type in {"image", "chart", "table"}]
        short_texts = [b for b in text_like if len(block_text(b)) <= 40]
        dense_metadata_layout = len(text_like) >= 18 and len(short_texts) >= max(14, int(len(text_like) * 0.8))
        body_width_long_text = [
            b
            for b in text_like
            if b.raw_type == "paragraph" and len(block_text(b)) > 80 and b.width >= self.layout.body_width * 0.75
        ]

        if any(b.raw_type == "chart" and dominant_block(b, meaningful, self.layout) for b in meaningful):
            return True, "page_chart"
        if self._is_dense_media_diagram(meaningful, media_like, text_like, short_texts):
            return True, "page_diagram"
        if self._is_visual_label_page(meaningful, text_like, media_like, body_width_long_text):
            return True, "visual_label_page"
        if media_like and len(page_edge_blocks) >= 4 and not body_width_long_text:
            return True, "designed_media_page"
        if self.prev_major_type == "full_page_image" and (
            dense_metadata_layout
            or len(page_edge_blocks) >= 3
            or (not body_width_long_text and 2 <= len(text_like) <= 8 and any(b.raw_type == "title" for b in text_like))
        ):
            return True, "designed_text_page"
        return False, ""

    @staticmethod
    def _is_dense_media_diagram(
        meaningful: Sequence[RawBlock],
        media_like: Sequence[RawBlock],
        text_like: Sequence[RawBlock],
        short_texts: Sequence[RawBlock],
    ) -> bool:
        return (
            len(meaningful) >= 18
            and bool(media_like)
            and len(short_texts) >= max(8, int(len(text_like) * 0.8))
        )

    def _is_visual_label_page(
        self,
        meaningful: Sequence[RawBlock],
        text_like: Sequence[RawBlock],
        media_like: Sequence[RawBlock],
        body_width_long_text: Sequence[RawBlock],
    ) -> bool:
        if body_width_long_text or len(text_like) < 4:
            return False
        page_width, page_height = coord_page_size(meaningful, self.layout)
        text_lengths = [len(block_text(b)) for b in text_like]
        short_count = sum(1 for length in text_lengths if length <= 40)
        if short_count < max(4, int(len(text_like) * 0.8)):
            return False
        if any(length > 60 for length in text_lengths):
            return False
        page_bbox = union_bbox([b.bbox for b in meaningful if b.bbox])
        if not page_bbox:
            return False
        x0, y0, x1, y1 = page_bbox
        coverage_width = (x1 - x0) / max(1.0, page_width)
        coverage_height = (y1 - y0) / max(1.0, page_height)
        text_centers_x = [((b.x0 + b.x1) / 2.0) for b in text_like if b.bbox]
        text_centers_y = [((b.y0 + b.y1) / 2.0) for b in text_like if b.bbox]
        if not text_centers_x or not text_centers_y:
            return False
        x_spread = (max(text_centers_x) - min(text_centers_x)) / max(1.0, page_width)
        y_spread = (max(text_centers_y) - min(text_centers_y)) / max(1.0, page_height)

        has_media = bool(media_like)
        media_or_dense_labels = has_media or len(text_like) >= 10
        if not media_or_dense_labels:
            return False
        if coverage_width < 0.55 or coverage_height < 0.45:
            return False
        if x_spread < 0.35 or y_spread < 0.25:
            return False
        return has_media or (len(text_like) >= 12 and coverage_width >= 0.65 and coverage_height >= 0.55)


def should_snapshot_layout_page(blocks: Sequence[RawBlock], layout: LayoutStats, prev_major_type: Optional[str]) -> Tuple[bool, str]:
    return _LayoutSnapshotPageDetector(layout=layout, prev_major_type=prev_major_type).detect(blocks)
