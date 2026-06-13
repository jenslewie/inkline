"""Page-top set-off display block detection. Detects indented blocks at the top of a page that continue a display run from a previous page, and reconciles them with the display lane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import FOOTNOTE, PARAGRAPH
from ..block_access import block_bbox as _bbox
from ..block_access import block_page as _block_page
from ..block_nav import _prev_text_non_float
from ..constants import FLOAT_LIKE_TYPES
from ..layout_helpers import _is_near_page_top, _page_coord_heights
from .helpers import force_generic_display_block_attrs


@dataclass(frozen=True)
class _PageTopSetOffDisplayDetector:
    """Detect page-top text blocks that are visually set off from body prose."""

    layout: LayoutStats
    page_heights: Dict[int, float]

    def matches(self, blocks: List[Dict[str, Any]], idx: int) -> bool:
        cur = blocks[idx]
        bb = _bbox(cur)
        page = _block_page(cur)
        text = str(cur.get("text", "")).strip()
        if cur.get("type") != PARAGRAPH or page is None or not bb or not text:
            return False
        if not self._has_candidate_position_and_measure(cur, text, bb):
            return False
        if self._has_prior_same_page_content(blocks, idx, page, float(bb[1])):
            return False
        return self._has_following_same_page_separation(blocks, idx, page, bb)

    def _has_candidate_position_and_measure(
        self, cur: Dict[str, Any], text: str, bb: List[float]
    ) -> bool:
        if not _is_near_page_top(cur, self.page_heights):
            return False
        if len(text) < 45 or len(text) > 220:
            return False
        if text.endswith(("：", ":")):
            return False
        width = float(bb[2]) - float(bb[0])
        if float(bb[0]) < self.layout.body_left + 28:
            return False
        return width <= self.layout.body_width * 0.96

    def _has_prior_same_page_content(
        self, blocks: List[Dict[str, Any]], idx: int, page: int, top: float
    ) -> bool:
        for j in range(idx - 1, -1, -1):
            prev = blocks[j]
            if prev.get("type") in FLOAT_LIKE_TYPES or prev.get("type") == FOOTNOTE:
                continue
            if self._block_has_span_above_on_page(prev, page, top):
                return True
            prev_page = _block_page(prev)
            if prev_page != page:
                if prev_page is not None:
                    break
                continue
            return True
        return False

    @staticmethod
    def _block_has_span_above_on_page(block: Dict[str, Any], page: int, top: float) -> bool:
        for span in (block.get("source") or {}).get("spans") or []:
            if span.get("page") != page:
                continue
            span_bbox = span.get("bbox")
            if isinstance(span_bbox, list) and len(span_bbox) >= 4 and float(span_bbox[3]) <= top:
                return True
        return False

    def _has_following_same_page_separation(
        self, blocks: List[Dict[str, Any]], idx: int, page: int, bb: List[float]
    ) -> bool:
        block_height = float(bb[3]) - float(bb[1])
        min_gap = max(20.0, block_height * 0.30)
        for j in range(idx + 1, min(len(blocks), idx + 5)):
            nxt = blocks[j]
            if _block_page(nxt) != page:
                break
            if nxt.get("type") in FLOAT_LIKE_TYPES or nxt.get("type") == FOOTNOTE:
                continue
            nbb = _bbox(nxt)
            if not nbb:
                return False
            return float(nbb[1]) - float(bb[3]) >= min_gap
        return False


def reconcile_page_top_set_off_display_blocks(
    blocks: List[Dict[str, Any]], layout: LayoutStats
) -> None:
    """Promote page-top paragraphs that are laid out as standalone display text."""
    detector = _PageTopSetOffDisplayDetector(
        layout=layout, page_heights=_page_coord_heights(blocks)
    )
    for i, cur in enumerate(blocks):
        if not detector.matches(blocks, i):
            continue
        force_generic_display_block_attrs(
            cur,
            prev_text=_prev_text_non_float(blocks, i),
            evidence="page_top_set_off_display_layout",
        )
