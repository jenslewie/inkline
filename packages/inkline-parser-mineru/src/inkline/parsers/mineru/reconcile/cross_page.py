"""Cross-page paragraph merging. Merges logical paragraphs split across page boundaries or interrupted by full-page floats. Uses PDF text-layer line metrics and rendered image analysis to detect continuation via first-line indent patterns. Contains _PdfLineExtractor and merge_cross_page_paragraphs()."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from ..analysis.layout import LayoutStats
from ..analysis.pdf_page_metrics import PdfPageCache, line_bands
from ..extraction.text import chinese_len, normalize_ws, strip_trailing_text_note
from ..schema.block_types import DISPLAY_BLOCK, FOOTNOTE, HEADING, PARAGRAPH, TABLE
from ..schema.models import BBox
from .block_access import block_bbox as _bbox
from .block_access import block_page as _block_page
from .block_access import block_pages as _block_pages
from .block_merge import _merge_block_pair
from .constants import (
    _DEFAULT_PAGE_HEIGHT,
    _NEAR_PAGE_BOTTOM_RATIO,
    FLOAT_LIKE_TYPES,
    MERGEABLE_TEXT_TYPES,
    TERMINAL_PUNCT,
)
from .layout_helpers import (
    _display_block_layout,
    _is_near_page_bottom,
    _is_near_page_top,
    _page_coord_heights,
    _page_coord_widths,
    _scaled_body_metrics,
)
from .notes.keys import leading_note_marker as _leading_note_marker
from .notes.marker_inline import _note_refs

FLOAT_INTERRUPTION_TYPES = FLOAT_LIKE_TYPES | {TABLE}
FLOW_STOP_TYPES = {HEADING, DISPLAY_BLOCK, TABLE}

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


@dataclass(frozen=True)
class _CrossPageContext:
    layout: Optional[LayoutStats]
    page_heights: Dict[int, float]
    page_widths: Dict[int, float]
    line_extractor: "_PdfLineExtractor"


@dataclass(frozen=True)
class _CrossPageCandidate:
    left: Dict[str, Any]
    right: Dict[str, Any]
    left_page: int
    right_page: int
    right_idx: int
    interruptions: List[Dict[str, Any]]
    starts_after_float: bool
    display_like: bool


@dataclass(frozen=True)
class _MergeDecision:
    should_merge: bool
    reason: str
    evidence: Dict[str, Any]


def _ends_with_terminal(text: str) -> bool:
    t = normalize_ws(text or "")
    t, _ = strip_trailing_text_note(t)
    t = t.rstrip()
    return bool(t and t[-1] in TERMINAL_PUNCT)


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
        candidates.append(Path("/mnt/data") / raw.name)
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
        self._cache = PdfPageCache(
            pdf_path, sizes, render_zoom=2.0, allow_missing=allow_missing_pdf_text
        )

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
        selected = self._selected_text_lines(p, self.scale_bbox(p, bb))
        if not selected:
            return self.image_line_metrics_for_block(b)
        selected.sort(key=lambda it: (it[0][1], it[0][0]))
        xs = [it[0][0] for it in selected]
        body_x = median(xs[1:]) if len(xs) > 1 else xs[0]
        char_w = _median_text_line_char_width(selected)
        return {
            "line_count": len(selected),
            "first_line_x": round(xs[0], 3),
            "body_line_x": round(body_x, 3),
            "first_line_indent": round(xs[0] - body_x, 3),
            "char_width": round(char_w, 3),
            "line_texts": [txt for _, txt in selected[:3]],
        }

    def _selected_text_lines(
        self, page: int, rect: Tuple[float, float, float, float]
    ) -> List[Tuple[Tuple[float, float, float, float], str]]:
        x0, y0, x1, y1 = rect
        margin_y, margin_x = _line_selection_margins(rect)
        selected: List[Tuple[Tuple[float, float, float, float], str]] = []
        for lbb, txt in self.page_lines(page):
            lx0, ly0, lx1, ly1 = lbb
            cy = (ly0 + ly1) / 2
            overlap_x = max(0.0, min(x1 + margin_x, lx1) - max(x0 - margin_x, lx0))
            if y0 - margin_y <= cy <= y1 + margin_y and overlap_x > 1.0:
                selected.append((lbb, txt))
        return selected

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
        line_boxes = _block_image_line_boxes(
            img,
            self.scale_bbox(p, bb),
            self._cache.render_zoom,
            self._line_bands,
        )
        if not line_boxes:
            return None
        xs_pdf = [line[0] for line in line_boxes]
        widths = [max(1.0, line[2] - line[0]) for line in line_boxes]
        char_w = _estimated_image_char_width(widths, len(line_boxes), str(b.get("text", "")))
        body_x = median(xs_pdf[1:]) if len(xs_pdf) > 1 else xs_pdf[0]
        return {
            "line_count": len(line_boxes),
            "first_line_x": round(xs_pdf[0], 3),
            "body_line_x": round(body_x, 3),
            "first_line_indent": round(xs_pdf[0] - body_x, 3),
            "char_width": round(char_w, 3),
            "source": "page_image",
        }


def _line_selection_margins(rect: Tuple[float, float, float, float]) -> Tuple[float, float]:
    x0, y0, x1, y1 = rect
    return max(3.0, (y1 - y0) * 0.04), max(3.0, (x1 - x0) * 0.03)


def _median_text_line_char_width(
    lines: List[Tuple[Tuple[float, float, float, float], str]],
) -> float:
    char_widths = []
    for lbb, txt in lines:
        width = max(1.0, lbb[2] - lbb[0])
        clen = max(1, chinese_len(txt))
        if clen >= 5:
            char_widths.append(width / clen)
    return median(char_widths) if char_widths else _DEFAULT_CHAR_WIDTH


def _image_crop_rect(
    img: Any, rect: Tuple[float, float, float, float], zoom: float
) -> Tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    pad_x = 3.0
    pad_y = 2.0
    return (
        max(0, int((x0 - pad_x) * zoom)),
        max(0, int((y0 - pad_y) * zoom)),
        min(img.width, int((x1 + pad_x) * zoom)),
        min(img.height, int((y1 + pad_y) * zoom)),
    )


def _block_image_line_boxes(
    img: Any,
    block_rect: Tuple[float, float, float, float],
    zoom: float,
    band_extractor: Any,
) -> List[Tuple[float, float, float, float]]:
    rect = _image_crop_rect(img, block_rect, zoom)
    px0, py0, px1, py1 = rect
    if px1 <= px0 or py1 <= py0:
        return []
    crop = img.crop((px0, py0, px1, py1))
    width, height = crop.size
    if width <= 0 or height <= 0:
        return []
    data = list(crop.getdata())
    bands = band_extractor(_dark_row_counts(data, width, height), max(3, int(width * 0.004)))
    return _image_line_boxes(data, width, rect, zoom, bands)


def _dark_row_counts(data: List[int], width: int, height: int, threshold: int = 225) -> List[int]:
    return [
        sum(1 for val in data[y * width : (y + 1) * width] if val < threshold)
        for y in range(height)
    ]


def _image_line_boxes(
    data: List[int],
    width: int,
    rect: Tuple[int, int, int, int],
    zoom: float,
    bands: List[Tuple[int, int]],
) -> List[Tuple[float, float, float, float]]:
    px0, py0, _px1, _py1 = rect
    line_boxes: List[Tuple[float, float, float, float]] = []
    for y_start, y_end in bands:
        xs = _dark_columns_for_band(data, width, y_start, y_end)
        if not xs:
            continue
        lx0 = px0 / zoom + min(xs) / zoom
        lx1 = px0 / zoom + max(xs) / zoom
        ly0 = py0 / zoom + y_start / zoom
        ly1 = py0 / zoom + y_end / zoom
        if lx1 - lx0 >= 5.0:
            line_boxes.append((lx0, ly0, lx1, ly1))
    return line_boxes


def _dark_columns_for_band(
    data: List[int], width: int, y_start: int, y_end: int, threshold: int = 225
) -> List[int]:
    xs: List[int] = []
    for x in range(width):
        count = 0
        for y in range(y_start, y_end):
            if data[y * width + x] < threshold:
                count += 1
        if count >= 1:
            xs.append(x)
    return xs


def _estimated_image_char_width(widths: List[float], line_count: int, text: str) -> float:
    text_len = max(1, chinese_len(text))
    avg_chars_per_line = max(1.0, text_len / max(1, line_count))
    char_w = median(widths) / avg_chars_per_line if widths else _DEFAULT_CHAR_WIDTH
    return max(_MIN_CHAR_WIDTH, min(char_w, _MAX_CHAR_WIDTH))


def _next_same_page_text_block(
    blocks: List[Dict[str, Any]], start: int, page: int
) -> Optional[Dict[str, Any]]:
    for k in range(start, len(blocks)):
        b = blocks[k]
        if _block_page(b) != page:
            if _block_page(b) and _block_page(b) > page:
                return None
            continue
        if b.get("type") in MERGEABLE_TEXT_TYPES:
            return b
        if b.get("type") in FLOW_STOP_TYPES:
            return None
    return None


def _is_cross_page_interruption(b: Dict[str, Any]) -> bool:
    if b.get("type") in FLOAT_INTERRUPTION_TYPES:
        return True
    # Page footnotes sit below the body text and should not prevent a body
    # paragraph from continuing onto the next page.
    return b.get("type") == FOOTNOTE


def _starts_after_next_page_float(
    right: Dict[str, Any], interruptions: List[Dict[str, Any]], page_heights: Dict[int, float]
) -> bool:
    rp = _block_page(right)
    rbb = _bbox(right)
    if rp is None or not rbb:
        return False
    float_boxes = [
        x.get("bbox")
        for x in interruptions
        if x.get("page") == rp
        and x.get("type") in FLOAT_INTERRUPTION_TYPES
        and isinstance(x.get("bbox"), list)
    ]
    if not float_boxes:
        return False
    top_y = min(float(bb[1]) for bb in float_boxes)
    bottom_y = max(float(bb[3]) for bb in float_boxes)
    h = page_heights.get(rp, _DEFAULT_PAGE_HEIGHT)
    return top_y <= h * 0.25 and bottom_y <= float(rbb[1]) <= bottom_y + h * 0.16


def _looks_like_body_resumption(
    block: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    bb = _bbox(block)
    if not bb:
        return False
    x0, _y0, x1, _y1 = [float(v) for v in bb]
    width = max(0.0, x1 - x0)
    page = _block_page(block)
    coord_width = page_widths.get(page) if page is not None and page_widths else None
    body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    near_body_left = x0 <= body_left + max(_BODY_INDENT_MAX_PX, body_width * _BODY_INDENT_RATIO)
    has_body_width = width >= body_width * _BODY_WIDTH_RATIO
    return near_body_left and has_body_width


def _left_refs_interrupted_footnote(
    left: Dict[str, Any], interruptions: List[Dict[str, Any]]
) -> bool:
    ref_markers = {
        str(ref.get("marker", "")).strip()
        for ref in _note_refs(left)
        if str(ref.get("marker", "")).strip()
    }
    if not ref_markers:
        return False
    for item in interruptions:
        if item.get("type") != FOOTNOTE:
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
    return (
        float(bb[3]) >= h * 0.78
        and line_height <= max(_SHORT_LINE_MAX_HEIGHT, h * _SHORT_LINE_HEIGHT_RATIO)
        and len(text) <= _SHORT_LINE_MAX_LEN
    )


def _can_end_body_before_page_footnotes(
    blocks: List[Dict[str, Any]], idx: int, page_heights: Dict[int, float]
) -> bool:
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
        if b.get("type") == FOOTNOTE:
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
        if lp in b_pages and b.get("type") == FOOTNOTE:
            _collect_spans_on_page(b, lp)

    if not footnote_boxes:
        return False
    first_top = min(float(bb[1]) for bb in footnote_boxes)
    last_bottom = max(float(bb[3]) for bb in footnote_boxes)
    gap = first_top - float(lbb[3])
    return (
        0 <= gap <= max(_FOOTNOTE_GAP_MAX_PX, h * _FOOTNOTE_GAP_RATIO)
        and last_bottom >= h * _NEAR_PAGE_BOTTOM_RATIO
    )


def _indent_says_continuation(
    right: Dict[str, Any],
    next_same_page: Optional[Dict[str, Any]],
    line_extractor: _PdfLineExtractor,
) -> Tuple[bool, Dict[str, Any]]:
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
        char_w = max(
            6.0, min(float(rmet.get("char_width", 10.0)), float(nmet.get("char_width", 10.0)))
        )
        right_indent = abs(float(rmet.get("first_line_indent", 0.0)))
        next_indent = float(nmet.get("first_line_indent", 0.0))
        delta_first_x = float(nmet.get("first_line_x", 0.0)) - float(rmet.get("first_line_x", 0.0))
        evidence["indent_delta_chars"] = round(delta_first_x / char_w, 3) if char_w else None
        next_is_single_line = int(nmet.get("line_count", 0)) == 1
        ok = (
            right_indent <= char_w * 0.65
            and delta_first_x >= char_w * 1.15
            and (next_indent >= char_w * 1.15 or next_is_single_line)
        )
        return ok, evidence
    # Fallback when PDF text line extraction fails.
    rbb = _bbox(right)
    nbb = _bbox(next_same_page)
    if rbb and nbb:
        delta = float(nbb[0]) - float(rbb[0])
        evidence["fallback_bbox_x_delta"] = delta
        return delta >= 15.0, evidence
    return False, evidence


def _collect_interruptions(
    blocks: List[Dict[str, Any]], start: int, left_page: int
) -> Tuple[int, List[Dict[str, Any]]]:
    j = start
    interruptions: List[Dict[str, Any]] = []
    while j < len(blocks) and _is_cross_page_interruption(blocks[j]):
        bp = _block_page(blocks[j])
        if bp is not None and bp < left_page:
            j += 1
            continue
        if bp is not None and bp >= left_page:
            interruptions.append(
                {
                    "page": bp,
                    "bbox": _bbox(blocks[j]),
                    "block_id": blocks[j].get("block_id"),
                    "type": blocks[j].get("type"),
                    "_note_marker": _leading_note_marker(str(blocks[j].get("text", "")))
                    if blocks[j].get("type") == FOOTNOTE
                    else None,
                }
            )
            j += 1
            continue
        break
    return j, interruptions


def _cross_page_context(
    blocks: List[Dict[str, Any]],
    source_pdf: Optional[str],
    layout: Optional[LayoutStats],
    allow_missing_pdf_text: bool,
) -> _CrossPageContext:
    page_heights = _page_coord_heights(blocks)
    page_widths = _page_coord_widths(blocks)
    line_extractor = _PdfLineExtractor(
        source_pdf, page_widths, page_heights, allow_missing_pdf_text=allow_missing_pdf_text
    )
    return _CrossPageContext(layout, page_heights, page_widths, line_extractor)


def _is_reference_list(block: Dict[str, Any]) -> bool:
    return (block.get("attrs") or {}).get("list_type") == "reference_list"


def _is_mergeable_cross_page_text(block: Dict[str, Any]) -> bool:
    return block.get("type") in MERGEABLE_TEXT_TYPES and not _is_reference_list(block)


def _cross_page_candidate_at(
    blocks: List[Dict[str, Any]], idx: int, context: _CrossPageContext
) -> Optional[_CrossPageCandidate]:
    left = blocks[idx]
    if not _is_mergeable_cross_page_text(left):
        return None
    left_page = _candidate_left_page(left)
    if left_page is None:
        return None
    if not _candidate_left_can_continue(blocks, idx, left, left_page, context.page_heights):
        return None
    right_idx, interruptions = _collect_interruptions(blocks, idx + 1, left_page)
    if right_idx >= len(blocks):
        return None
    right = blocks[right_idx]
    if not _valid_cross_page_right(left, right, left_page, interruptions):
        return None
    right_page = _block_page(right)
    if right_page is None:
        return None
    starts_after_float = _starts_after_next_page_float(
        right, interruptions, context.page_heights
    )
    if not _is_near_page_top(right, context.page_heights) and not starts_after_float:
        return None
    return _CrossPageCandidate(
        left=left,
        right=right,
        left_page=left_page,
        right_page=right_page,
        right_idx=right_idx,
        interruptions=interruptions,
        starts_after_float=starts_after_float,
        display_like=left.get("type") == DISPLAY_BLOCK,
    )


def _candidate_left_page(left: Dict[str, Any]) -> Optional[int]:
    pages = _block_pages(left)
    return max(pages) if pages else None


def _candidate_left_can_continue(
    blocks: List[Dict[str, Any]],
    idx: int,
    left: Dict[str, Any],
    left_page: int,
    page_heights: Dict[int, float],
) -> bool:
    del left_page
    return _is_near_page_bottom(left, page_heights) or _can_end_body_before_page_footnotes(
        blocks, idx, page_heights
    )


def _valid_cross_page_right(
    left: Dict[str, Any],
    right: Dict[str, Any],
    left_page: int,
    interruptions: List[Dict[str, Any]],
) -> bool:
    if not _is_mergeable_cross_page_text(right):
        return False
    if left.get("type") == PARAGRAPH and right.get("type") == DISPLAY_BLOCK:
        return False
    right_page = _block_page(right)
    if right_page is None or right_page <= left_page:
        return False
    return right_page <= left_page + 1 or bool(interruptions)


def _display_gate_blocks_merge(
    candidate: _CrossPageCandidate, context: _CrossPageContext
) -> bool:
    if not candidate.display_like or candidate.right.get("type") != PARAGRAPH:
        return False
    if context.layout is None:
        return False
    right_page = _block_page(candidate.right)
    return not _display_block_layout(
        candidate.right, context.layout, context.page_widths.get(right_page)
    )


def _mark_set_off_display_boundary(left: Dict[str, Any]) -> None:
    attrs = left.setdefault("attrs", {})
    attrs["display_boundary_after_float_body_resume"] = True
    evidence = attrs.setdefault("classification_evidence", [])
    if "set_off_display_before_float_body_resume" not in evidence:
        evidence.append("set_off_display_before_float_body_resume")


def _cross_page_merge_decision(
    blocks: List[Dict[str, Any]],
    candidate: _CrossPageCandidate,
    context: _CrossPageContext,
) -> _MergeDecision:
    left_terminal = _ends_with_terminal(candidate.left.get("text", ""))
    evidence: Dict[str, Any] = {"left_ends_with_terminal_punctuation": left_terminal}
    if candidate.starts_after_float:
        evidence["right_starts_after_next_page_float"] = True
    reason = _base_cross_page_merge_reason(candidate.interruptions)
    if not left_terminal:
        return _MergeDecision(True, reason, evidence)
    return _terminal_merge_decision(blocks, candidate, context, evidence)


def _base_cross_page_merge_reason(interruptions: List[Dict[str, Any]]) -> str:
    if not interruptions:
        return "cross_page_paragraph_continuation"
    if all(x.get("type") == FOOTNOTE for x in interruptions):
        return "cross_page_paragraph_continuation_across_footnote"
    return "cross_page_paragraph_continuation_across_float"


def _terminal_merge_decision(
    blocks: List[Dict[str, Any]],
    candidate: _CrossPageCandidate,
    context: _CrossPageContext,
    evidence: Dict[str, Any],
) -> _MergeDecision:
    next_para = _next_same_page_text_block(
        blocks, candidate.right_idx + 1, candidate.right_page
    )
    indent_ok, indent_ev = _indent_says_continuation(
        candidate.right, next_para, context.line_extractor
    )
    evidence.update(indent_ev)
    if indent_ok:
        evidence["terminal_continuation_exception"] = (
            "right_unindented_vs_next_paragraph_first_line_indent"
        )
        return _MergeDecision(
            True, "cross_page_paragraph_continuation_after_terminal_by_indent", evidence
        )
    if candidate.starts_after_float and _is_short_page_bottom_line(
        candidate.left, context.page_heights
    ):
        evidence["terminal_continuation_exception"] = (
            "short_page_bottom_line_before_next_page_float"
        )
        return _MergeDecision(
            True, "cross_page_paragraph_continuation_after_terminal_across_float", evidence
        )
    if _terminal_footnote_interruption_allows_merge(candidate, evidence):
        evidence["terminal_continuation_exception"] = (
            "left_note_ref_matches_interrupted_footnote"
        )
        return _MergeDecision(
            True,
            "cross_page_paragraph_continuation_after_terminal_across_referenced_footnote",
            evidence,
        )
    return _MergeDecision(False, "", evidence)


def _terminal_footnote_interruption_allows_merge(
    candidate: _CrossPageCandidate, evidence: Dict[str, Any]
) -> bool:
    return (
        not _note_refs(candidate.right)
        and _right_layout_says_unindented_continuation(evidence)
        and _left_refs_interrupted_footnote(candidate.left, candidate.interruptions)
    )


def _stored_interruptions(interruptions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        for item in interruptions
    ]


def _merge_cross_page_candidate(
    blocks: List[Dict[str, Any]],
    candidate: _CrossPageCandidate,
    decision: _MergeDecision,
) -> None:
    _merge_block_pair(
        candidate.left,
        candidate.right,
        decision.reason,
        decision.evidence,
        _stored_interruptions(candidate.interruptions),
    )
    # Remove right block. Keep any skipped float blocks in document order.
    del blocks[candidate.right_idx]


def merge_cross_page_paragraphs(
    blocks: List[Dict[str, Any]],
    source_pdf: Optional[str],
    layout: Optional[LayoutStats] = None,
    allow_missing_pdf_text: bool = False,
) -> None:
    """Merge logical paragraphs split by page boundaries or full-page floats.

    This pass deliberately runs after page-local classification. It fixes cases
    like:
      - page bottom ends with “对” and next page begins “马岛时”
      - a full-page figure/map interrupts a paragraph
      - previous page ends with terminal punctuation, but next-page first block
        has no first-line indent while the next paragraph on that page does.
    """
    context = _cross_page_context(blocks, source_pdf, layout, allow_missing_pdf_text)
    try:
        i = 0
        while i < len(blocks):
            candidate = _cross_page_candidate_at(blocks, i, context)
            if candidate is None:
                i += 1
                continue
            if _set_off_display_before_float_body_resume(
                blocks,
                i,
                candidate.left,
                candidate.right,
                candidate.interruptions,
                candidate.starts_after_float,
                context.layout,
                context.page_widths,
                context.page_heights,
            ):
                _mark_set_off_display_boundary(candidate.left)
                i += 1
                continue
            if _display_gate_blocks_merge(candidate, context):
                i += 1
                continue
            decision = _cross_page_merge_decision(blocks, candidate, context)
            if not decision.should_merge:
                i += 1
                continue
            _merge_cross_page_candidate(blocks, candidate, decision)
            # Try merging the enlarged left with a further continuation.

    finally:
        context.line_extractor.close()


def _set_off_display_before_float_body_resume(
    blocks: List[Dict[str, Any]],
    idx: int,
    left: Dict[str, Any],
    right: Dict[str, Any],
    interruptions: List[Dict[str, Any]],
    starts_after_float: bool,
    layout: Optional[LayoutStats],
    page_widths: Dict[int, float],
    page_heights: Dict[int, float],
) -> bool:
    if layout is None or not starts_after_float:
        return False
    if left.get("type") not in {PARAGRAPH, DISPLAY_BLOCK} or right.get("type") != PARAGRAPH:
        return False
    if not any(item.get("type") in FLOAT_INTERRUPTION_TYPES for item in interruptions):
        return False
    if _has_tight_body_flow_from_previous_body(blocks, idx, layout, page_widths, page_heights):
        return False
    page_local_set_off = _is_set_off_from_previous_body(blocks, idx, layout, page_widths)
    if (
        not _display_block_layout(left, layout, page_widths.get(_block_page(left)))
        and not page_local_set_off
    ):
        return False
    if not page_local_set_off and _looks_like_body_resumption(left, layout, page_widths):
        return False
    if not _looks_like_body_resumption(right, layout, page_widths):
        return False
    return page_local_set_off or not _looks_like_strict_body_lane(left, layout, page_widths)


def _has_tight_body_flow_from_previous_body(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float],
    page_heights: Dict[int, float],
) -> bool:
    block = blocks[idx]
    bb = _bbox(block)
    page = _block_page(block)
    if page is None or not bb:
        return False
    prev = _previous_same_page_non_footnote(blocks, idx, page)
    if prev is None or prev.get("type") != PARAGRAPH:
        return False
    if not _looks_like_body_resumption(prev, layout, page_widths):
        return False
    pbb = _bbox(prev)
    if not pbb:
        return False
    return _tight_body_flow_geometry_matches(
        bb,
        pbb,
        _body_width_for_page(layout, page_widths, page),
        page_heights.get(page, _DEFAULT_PAGE_HEIGHT),
    )


def _is_set_off_from_previous_body(
    blocks: List[Dict[str, Any]],
    idx: int,
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    block = blocks[idx]
    bb = _bbox(block)
    page = _block_page(block)
    if page is None or not bb:
        return False
    prev = _previous_same_page_non_footnote(blocks, idx, page)
    if prev is None or not _looks_like_body_resumption(prev, layout, page_widths):
        return False
    pbb = _bbox(prev)
    if not pbb:
        return False
    return _set_off_geometry_matches(bb, pbb, _body_width_for_page(layout, page_widths, page))


def _previous_same_page_non_footnote(
    blocks: List[Dict[str, Any]], idx: int, page: int
) -> Optional[Dict[str, Any]]:
    for candidate in reversed(blocks[:idx]):
        candidate_page = _block_page(candidate)
        if candidate_page != page:
            break
        if candidate.get("type") != FOOTNOTE:
            return candidate
    return None


def _body_width_for_page(
    layout: LayoutStats, page_widths: Dict[int, float] | None, page: int
) -> float:
    coord_width = page_widths.get(page) if page_widths else None
    _body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    return body_width


def _tight_body_flow_geometry_matches(
    bb: BBox, previous_bb: BBox, body_width: float, page_height: float
) -> bool:
    x0, y0, x1, _y1 = [float(v) for v in bb]
    px0, _py0, _px1, py1 = [float(v) for v in previous_bb]
    vertical_gap = y0 - py1
    if not (0 <= vertical_gap <= max(18.0, page_height * 0.018)):
        return False
    indent = x0 - px0
    first_line_indent = max(34.0, body_width * 0.045) <= indent <= max(82.0, body_width * 0.11)
    near_body_width = max(0.0, x1 - x0) >= body_width * 0.70
    return first_line_indent and near_body_width


def _set_off_geometry_matches(bb: BBox, previous_bb: BBox, body_width: float) -> bool:
    x0, _y0, x1, _y1 = [float(v) for v in bb]
    px0, _py0, px1, _py1 = [float(v) for v in previous_bb]
    width = max(0.0, x1 - x0)
    prev_width = max(0.0, px1 - px0)
    shifted_from_body = x0 - px0 >= max(34.0, body_width * 0.04)
    not_wider_than_body_lane = width <= prev_width + max(28.0, body_width * 0.04)
    return shifted_from_body and not_wider_than_body_lane


def _looks_like_strict_body_lane(
    block: Dict[str, Any],
    layout: LayoutStats,
    page_widths: Dict[int, float] | None = None,
) -> bool:
    bb = _bbox(block)
    if not bb:
        return False
    x0, _y0, x1, _y1 = [float(v) for v in bb]
    width = max(0.0, x1 - x0)
    page = _block_page(block)
    coord_width = page_widths.get(page) if page is not None and page_widths else None
    body_left, _body_right, body_width = _scaled_body_metrics(layout, coord_width)
    near_body_left = x0 <= body_left + max(24.0, body_width * 0.03)
    has_body_width = width >= body_width * 0.88
    return near_body_left and has_body_width
