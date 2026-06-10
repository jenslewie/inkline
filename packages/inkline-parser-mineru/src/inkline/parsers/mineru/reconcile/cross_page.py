"""Cross-page paragraph merging. Merges logical paragraphs split across page boundaries or interrupted by full-page floats. Uses PDF text-layer line metrics and rendered image analysis to detect continuation via first-line indent patterns. Contains _PdfLineExtractor and merge_cross_page_paragraphs()."""

from __future__ import annotations
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from ..analysis.layout import LayoutStats
from ..analysis.pdf_page_metrics import PdfPageCache, line_bands
from ..schema.models import BBox
from ..extraction.text import chinese_len, normalize_ws
from .constants import (
    FLOAT_LIKE_TYPES, MERGEABLE_TEXT_TYPES, QUOTE_TYPES, _DEFAULT_PAGE_HEIGHT,
    _NEAR_PAGE_BOTTOM_RATIO,
)
from .block_access import block_bbox as _bbox, block_page as _block_page, block_pages as _block_pages
from .block_merge import _join_text, _merge_block_pair
from .layout_helpers import (
    _canonical_quote_layout, _ends_with_terminal, _is_near_page_bottom,
    _is_near_page_top, _page_coord_heights, _page_coord_widths,
)
from .notes.keys import leading_note_marker as _leading_note_marker

FLOAT_INTERRUPTION_TYPES = FLOAT_LIKE_TYPES | {"table"}

_BODY_INDENT_MAX_PX = 48.0
_BODY_INDENT_RATIO = 0.055
_BODY_WIDTH_RATIO = 0.86
_BODY_INDENT_CHAR_RATIO = 0.65
_SHORT_LINE_MAX_HEIGHT = 30.0
_SHORT_LINE_HEIGHT_RATIO = 0.035
_SHORT_LINE_MAX_LEN = 90
_DEFAULT_CHAR_WIDTH = 10.0
_MIN_CHAR_WIDTH = 6.0
_MAX_CHAR_WIDTH = 18.0
_FOOTNOTE_GAP_MAX_PX = 95.0
_FOOTNOTE_GAP_RATIO = 0.095

def resolve_source_pdf_path(pdf_path: Optional[str], allow_missing: bool = False) -> Optional[str]:
    """Resolve --source-pdf robustly and fail loudly when requested PDF is unavailable."""
    if not pdf_path:
        return None
    raw = Path(pdf_path).expanduser()
    candidates: List[Path] = []
    candidates.append(raw)
    if not raw.is_absolute():
        candidates.append(Path.cwd() / raw)
        candidates.append(Path.cwd() / raw.name)
        candidates.append(Path('/mnt/data') / raw.name)
    # de-duplicate while preserving order
    seen = set()
    uniq: List[Path] = []
    for c in candidates:
        key = str(c)
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    for c in uniq:
        if c.exists() and c.is_file():
            return str(c.resolve())
    msg = (
        f"--source-pdf was provided but the PDF file could not be found: {pdf_path}\n"
        f"Tried: " + ", ".join(str(c) for c in uniq)
    )
    if allow_missing:
        print("WARNING: " + msg)
        return None
    raise FileNotFoundError(msg)

