"""Cached PDF page text-layer and rendered-image access. Wraps PyMuPDF document lifecycle, provides cached text-layer extraction (PyMuPDF spans), cached rendered page images (PIL grayscale), bbox scaling, and shared line-band detection utilities. Used by TextStyleAnalyzer and cross-page paragraph merging."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..schema.models import BBox
from .page_geometry import PageGeometry


class PdfPageCache:
    """Cached PDF page text-layer and rendered-image access.

    Wraps PyMuPDF document lifecycle, provides cached text-layer extraction
    (with spans), cached rendered page images (PIL grayscale), and bbox
    scaling between MinerU coordinate space and PDF-point space.
    """

    def __init__(
        self,
        pdf_path: Optional[str],
        page_coord_sizes: Optional[Dict[int, Tuple[float, float]]] = None,
        *,
        render_zoom: float = 2.0,
        allow_missing: bool = False,
    ) -> None:
        self.pdf_path = str(pdf_path) if pdf_path else None
        self.render_zoom = render_zoom
        page_sizes = page_coord_sizes or {}
        self._geometry = PageGeometry(
            coord_widths={p: w for p, (w, h) in page_sizes.items()},
            coord_heights={p: h for p, (w, h) in page_sizes.items()},
        )
        self._doc: Any = None
        self._text_cache: Dict[int, List[Dict[str, Any]]] = {}
        self._image_cache: Dict[int, Any] = {}
        if pdf_path and Path(pdf_path).exists():
            try:
                import fitz  # type: ignore

                self._doc = fitz.open(pdf_path)
            except Exception as exc:
                if allow_missing:
                    print(f"WARNING: Could not open PDF: {pdf_path}: {exc}")
                else:
                    raise RuntimeError(
                        f"Could not open PDF: {pdf_path}. "
                        "Install PyMuPDF or pass allow_missing=True to use lower-quality fallbacks."
                    ) from exc

    @property
    def pdf_available(self) -> bool:
        return self._doc is not None

    def close(self) -> None:
        try:
            if self._doc is not None:
                self._doc.close()
        except Exception:
            pass

    def page_rect(self, page: int) -> Optional[Any]:
        if self._doc is None or page < 1 or page > len(self._doc):
            return None
        return self._doc[page - 1].rect

    def coord_size(
        self, page: int, default: Tuple[float, float] = (1000.0, 1000.0)
    ) -> Tuple[float, float]:
        return (
            self._geometry.coord_widths.get(page, default[0]),
            self._geometry.coord_heights.get(page, default[1]),
        )

    def scale_bbox(self, page: int, bb: BBox) -> Tuple[float, float, float, float]:
        rect = self.page_rect(page)
        if rect is None:
            return tuple(float(x) for x in bb)  # type: ignore[return-value]
        return self._geometry.scale_bbox(page, bb, rect)

    def page_text_items(self, page: int) -> List[Dict[str, Any]]:
        """Cached text-layer lines with bbox and PyMuPDF spans."""
        if page in self._text_cache:
            return self._text_cache[page]
        items: List[Dict[str, Any]] = []
        if self._doc is None or page < 1 or page > len(self._doc):
            self._text_cache[page] = items
            return items
        try:
            data = self._doc[page - 1].get_text("dict")
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    bbox = tuple(float(x) for x in line.get("bbox", [0, 0, 0, 0]))
                    items.append({"bbox": bbox, "spans": list(line.get("spans", []))})
            items.sort(key=lambda it: (it["bbox"][1], it["bbox"][0]))
        except Exception:
            pass
        self._text_cache[page] = items
        return items

    def page_text_lines(self, page: int) -> List[Tuple[Tuple[float, float, float, float], str]]:
        """Cached text-layer lines as (bbox, concatenated_text) tuples."""
        lines: List[Tuple[Tuple[float, float, float, float], str]] = []
        for item in self.page_text_items(page):
            txt = "".join(str(s.get("text", "")) for s in item.get("spans", [])).strip()
            if not txt:
                continue
            lines.append((item["bbox"], txt))
        return lines

    def page_image(self, page: int) -> Optional[Any]:
        if page in self._image_cache:
            return self._image_cache[page]
        if self._doc is None or page < 1 or page > len(self._doc):
            self._image_cache[page] = None
            return None
        try:
            import fitz  # type: ignore
            from PIL import Image  # type: ignore

            pix = self._doc[page - 1].get_pixmap(
                matrix=fitz.Matrix(self.render_zoom, self.render_zoom),
                alpha=False,
            )
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        except Exception:
            image = None
        self._image_cache[page] = image
        return image


def line_bands(row_counts: List[int], min_row_pixels: int) -> List[Tuple[int, int]]:
    bands: List[Tuple[int, int]] = []
    start: Optional[int] = None
    last = -1
    max_gap = 3
    for y, count in enumerate(row_counts):
        if count >= min_row_pixels:
            if start is None:
                start = y
            elif y - last > max_gap:
                if last - start >= 2:
                    bands.append((start, last + 1))
                start = y
            last = y
    if start is not None and last - start >= 2:
        bands.append((start, last + 1))
    return bands
