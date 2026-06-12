"""Page layout statistics inference.

Infers body-width margins, page dimensions, and page-level classification
signals (full-page images, title-only pages, display_block layout). Used by
both the canonical page-processing pipeline and the reconciliation passes.
"""

from __future__ import annotations

from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from ..schema.models import LayoutStats, RawBlock
from ..schema.patterns import ATTR_RE
from ..extraction.text import block_text

def infer_layout_stats(pages: Dict[int, List[RawBlock]], page_sizes: Dict[int, Tuple[float, float]]) -> LayoutStats:
    widths = [w for w, h in page_sizes.values() if w]
    heights = [h for w, h in page_sizes.values() if h]
    page_width = median(widths) if widths else 1000.0
    page_height = median(heights) if heights else 1000.0

    x0s: List[float] = []
    x1s: List[float] = []
    for page, blocks in pages.items():
        if page < 20:  # front plates/cover often have captions, not body.
            continue
        for b in blocks:
            if b.raw_type != "paragraph" or not b.bbox:
                continue
            t = block_text(b)
            if len(t) < 60:
                continue
            # Normal body paragraphs are wide and start near a stable margin.
            if b.width > page_width * 0.55:
                x0s.append(b.x0)
                x1s.append(b.x1)
    body_left = median(x0s) if x0s else page_width * 0.13
    body_right = median(x1s) if x1s else page_width * 0.88
    return LayoutStats(page_width=page_width, page_height=page_height, body_left=body_left, body_right=body_right)


def is_short_or_indented(b: RawBlock, layout: LayoutStats) -> bool:
    if not b.bbox:
        return False
    return b.x0 >= layout.body_left + 35 or b.width <= layout.body_width * 0.82


def is_display_block_layout_raw(b: RawBlock, layout: LayoutStats) -> bool:
    """Looser layout test for display blocks after an explicit introducer.

    Some MinerU VLM paragraph boxes are the union of several rendered lines, so
    a true display block may only be mildly indented in bbox terms. Use this only
    with a strong textual trigger such as a preceding colon / 上书 / 诏书.
    """
    if not b.bbox:
        return False
    return b.x0 >= layout.body_left + 18 or b.width <= layout.body_width * 0.95


def is_right_aligned_short(b: RawBlock, layout: LayoutStats) -> bool:
    return bool(b.bbox and len(block_text(b)) <= 20 and b.x0 > layout.body_left + layout.body_width * 0.65)


def page_has_images(blocks: Sequence[RawBlock]) -> bool:
    return any(b.raw_type == "image" for b in blocks)


def is_full_page_image_page(blocks: Sequence[RawBlock], layout: LayoutStats) -> bool:
    content = [
        b for b in blocks
        if b.raw_type not in {"page_number", "page_header", "page_footer"} and (block_text(b) or b.raw_type in {"image", "table"})
    ]
    images = [b for b in content if b.raw_type == "image" and b.bbox]
    if len(images) != 1:
        return False
    text_blocks = [b for b in content if b.raw_type in {"paragraph", "title"} and block_text(b)]
    if not text_blocks:
        return False
    if any(len(block_text(b)) > 24 for b in text_blocks):
        return False
    if any(b.raw_type not in {"image", "paragraph", "title"} for b in content):
        return False
    img = images[0]
    union_x0 = min(b.x0 for b in content if b.bbox)
    union_y0 = min(b.y0 for b in content if b.bbox)
    union_x1 = max(b.x1 for b in content if b.bbox)
    union_y1 = max(b.y1 for b in content if b.bbox)
    union_width = union_x1 - union_x0
    union_height = union_y1 - union_y0
    coord_page_height = 1000.0 if union_x1 > 650 or union_y1 > 750 else layout.page_height
    if img.width < layout.body_width * 0.95 and union_width < layout.body_width * 1.05:
        return False
    if union_height < coord_page_height * 0.55:
        return False
    # The over-split labels should be visually part of the image region: either
    # inside the image bounds or immediately attached to its cropped edge.
    for b in text_blocks:
        horizontally_inside = b.x0 >= img.x0 - 20 and b.x1 <= img.x1 + 20
        vertically_attached = b.y0 <= img.y1 + coord_page_height * 0.12
        if not (horizontally_inside and vertically_attached):
            return False
    return True


def is_title_only_page(blocks: Sequence[RawBlock]) -> bool:
    content = [b for b in blocks if b.raw_type not in {"page_number", "page_header", "page_footer"} and (block_text(b) or b.raw_type in {"image", "table"})]
    if not content:
        return False
    if all(b.raw_type == "title" for b in content) and len(content) <= 3:
        return True
    textual = [b for b in content if b.raw_type in {"paragraph", "title"} and block_text(b)]
    if len(textual) != len(content) or len(textual) > 4 or not any(b.raw_type == "title" for b in textual):
        return False
    return all(len(block_text(b)) <= 24 for b in textual)


def has_attribution_line(blocks: Sequence[RawBlock]) -> bool:
    return any(ATTR_RE.match(block_text(b) or "") for b in blocks if b.raw_type == "paragraph")