class _PdfLineExtractor:
    def __init__(
        self,
        pdf_path: Optional[str],
        page_widths: Dict[int, float],
        page_heights: Dict[int, float],
        allow_missing_pdf_text: bool = False,
    ) -> None:
        sizes: Dict[int, Tuple[float, float]] = {}
        for p in set(page_widths) | set(page_heights):
            sizes[p] = (page_widths.get(p, 1000.0), page_heights.get(p, 1000.0))
        self._cache = PdfPageCache(pdf_path, sizes, render_zoom=2.0, allow_missing=allow_missing_pdf_text)

    def close(self) -> None:
        self._cache.close()

    def page_lines(self, page: int) -> List[Tuple[Tuple[float, float, float, float], str]]:
        return self._cache.page_text_lines(page)

    def scale_bbox(self, page: int, bb: BBox) -> Tuple[float, float, float, float]:
        return self._cache.scale_bbox(page, bb)

    @staticmethod
    def _line_bands(row_counts: List[int], min_row_pixels: int) -> List[Tuple[int, int]]:
        return line_bands(row_counts, min_row_pixels)

    def _page_image(self, page: int) -> Optional[Any]:
        return self._cache.page_image(page)

    def line_metrics_for_block(self, b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = _block_page(b)
        bb = _bbox(b)
        if p is None or not bb:
            return None
        rect = self.scale_bbox(p, bb)
        x0, y0, x1, y1 = rect
        margin_y = max(3.0, (y1 - y0) * 0.04)
        margin_x = max(3.0, (x1 - x0) * 0.03)
        selected: List[Tuple[Tuple[float, float, float, float], str]] = []
        for lbb, txt in self.page_lines(p):
            lx0, ly0, lx1, ly1 = lbb
            cy = (ly0 + ly1) / 2
            overlap_x = max(0.0, min(x1 + margin_x, lx1) - max(x0 - margin_x, lx0))
            if y0 - margin_y <= cy <= y1 + margin_y and overlap_x > 1.0:
                selected.append((lbb, txt))
        if not selected:
            return self.image_line_metrics_for_block(b)
        selected.sort(key=lambda it: (it[0][1], it[0][0]))
        xs = [it[0][0] for it in selected]
        widths = [max(1.0, it[0][2] - it[0][0]) for it in selected]
        char_widths = []
        for (lbb, txt), w in zip(selected, widths):
            clen = max(1, chinese_len(txt))
            if clen >= 5:
                char_widths.append(w / clen)
        char_w = median(char_widths) if char_widths else 10.0
        body_x = median(xs[1:]) if len(xs) > 1 else xs[0]
        return {
            "line_count": len(selected),
            "first_line_x": round(xs[0], 3),
            "body_line_x": round(body_x, 3),
            "first_line_indent": round(xs[0] - body_x, 3),
            "char_width": round(char_w, 3),
            "line_texts": [txt for _, txt in selected[:3]],
        }

    def image_line_metrics_for_block(self, b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Estimate line starts from a rendered page image when PDF text is unavailable.

        Scanned PDFs often have no text layer, but paragraph continuation across
        page boundaries depends on visible first-line indentation. This fallback
        uses only layout pixels inside the block bbox.
        """
        p = _block_page(b)
        bb = _bbox(b)
        img = self._page_image(p) if p is not None else None
        if p is None or not bb or img is None:
            return None
        x0, y0, x1, y1 = self.scale_bbox(p, bb)
        zoom = self._cache.render_zoom
        pad_x = 3.0
        pad_y = 2.0
        px0 = max(0, int((x0 - pad_x) * zoom))
        py0 = max(0, int((y0 - pad_y) * zoom))
        px1 = min(img.width, int((x1 + pad_x) * zoom))
        py1 = min(img.height, int((y1 + pad_y) * zoom))
        if px1 <= px0 or py1 <= py0:
            return None
        crop = img.crop((px0, py0, px1, py1))
        w, h = crop.size
        if w <= 0 or h <= 0:
            return None
        data = list(crop.getdata())
        threshold = 225
        row_counts = [
            sum(1 for val in data[y * w : (y + 1) * w] if val < threshold)
            for y in range(h)
        ]
        min_row_pixels = max(3, int(w * 0.004))
        bands = self._line_bands(row_counts, min_row_pixels)
        line_boxes: List[Tuple[float, float, float, float]] = []
        min_col_pixels = 1
        for y_start, y_end in bands:
            xs: List[int] = []
            for x in range(w):
                count = 0
                for y in range(y_start, y_end):
                    if data[y * w + x] < threshold:
                        count += 1
                if count >= min_col_pixels:
                    xs.append(x)
            if not xs:
                continue
            lx0 = px0 / zoom + min(xs) / zoom
            lx1 = px0 / zoom + max(xs) / zoom
            ly0 = py0 / zoom + y_start / zoom
            ly1 = py0 / zoom + y_end / zoom
            if lx1 - lx0 >= 5.0:
                line_boxes.append((lx0, ly0, lx1, ly1))
        if not line_boxes:
            return None
        xs_pdf = [line[0] for line in line_boxes]
        widths = [max(1.0, line[2] - line[0]) for line in line_boxes]
        text_len = max(1, chinese_len(str(b.get("text", ""))))
        avg_chars_per_line = max(1.0, text_len / max(1, len(line_boxes)))
        char_w = median(widths) / avg_chars_per_line if widths else 10.0
        char_w = max(6.0, min(char_w, 18.0))
        body_x = median(xs_pdf[1:]) if len(xs_pdf) > 1 else xs_pdf[0]
        return {
            "line_count": len(line_boxes),
            "first_line_x": round(xs_pdf[0], 3),
            "body_line_x": round(body_x, 3),
            "first_line_indent": round(xs_pdf[0] - body_x, 3),
            "char_width": round(char_w, 3),
            "source": "page_image",
        }


def _next_same_page_text_block(blocks: List[Dict[str, Any]], start: int, page: int) -> Optional[Dict[str, Any]]:
    for k in range(start, len(blocks)):
        b = blocks[k]
        if _block_page(b) != page:
            if _block_page(b) and _block_page(b) > page:
                return None
            continue
        if b.get("type") in MERGEABLE_TEXT_TYPES:
            return b
        if b.get("type") in {"heading", "epigraph", "epigraph_group", "blockquote", "table"}:
            return None
    return None


def _is_cross_page_interruption(b: Dict[str, Any]) -> bool:
    if b.get("type") in FLOAT_INTERRUPTION_TYPES:
        return True
    # Page footnotes sit below the body text and should not prevent a body
    # paragraph from continuing onto the next page.
    return b.get("type") == "footnote"


def _starts_after_next_page_float(right: Dict[str, Any], interruptions: List[Dict[str, Any]], page_heights: Dict[int, float]) -> bool:
    rp = _block_page(right)
    rbb = _bbox(right)
    if rp is None or not rbb:
        return False
    float_boxes = [
        x.get("bbox")
        for x in interruptions
        if x.get("page") == rp and x.get("type") in FLOAT_INTERRUPTION_TYPES and isinstance(x.get("bbox"), list)
    ]
    if not float_boxes:
        return False
    top_y = min(float(bb[1]) for bb in float_boxes)
    bottom_y = max(float(bb[3]) for bb in float_boxes)
    h = page_heights.get(rp, _DEFAULT_PAGE_HEIGHT)
    return top_y <= h * 0.25 and bottom_y <= float(rbb[1]) <= bottom_y + h * 0.16


def _looks_like_body_resumption(block: Dict[str, Any], layout: LayoutStats) -> bool:
    bb = _bbox(block)
    if not bb:
        return False
    x0, _y0, x1, _y1 = [float(v) for v in bb]
    width = max(0.0, x1 - x0)
    near_body_left = x0 <= layout.body_left + max(_BODY_INDENT_MAX_PX, layout.body_width * _BODY_INDENT_RATIO)
    body_width = width >= layout.body_width * _BODY_WIDTH_RATIO
    return near_body_left and body_width


def _left_refs_interrupted_footnote(left: Dict[str, Any], interruptions: List[Dict[str, Any]]) -> bool:
    ref_markers = {
        str(ref.get("marker", "")).strip()
        for ref in (left.get("attrs") or {}).get("note_refs", [])
        if str(ref.get("marker", "")).strip()
    }
    if not ref_markers:
        return False
    for item in interruptions:
        if item.get("type") != "footnote":
            continue
        marker = item.get("_note_marker") or _leading_note_marker(str(item.get("text", "")))
        if marker and marker in ref_markers:
            return True
    return False


def _right_layout_says_unindented_continuation(evidence: Dict[str, Any]) -> bool:
    metrics = evidence.get("right_first_line_metrics")
    if not isinstance(metrics, dict):
        return False
    try:
        indent = abs(float(metrics.get("first_line_indent", 0.0)))
        char_w = max(_MIN_CHAR_WIDTH, float(metrics.get("char_width", _DEFAULT_CHAR_WIDTH)))
    except (TypeError, ValueError):
        return False
    return indent <= char_w * 0.75


def _is_short_page_bottom_line(b: Dict[str, Any], page_heights: Dict[int, float]) -> bool:
    bb = _bbox(b)
    p = _block_page(b)
    if p is None or not bb:
        return False
    h = page_heights.get(p, _DEFAULT_PAGE_HEIGHT)
    line_height = float(bb[3]) - float(bb[1])
    text = normalize_ws(str(b.get("text", "")))
    return float(bb[3]) >= h * 0.78 and line_height <= max(_SHORT_LINE_MAX_HEIGHT, h * _SHORT_LINE_HEIGHT_RATIO) and len(text) <= _SHORT_LINE_MAX_LEN


def _can_end_body_before_page_footnotes(blocks: List[Dict[str, Any]], idx: int, page_heights: Dict[int, float]) -> bool:
    left = blocks[idx]
    lp = _block_page(left)
    lbb = _bbox(left)
    if lp is None or not lbb:
        return False
    h = page_heights.get(lp, _DEFAULT_PAGE_HEIGHT)
    footnote_boxes: List[BBox] = []

    def _collect_spans_on_page(b: Dict[str, Any], target_page: int) -> None:
        for span in (b.get("source") or {}).get("spans") or []:
            if span.get("page") == target_page:
                bb = span.get("bbox")
                if bb:
                    footnote_boxes.append(bb)

    for k in range(idx + 1, len(blocks)):
        b = blocks[k]
        bp = _block_page(b)
        if bp != lp:
            break
        if b.get("type") == "footnote":
            b_pages = (b.get("source") or {}).get("pages") or []
            if len(b_pages) > 1 and lp in b_pages:
                _collect_spans_on_page(b, lp)
            else:
                bb = _bbox(b)
                if bb:
                    footnote_boxes.append(bb)
            continue
        return False

    # Also look backward for cross-page footnotes that were merged into an
    # earlier block but still have span content on this page (e.g. a footnote
    # that continued from the previous page via "（接下页）"/"（接上页）").
    for k in range(idx - 1, -1, -1):
        b = blocks[k]
        b_pages = (b.get("source") or {}).get("pages") or []
        if lp in b_pages and b.get("type") == "footnote":
            _collect_spans_on_page(b, lp)

    if not footnote_boxes:
        return False
    first_top = min(float(bb[1]) for bb in footnote_boxes)
    last_bottom = max(float(bb[3]) for bb in footnote_boxes)
    gap = first_top - float(lbb[3])
    return 0 <= gap <= max(_FOOTNOTE_GAP_MAX_PX, h * _FOOTNOTE_GAP_RATIO) and last_bottom >= h * _NEAR_PAGE_BOTTOM_RATIO


def _indent_says_continuation(right: Dict[str, Any], next_same_page: Optional[Dict[str, Any]], line_extractor: _PdfLineExtractor) -> Tuple[bool, Dict[str, Any]]:
    evidence: Dict[str, Any] = {}
    if next_same_page is None:
        return False, evidence
    rmet = line_extractor.line_metrics_for_block(right)
    nmet = line_extractor.line_metrics_for_block(next_same_page)
    if rmet:
        evidence["right_first_line_metrics"] = rmet
    if nmet:
        evidence["next_first_line_metrics"] = nmet
    if rmet and nmet:
        char_w = max(6.0, min(float(rmet.get("char_width", 10.0)), float(nmet.get("char_width", 10.0))))
        right_indent = abs(float(rmet.get("first_line_indent", 0.0)))
        next_indent = float(nmet.get("first_line_indent", 0.0))
        delta_first_x = float(nmet.get("first_line_x", 0.0)) - float(rmet.get("first_line_x", 0.0))
        evidence["indent_delta_chars"] = round(delta_first_x / char_w, 3) if char_w else None
        next_is_single_line = int(nmet.get("line_count", 0)) == 1
        ok = right_indent <= char_w * 0.65 and delta_first_x >= char_w * 1.15 and (next_indent >= char_w * 1.15 or next_is_single_line)
        return ok, evidence
    # Fallback when PDF text line extraction fails.
    rbb = _bbox(right)
    nbb = _bbox(next_same_page)
    if rbb and nbb:
        delta = float(nbb[0]) - float(rbb[0])
        evidence["fallback_bbox_x_delta"] = delta
        return delta >= 15.0, evidence
    return False, evidence


def _collect_interruptions(blocks: List[Dict[str, Any]], start: int, left_page: int) -> Tuple[int, List[Dict[str, Any]]]:
    j = start
    interruptions: List[Dict[str, Any]] = []
    while j < len(blocks) and _is_cross_page_interruption(blocks[j]):
        bp = _block_page(blocks[j])
        if bp is not None and bp < left_page:
            j += 1
            continue
        if bp is not None and bp >= left_page:
            interruptions.append({
                "page": bp,
                "bbox": _bbox(blocks[j]),
                "block_id": blocks[j].get("block_id"),
                "type": blocks[j].get("type"),
                "_note_marker": _leading_note_marker(str(blocks[j].get("text", ""))) if blocks[j].get("type") == "footnote" else None,
            })
            j += 1
            continue
        break
    return j, interruptions


def merge_cross_page_paragraphs(blocks: List[Dict[str, Any]], source_pdf: Optional[str], layout: Optional[LayoutStats] = None, allow_missing_pdf_text: bool = False) -> None:
    """Merge logical paragraphs split by page boundaries or full-page floats.

    This pass deliberately runs after page-local classification. It fixes cases
    like:
      - page bottom ends with “对” and next page begins “马岛时”
      - a full-page figure/map interrupts a paragraph
      - previous page ends with terminal punctuation, but next-page first block
        has no first-line indent while the next paragraph on that page does.
    """
    page_heights = _page_coord_heights(blocks)
    page_widths = _page_coord_widths(blocks)
    line_extractor = _PdfLineExtractor(source_pdf, page_widths, page_heights, allow_missing_pdf_text=allow_missing_pdf_text)
    try:
        i = 0
        while i < len(blocks):
            left = blocks[i]
            if left.get("type") not in MERGEABLE_TEXT_TYPES:
                i += 1
                continue
            if (left.get("attrs") or {}).get("list_type") == "reference_list":
                i += 1
                continue
            lp_list = _block_pages(left)
            if not lp_list:
                i += 1
                continue
            left_page = max(lp_list)
            if not _is_near_page_bottom(left, page_heights) and not _can_end_body_before_page_footnotes(blocks, i, page_heights):
                i += 1
                continue
            j, interruptions = _collect_interruptions(blocks, i + 1, left_page)
            if j >= len(blocks):
                i += 1
                continue
            right = blocks[j]
            if right.get("type") not in MERGEABLE_TEXT_TYPES:
                i += 1
                continue
            if (right.get("attrs") or {}).get("list_type") == "reference_list":
                i += 1
                continue
            # Do not let paragraph-continuation merging cross a set-off display
            # boundary.  A prose introducer at a page bottom followed by a
            # quote on the next page must remain separate; a quote followed by
            # normal narrative must also remain separate. True cross-page quote
            # continuations are handled by quote reconciliation when the next
            # fragment has quote layout.
            if left.get("type") == "paragraph" and right.get("type") in QUOTE_TYPES:
                i += 1
                continue
            if left.get("type") in QUOTE_TYPES and right.get("type") == "paragraph":
                if layout is not None and not _canonical_quote_layout(right, layout):
                    i += 1
                    continue
            display_like = (left.get("type") == "display_block") or (left.get("type") in QUOTE_TYPES)
            if display_like and right.get("type") == "paragraph":
                if layout is not None and not _canonical_quote_layout(right, layout):
                    i += 1
                    continue
            rp = _block_page(right)
            if rp is None or rp <= left_page:
                i += 1
                continue
            # Usually next page; allow +2/+3 only when skipped blocks are full-page floats.
            if rp > left_page + 1 and not interruptions:
                i += 1
                continue
            starts_after_float = _starts_after_next_page_float(right, interruptions, page_heights)
            if not _is_near_page_top(right, page_heights) and not starts_after_float:
                i += 1
                continue
            if (
                display_like
                and right.get("type") == "paragraph"
                and layout is not None
                and starts_after_float
                and _looks_like_body_resumption(right, layout)
            ):
                i += 1
                continue

            left_terminal = _ends_with_terminal(left.get("text", ""))
            evidence: Dict[str, Any] = {"left_ends_with_terminal_punctuation": left_terminal}
            if starts_after_float:
                evidence["right_starts_after_next_page_float"] = True
            should_merge = not left_terminal
            reason = "cross_page_paragraph_continuation"
            if interruptions:
                reason = (
                    "cross_page_paragraph_continuation_across_footnote"
                    if all(x.get("type") == "footnote" for x in interruptions)
                    else "cross_page_paragraph_continuation_across_float"
                )
            if left_terminal:
                next_para = _next_same_page_text_block(blocks, j + 1, rp)
                indent_ok, indent_ev = _indent_says_continuation(right, next_para, line_extractor)
                evidence.update(indent_ev)
                if indent_ok:
                    should_merge = True
                    reason = "cross_page_paragraph_continuation_after_terminal_by_indent"
                    evidence["terminal_continuation_exception"] = "right_unindented_vs_next_paragraph_first_line_indent"
                elif starts_after_float and _is_short_page_bottom_line(left, page_heights):
                    should_merge = True
                    reason = "cross_page_paragraph_continuation_after_terminal_across_float"
                    evidence["terminal_continuation_exception"] = "short_page_bottom_line_before_next_page_float"
                elif (
                    not (right.get("attrs") or {}).get("note_refs")
                    and _right_layout_says_unindented_continuation(evidence)
                    and _left_refs_interrupted_footnote(
                        left, interruptions
                    )
                ):
                    should_merge = True
                    reason = "cross_page_paragraph_continuation_after_terminal_across_referenced_footnote"
                    evidence["terminal_continuation_exception"] = "left_note_ref_matches_interrupted_footnote"
            if not should_merge:
                i += 1
                continue
            stored_interruptions = [{k: v for k, v in item.items() if not k.startswith("_") and v is not None} for item in interruptions]
            _merge_block_pair(left, right, reason, evidence, stored_interruptions)
            # Remove right block. Keep any skipped float blocks in document order.
            del blocks[j]
            # Try merging the enlarged left with a further continuation.
        
    finally:
        line_extractor.close()
