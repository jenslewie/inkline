"""Text style metrics estimation. Estimates font size, line height, and visual text size for canonical blocks using PyMuPDF text-layer spans (preferred) or rendered page images (scanned PDF fallback). Provides TextStyleAnalyzer as the main interface."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..schema.block_types import DISPLAY_BLOCK, LIST_ITEM, PARAGRAPH
from ..schema.models import BBox
from .pdf_page_metrics import PdfPageCache, line_bands


@dataclass(frozen=True)
class TextStyleMetrics:
    """Text style evidence for a block.

    `font_size` comes from a PDF text layer when available. `visual_size` is an
    estimated ink height from a rendered page image, used for scanned PDFs.
    """

    source: str
    line_count: int
    font_size: Optional[float] = None
    visual_size: Optional[float] = None
    line_height: Optional[float] = None
    fonts: Tuple[str, ...] = ()
    confidence: str = "low"

    @property
    def comparable_size(self) -> Optional[float]:
        return self.font_size if self.font_size is not None else self.visual_size


class TextStyleAnalyzer:
    """Estimate font/style metrics for canonical blocks.

    The analyzer prefers PyMuPDF span font sizes. When the PDF has no text
    layer, it estimates visual text size from rendered page pixels.
    """

    def __init__(
        self,
        pdf_path: Optional[str],
        page_coord_sizes: Optional[Dict[int, Tuple[float, float]]] = None,
        *,
        render_zoom: float = 2.0,
    ) -> None:
        self._cache = PdfPageCache(pdf_path, page_coord_sizes, render_zoom=render_zoom)
        self._block_metrics_cache: Dict[str, Optional[TextStyleMetrics]] = {}
        self._page_body_cache: Dict[int, Optional[TextStyleMetrics]] = {}

    @classmethod
    def from_blocks(cls, pdf_path: Optional[str], blocks: Sequence[Dict[str, Any]]) -> "TextStyleAnalyzer":
        from .page_geometry import PageGeometry

        geo = PageGeometry.from_canonical_blocks(blocks)
        sizes = {p: (geo.coord_widths[p], geo.coord_heights[p]) for p in geo.coord_widths}
        return cls(pdf_path, sizes)

    @classmethod
    def from_raw_pages(cls, pdf_path: Optional[str], pages: Dict[int, Sequence[Any]]) -> "TextStyleAnalyzer":
        from .page_geometry import PageGeometry

        geo = PageGeometry.from_raw_pages(pages)
        sizes = {p: (geo.coord_widths[p], geo.coord_heights[p]) for p in geo.coord_widths}
        return cls(pdf_path, sizes)

    def close(self) -> None:
        self._cache.close()

    def block_metrics(self, block: Dict[str, Any]) -> Optional[TextStyleMetrics]:
        block_id = str(block.get("block_id") or id(block))
        if block_id in self._block_metrics_cache:
            return self._block_metrics_cache[block_id]
        metrics = self._text_layer_metrics(block) or self._image_metrics(block)
        self._block_metrics_cache[block_id] = metrics
        return metrics

    def block_style_size(self, block: Dict[str, Any]) -> Optional[float]:
        metrics = self.block_metrics(block)
        return metrics.comparable_size if metrics else None

    def raw_block_metrics(self, block: Any) -> Optional[TextStyleMetrics]:
        return self.block_metrics(_raw_block_as_canonical(block))

    def raw_block_style_size(self, block: Any) -> Optional[float]:
        metrics = self.raw_block_metrics(block)
        return metrics.comparable_size if metrics else None

    def raw_page_body_style_size(self, page: int, blocks: Sequence[Any]) -> Optional[float]:
        pseudo_blocks = []
        for block in blocks:
            raw_type = getattr(block, "raw_type", None)
            if raw_type not in {"paragraph", "list_item"}:
                continue
            if getattr(block, "page", None) != page:
                continue
            pseudo_blocks.append(_raw_block_as_canonical(block))
        return self.page_body_style_size(page, pseudo_blocks)

    def page_body_metrics(self, page: int, blocks: Sequence[Dict[str, Any]]) -> Optional[TextStyleMetrics]:
        if page in self._page_body_cache:
            return self._page_body_cache[page]
        sizes: List[float] = []
        line_heights: List[float] = []
        sources: List[str] = []
        for block in blocks:
            if block.get("type") not in {PARAGRAPH, LIST_ITEM, DISPLAY_BLOCK}:
                continue
            if _block_page(block) != page:
                continue
            bb = _bbox(block)
            if not bb:
                continue
            coord_w = self._cache.coord_size(page)[0]
            width = max(1.0, float(bb[2]) - float(bb[0]))
            if width < coord_w * 0.45:
                continue
            metrics = self.block_metrics(block)
            size = metrics.comparable_size if metrics else None
            if size is None:
                continue
            sizes.append(size)
            sources.append(metrics.source)
            if metrics.line_height is not None:
                line_heights.append(metrics.line_height)
        out: Optional[TextStyleMetrics]
        if sizes:
            source = "mixed"
            if sources and all(src == sources[0] for src in sources):
                source = sources[0]
            out = TextStyleMetrics(
                source=source,
                line_count=len(sizes),
                font_size=round(median(sizes), 3) if source == "pdf_text" else None,
                visual_size=round(median(sizes), 3) if source != "pdf_text" else None,
                line_height=round(median(line_heights), 3) if line_heights else None,
                confidence="medium",
            )
        else:
            out = None
        self._page_body_cache[page] = out
        return out

    def page_body_style_size(self, page: int, blocks: Sequence[Dict[str, Any]]) -> Optional[float]:
        metrics = self.page_body_metrics(page, blocks)
        return metrics.comparable_size if metrics else None

    def _text_layer_metrics(self, block: Dict[str, Any]) -> Optional[TextStyleMetrics]:
        if not self._cache.pdf_available:
            return None
        page = _block_page(block)
        bb = _bbox(block)
        if page is None or not bb:
            return None
        x0, y0, x1, y1 = self._cache.scale_bbox(page, bb)
        margin_y = max(2.0, (y1 - y0) * 0.08)
        margin_x = max(2.0, (x1 - x0) * 0.04)
        text_items = self._cache.page_text_items(page)
        sizes: List[float] = []
        line_heights: List[float] = []
        fonts: List[str] = []
        selected_lines = 0
        for line in text_items:
            lx0, ly0, lx1, ly1 = line["bbox"]
            cy = (ly0 + ly1) / 2.0
            overlap_x = max(0.0, min(x1 + margin_x, lx1) - max(x0 - margin_x, lx0))
            if not (y0 - margin_y <= cy <= y1 + margin_y and overlap_x > 1.0):
                continue
            selected_lines += 1
            line_heights.append(max(1.0, ly1 - ly0))
            for span in line["spans"]:
                txt = str(span.get("text", "")).strip()
                if not txt:
                    continue
                size = span.get("size")
                if isinstance(size, (int, float)) and size > 0:
                    sizes.append(float(size))
                font = span.get("font")
                if isinstance(font, str) and font and font not in fonts:
                    fonts.append(font)
        if not sizes and not line_heights:
            return None
        return TextStyleMetrics(
            source="pdf_text",
            line_count=selected_lines,
            font_size=round(median(sizes), 3) if sizes else None,
            line_height=round(median(line_heights), 3) if line_heights else None,
            fonts=tuple(fonts),
            confidence="high" if sizes else "medium",
        )

    def _image_metrics(self, block: Dict[str, Any]) -> Optional[TextStyleMetrics]:
        page = _block_page(block)
        bb = _bbox(block)
        image = self._cache.page_image(page) if page is not None else None
        if page is None or not bb or image is None:
            return None
        x0, y0, x1, y1 = self._cache.scale_bbox(page, bb)
        zoom = self._cache.render_zoom
        px0 = max(0, int((x0 - 2.0) * zoom))
        py0 = max(0, int((y0 - 2.0) * zoom))
        px1 = min(image.width, int((x1 + 2.0) * zoom))
        py1 = min(image.height, int((y1 + 2.0) * zoom))
        if px1 <= px0 or py1 <= py0:
            return None
        crop = image.crop((px0, py0, px1, py1))
        width, height = crop.size
        data = list(crop.getdata())
        threshold = 225
        row_counts = [
            sum(1 for val in data[y * width : (y + 1) * width] if val < threshold)
            for y in range(height)
        ]
        bands = line_bands(row_counts, max(2, int(width * 0.004)))
        line_heights: List[float] = []
        visual_sizes: List[float] = []
        for start, end in bands:
            band_height = (end - start) / zoom
            if band_height < 2.0:
                continue
            line_heights.append(band_height)
            active_rows = [row_counts[y] for y in range(start, end) if row_counts[y] > 0]
            if active_rows:
                visual_sizes.append(band_height)
        if not visual_sizes:
            return None
        return TextStyleMetrics(
            source="rendered_image",
            line_count=len(visual_sizes),
            visual_size=round(median(visual_sizes), 3),
            line_height=round(median(line_heights), 3) if line_heights else None,
            confidence="medium",
        )


def _raw_block_as_canonical(block: Any) -> Dict[str, Any]:
    return {
        "block_id": f"raw:{getattr(block, 'page', '')}:{getattr(block, 'index', '')}",
        "type": PARAGRAPH if getattr(block, "raw_type", None) == "paragraph" else str(getattr(block, "raw_type", "text")),
        "text": str(getattr(block, "text", "") or ""),
        "source": {"page": getattr(block, "page", None), "bbox": getattr(block, "bbox", None)},
    }


def _block_page(block: Dict[str, Any]) -> Optional[int]:
    page = (block.get("source") or {}).get("page")
    return int(page) if page is not None else None


def _bbox(block: Dict[str, Any]) -> Optional[BBox]:
    box = (block.get("source") or {}).get("bbox")
    if isinstance(box, list) and len(box) >= 4:
        return box
    return None
