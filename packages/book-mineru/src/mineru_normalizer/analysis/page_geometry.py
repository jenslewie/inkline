"""Page coordinate-space geometry and bbox scaling. Centralises the heuristic that distinguishes MinerU rendered-pixel coordinates (~1000x1000) from native PDF-point coordinates (~425x680), and provides bbox scaling between the two."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..schema.models import BBox

@dataclass
class PageGeometry:
    """Coordinate-space geometry for pages, centralising bbox scale heuristics.

    MinerU extracts use one of two coordinate spaces:
      - PDF-point space (~425x680 for typical 6x9" book pages)
      - Rendered-pixel-like space (~1000x1000)
    The correct space is inferred from the max x/y values observed in blocks.
    """

    coord_widths: Dict[int, float] = field(default_factory=dict)
    coord_heights: Dict[int, float] = field(default_factory=dict)

    WIDTH_THRESHOLD = 650.0
    HEIGHT_THRESHOLD = 750.0
    NATIVE_W = 425.0
    NATIVE_H = 680.0
    RENDERED = 1000.0

    @classmethod
    def from_canonical_blocks(cls, blocks: Sequence[Dict[str, Any]]) -> PageGeometry:
        max_x: Dict[int, float] = {}
        max_y: Dict[int, float] = {}
        for b in blocks:
            p = _block_page(b)
            bb = _bbox(b)
            if p is None or not bb:
                continue
            max_x[p] = max(max_x.get(p, 0.0), float(bb[2]))
            max_y[p] = max(max_y.get(p, 0.0), float(bb[3]))
        return cls._from_max_coords(max_x, max_y)

    @classmethod
    def from_raw_pages(cls, pages: Dict[int, Sequence[Any]]) -> PageGeometry:
        max_x: Dict[int, float] = {}
        max_y: Dict[int, float] = {}
        for page, page_blocks in pages.items():
            for b in page_blocks:
                bbox = getattr(b, "bbox", None)
                if bbox:
                    max_x[page] = max(max_x.get(page, 0.0), float(bbox[2]))
                    max_y[page] = max(max_y.get(page, 0.0), float(bbox[3]))
        return cls._from_max_coords(max_x, max_y)

    @classmethod
    def _from_max_coords(cls, max_x: Dict[int, float], max_y: Dict[int, float]) -> PageGeometry:
        coord_widths: Dict[int, float] = {}
        coord_heights: Dict[int, float] = {}
        for p in sorted(set(max_x) | set(max_y)):
            x = max_x.get(p, 0.0)
            y = max_y.get(p, 0.0)
            if x > cls.WIDTH_THRESHOLD or y > cls.HEIGHT_THRESHOLD:
                coord_widths[p] = cls.RENDERED
                coord_heights[p] = cls.RENDERED
            else:
                coord_widths[p] = cls.NATIVE_W
                coord_heights[p] = cls.NATIVE_H
        return cls(coord_widths=coord_widths, coord_heights=coord_heights)

    def height(self, page: int) -> float:
        return self.coord_heights.get(page, self.RENDERED)

    def width(self, page: int) -> float:
        return self.coord_widths.get(page, self.RENDERED)

    def size(self, page: int) -> Tuple[float, float]:
        return self.coord_widths.get(page, self.RENDERED), self.coord_heights.get(page, self.RENDERED)

    def is_near_bottom(self, b: Dict[str, Any], threshold: float = 0.82) -> bool:
        p = _block_page(b)
        bb = _bbox(b)
        if p is None or not bb:
            return False
        return float(bb[3]) >= self.height(p) * threshold

    def is_near_top(self, b: Dict[str, Any], threshold: float = 0.22) -> bool:
        p = _block_page(b)
        bb = _bbox(b)
        if p is None or not bb:
            return False
        return float(bb[1]) <= self.height(p) * threshold

    def scale_bbox(self, page: int, bb: BBox, pdf_rect: Any, fallback_w: Optional[float] = None, fallback_h: Optional[float] = None) -> Tuple[float, float, float, float]:
        """Scale a coordinate-space bbox into PDF-point space.

        ``pdf_rect`` must have ``.width`` and ``.height`` attributes (e.g. a
        fitz page rect).  When ``fallback_w`` / ``fallback_h`` are omitted,
        they default to the ``pdf_rect`` dimensions.
        """
        coord_w = self.coord_widths.get(page, fallback_w or getattr(pdf_rect, "width", self.RENDERED))
        coord_h = self.coord_heights.get(page, fallback_h or getattr(pdf_rect, "height", self.RENDERED))
        rect_w = pdf_rect.width
        rect_h = pdf_rect.height
        width_mismatch = abs(coord_w - rect_w) / max(coord_w, rect_w, 1.0)
        height_mismatch = abs(coord_h - rect_h) / max(coord_h, rect_h, 1.0)
        if width_mismatch > 0.15 or height_mismatch > 0.15:
            sx = rect_w / coord_w
            sy = rect_h / coord_h
            return (float(bb[0]) * sx, float(bb[1]) * sy, float(bb[2]) * sx, float(bb[3]) * sy)
        return (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))

    def scale_bbox_inverse(self, page: int, rect: Any, pdf_page_rect: Any, coord_w: Optional[float] = None, coord_h: Optional[float] = None) -> list[float]:
        """Scale a PDF-point rect back into coordinate space.

        ``rect`` is the rectangle to convert.  ``pdf_page_rect`` is the full
        page rectangle (used to compute the scale factor).  When ``coord_w``
        and ``coord_h`` are omitted they come from the geometry map.
        """
        cw = coord_w if coord_w is not None else self.coord_widths.get(page, self.RENDERED)
        ch = coord_h if coord_h is not None else self.coord_heights.get(page, self.RENDERED)
        pdf_w = pdf_page_rect.width
        pdf_h = pdf_page_rect.height
        width_mismatch = abs(cw - pdf_w) / max(cw, pdf_w, 1.0)
        height_mismatch = abs(ch - pdf_h) / max(ch, pdf_h, 1.0)
        if width_mismatch > 0.15 or height_mismatch > 0.15:
            sx = cw / pdf_w
            sy = ch / pdf_h
            return [round(rect.x0 * sx, 3), round(rect.y0 * sy, 3), round(rect.x1 * sx, 3), round(rect.y1 * sy, 3)]
        return [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)]


def _block_page(block: Dict[str, Any]) -> Optional[int]:
    page = (block.get("source") or {}).get("page")
    return int(page) if page is not None else None


def _bbox(block: Dict[str, Any]) -> Optional[BBox]:
    box = (block.get("source") or {}).get("bbox")
    if isinstance(box, list) and len(box) >= 4:
        return box
    return None