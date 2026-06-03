"""Secondary marker evidence from PDF and model sources.

Collects note markers from model JSON output and PDF text layers, locates
positions via text prefix matching, and provides PDF image-based superscript
marker detection using OpenCV computer vision.

PDF access now goes through PdfPageCache when one is provided, avoiding
duplicate document opens and redundant rendering. When no cache is given,
the legacy direct-fitz.open fallback is used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ...analysis.pdf_page_metrics import PdfPageCache
from ...extraction.text import normalize_ws
from .marker_inline import _InlineMarkerLocation, _existing_ref_markers
from .marker_patterns import (
    BODY_TYPES,
    CLOSING_PUNCTUATION,
    QUOTE_BOUNDARY_PUNCTUATION,
    SECONDARY_MARKER_RE,
    TERMINAL_PUNCTUATION,
    _candidate_marker_offsets,
    _first_match_group,
    _marker_int,
    _strip_secondary_marker_markup,
    _visible_note_candidates,
)
from .scopes import _NoteContext

_NORMALIZED_COORD_THRESHOLD = 1000.0
_RAW_PAGE_DIM_THRESHOLD = 1200.0


@dataclass(frozen=True)
class _SecondaryMarker:
    page: int
    marker: int
    item_index: int
    char_index: int
    text: str
    bbox: Any = None
    source: str = "secondary"
    block_id: Optional[str] = None


def _secondary_markers_by_page(
    pages: Iterable[int],
    *,
    source_pdf: Any = None,
    model_json: Any = None,
    model_pages: Any = None,
    glm_ocr_pages: Any = None,
    pdf_cache: Optional[PdfPageCache] = None,
) -> Dict[int, List[_SecondaryMarker]]:
    wanted_pages = set(pages)
    markers = _model_markers_by_page(wanted_pages, model_json=model_json, model_pages=model_pages)
    glm_markers = _glm_ocr_markers_by_page(wanted_pages, glm_ocr_pages=glm_ocr_pages)
    for page, items in glm_markers.items():
        markers.setdefault(page, []).extend(items)
    pdf_markers = _pdf_text_markers_by_page(wanted_pages, source_pdf=source_pdf, pdf_cache=pdf_cache)
    for page, items in pdf_markers.items():
        markers.setdefault(page, []).extend(items)
        markers[page].sort(key=lambda item: (item.item_index, item.char_index))
    return markers


def _secondary_evidence_between_anchors(
    markers: Sequence[_SecondaryMarker],
    missing: int,
    left_anchor: int,
    right_anchor: int,
) -> Optional[_SecondaryMarker]:
    matches: List[_SecondaryMarker] = []
    for index, marker in enumerate(markers):
        if marker.marker != missing:
            continue
        has_left = any(prev.marker == left_anchor for prev in markers[:index])
        has_right = any(next_marker.marker == right_anchor for next_marker in markers[index + 1:])
        if has_left and has_right:
            matches.append(marker)
        elif marker.source == "glm_ocr_body":
            matches.append(marker)
    if len(matches) != 1:
        return None
    return matches[0]


def _inline_location_from_secondary_evidence(
    block: Dict[str, Any],
    evidence: _SecondaryMarker,
) -> Optional[_InlineMarkerLocation]:
    if evidence.source not in {"model_json", "pdf_text", "glm_ocr_body"}:
        return None
    text = str(block.get("text") or "")
    if not text:
        return None
    if evidence.source == "glm_ocr_body":
        if evidence.block_id:
            offset = _offset_after_ocr_prefix(text, evidence.text[: evidence.char_index])
        else:
            offset = _offset_after_ocr_marker_context(text, evidence.text, evidence.char_index)
        if offset is None:
            return None
        return _InlineMarkerLocation(
            char_index=offset,
            source=evidence.source,
            confidence="candidate",
            evidence={
                "inline_position_source": evidence.source,
                "inline_position_confidence": "candidate",
                "inline_position_offset": offset,
            },
        )
    for match in SECONDARY_MARKER_RE.finditer(evidence.text):
        marker = _marker_int(_first_match_group(match))
        if marker != evidence.marker:
            continue
        prefix = _strip_secondary_marker_markup(evidence.text[: match.start()])
        offset = _offset_after_prefix(text, prefix)
        if offset is None:
            continue
        return _InlineMarkerLocation(
            char_index=offset,
            source=evidence.source,
            confidence="anchored",
            evidence={
                "inline_position_source": evidence.source,
                "inline_position_confidence": "anchored",
                "inline_position_offset": offset,
            },
        )
    return None


def _target_block_for_secondary_marker(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
    page: int,
    evidence: _SecondaryMarker,
) -> Optional[Dict[str, Any]]:
    if evidence.source == "glm_ocr_body" and evidence.block_id:
        for block in blocks:
            block_id = str(block.get("block_id") or block.get("id") or "")
            if block_id != evidence.block_id:
                continue
            if block.get("type") not in BODY_TYPES:
                return None
            if page not in context.pages_for(block):
                return None
            if str(evidence.marker) in _existing_ref_markers(block):
                return None
            return block
    evidence_text = _strip_secondary_marker_markup(_evidence_target_text(evidence))
    best: Optional[Tuple[float, Dict[str, Any]]] = None
    for block in blocks:
        if block.get("type") not in BODY_TYPES:
            continue
        if page not in context.pages_for(block):
            continue
        if str(evidence.marker) in _existing_ref_markers(block):
            continue
        text = normalize_ws(str(block.get("text") or ""))
        if not text:
            continue
        score = _text_similarity(evidence_text, text)
        if score < 0.18:
            continue
        if best is None or score > best[0]:
            best = (score, block)
    return best[1] if best else None


def _locate_pdf_image_marker(
    block: Dict[str, Any],
    marker: int,
    *,
    source_pdf: Any = None,
    pdf_cache: Optional[PdfPageCache] = None,
) -> Optional[_InlineMarkerLocation]:
    if not source_pdf and pdf_cache is None:
        return None
    text = str(block.get("text") or "")
    bbox = (block.get("source") or {}).get("bbox")
    page_number = (block.get("source") or {}).get("page")
    if not text or not isinstance(bbox, list) or not isinstance(page_number, int):
        return None
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None

    if pdf_cache is not None and pdf_cache.pdf_available:
        image = pdf_cache.page_image(page_number)
        if image is None:
            return None
        scale = pdf_cache.render_zoom
        rect = pdf_cache.page_rect(page_number)
        if rect is None:
            return None
        crop, crop_origin = _crop_pil_bbox(image, rect.width, rect.height, bbox, scale)
    else:
        path = Path(str(source_pdf))
        if not path.exists():
            return None
        try:
            import fitz  # type: ignore

            with fitz.open(path) as doc:
                if page_number < 1 or page_number > doc.page_count:
                    return None
                page = doc[page_number - 1]
                scale = 3.0
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
                crop, crop_origin = _crop_normalized_bbox(image, page.rect.width, page.rect.height, bbox, scale)
        except Exception:
            return None

    if crop.size == 0:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    binary = (gray < 180).astype("uint8")
    bands = _text_line_bands(binary, np=np)
    if len(bands) < 1:
        return None
    line_extents = _line_extents(binary, bands, np=np)
    wrapped = _wrap_text_to_image_lines(text, bands, line_extents)
    if not wrapped:
        return None

    candidates: List[Tuple[float, int, Dict[str, Any]]] = []
    for offset in _candidate_marker_offsets(text):
        placed = _project_text_offset(offset, text, wrapped, bands, line_extents)
        if placed is None:
            continue
        line_index, x, band, extent = placed
        score, details = _score_superscript_zone(binary, x, band, cv2=cv2, np=np)
        if score <= 0:
            continue
        details.update(
            {
                "pdf_page": page_number,
                "pdf_marker": str(marker),
                "pdf_crop_origin": [round(crop_origin[0], 3), round(crop_origin[1], 3)],
                "pdf_line_index": line_index,
                "pdf_line_band": [int(band[0]), int(band[1])],
                "pdf_line_extent": [int(extent[0]), int(extent[1])],
                "inline_position_source": "pdf_image",
                "inline_position_confidence": "candidate",
                "inline_position_offset": offset,
            }
        )
        candidates.append((score, offset, details))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] <= 1.0:
        return None
    score, offset, details = candidates[0]
    if score < 2.0:
        return None
    details["pdf_image_score"] = round(score, 3)
    return _InlineMarkerLocation(
        char_index=offset,
        source="pdf_image",
        confidence="candidate",
        evidence=details,
    )


def _model_markers_by_page(
    pages: Set[int],
    *,
    model_json: Any = None,
    model_pages: Any = None,
) -> Dict[int, List[_SecondaryMarker]]:
    model_data = model_pages if model_pages is not None else _load_model_json(model_json)
    if not isinstance(model_data, list):
        return {}
    out: Dict[int, List[_SecondaryMarker]] = {}
    for page in sorted(pages):
        if page < 1 or page > len(model_data):
            continue
        page_items = model_data[page - 1]
        if not isinstance(page_items, list):
            continue
        for item_index, item in enumerate(page_items):
            if not isinstance(item, dict):
                continue
            text = str(item.get("content") or item.get("text") or "")
            for match in SECONDARY_MARKER_RE.finditer(text):
                marker = _marker_int(_first_match_group(match))
                if marker is None:
                    continue
                out.setdefault(page, []).append(
                    _SecondaryMarker(
                        page=page,
                        marker=marker,
                        item_index=item_index,
                        char_index=match.start(),
                        text=text,
                        bbox=item.get("bbox"),
                        source="model_json",
                    )
                )
    return out


def _glm_ocr_markers_by_page(
    pages: Set[int],
    *,
    glm_ocr_pages: Any = None,
) -> Dict[int, List[_SecondaryMarker]]:
    if not glm_ocr_pages:
        return {}
    if isinstance(glm_ocr_pages, dict):
        items = glm_ocr_pages.get("pages") or []
    else:
        items = glm_ocr_pages
    if not isinstance(items, list):
        return {}
    out: Dict[int, List[_SecondaryMarker]] = {}
    for item_index, item in enumerate(items):
        page = _glm_item_value(item, "page")
        kind = _glm_item_value(item, "kind")
        text = str(_glm_item_value(item, "raw_text") or "")
        block_id = _glm_item_value(item, "block_id")
        if not isinstance(page, int) or page not in pages or kind not in {"body_block", "page_body", "full_page"} or not text:
            continue
        for raw_marker, marker_text, _reason in _visible_note_candidates(text):
            marker = _marker_int(marker_text)
            if marker is None:
                continue
            char_index = text.find(raw_marker)
            out.setdefault(page, []).append(
                _SecondaryMarker(
                    page=page,
                    marker=marker,
                    item_index=item_index,
                    char_index=max(char_index, 0),
                    text=text,
                    source="glm_ocr_body",
                    block_id=str(block_id or "") or None,
                )
            )
    return out


def _glm_item_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _pdf_text_markers_by_page(
    pages: Set[int],
    *,
    source_pdf: Any = None,
    pdf_cache: Optional[PdfPageCache] = None,
) -> Dict[int, List[_SecondaryMarker]]:
    if pdf_cache is not None and pdf_cache.pdf_available:
        out: Dict[int, List[_SecondaryMarker]] = {}
        for page in sorted(pages):
            lines = pdf_cache.page_text_lines(page)
            if not lines:
                continue
            for item_index, (_lbb, line_text) in enumerate(lines):
                for raw_marker, marker_text, reason in _visible_note_candidates(line_text):
                    marker = _marker_int(marker_text)
                    if marker is None or reason != "superscript_digit":
                        continue
                    char_index = line_text.find(raw_marker)
                    out.setdefault(page, []).append(
                        _SecondaryMarker(
                            page=page,
                            marker=marker,
                            item_index=item_index,
                            char_index=max(char_index, 0),
                            text=line_text,
                            source="pdf_text",
                        )
                    )
        return out

    if not source_pdf:
        return {}
    try:
        import fitz  # type: ignore
    except Exception:
        return {}

    path = Path(str(source_pdf))
    if not path.exists():
        return {}
    out: Dict[int, List[_SecondaryMarker]] = {}
    try:
        with fitz.open(path) as doc:
            for page in sorted(pages):
                if page < 1 or page > doc.page_count:
                    continue
                text = doc[page - 1].get_text("text") or ""
                if not text.strip():
                    continue
                for item_index, line in enumerate(text.splitlines()):
                    for raw_marker, marker_text, reason in _visible_note_candidates(line):
                        marker = _marker_int(marker_text)
                        if marker is None or reason != "superscript_digit":
                            continue
                        char_index = line.find(raw_marker)
                        out.setdefault(page, []).append(
                            _SecondaryMarker(
                                page=page,
                                marker=marker,
                                item_index=item_index,
                                char_index=max(char_index, 0),
                                text=line,
                                source="pdf_text",
                            )
                        )
    except Exception:
        return out
    return out


def _load_model_json(model_json: Any) -> Any:
    if not model_json:
        return None
    try:
        path = Path(str(model_json))
    except TypeError:
        return None
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _offset_after_prefix(text: str, prefix: str) -> Optional[int]:
    prefix = normalize_ws(prefix)
    if not prefix:
        return 0
    if text.startswith(prefix):
        return len(prefix)
    compact_prefix = normalize_ws(prefix)
    compact_text = normalize_ws(text)
    if compact_text.startswith(compact_prefix):
        return _offset_for_normalized_prefix(text, compact_prefix)
    index = compact_text.find(compact_prefix)
    if index == 0:
        return _offset_for_normalized_prefix(text, compact_prefix)
    return None


def _offset_after_ocr_prefix(text: str, prefix: str) -> Optional[int]:
    prefix = normalize_ws(prefix)
    if not prefix:
        return 0
    offset = _offset_after_prefix(text, prefix)
    if offset is not None:
        return offset
    compact_text, end_offsets = _normalized_text_with_end_offsets(text)
    indexes: List[int] = []
    start = 0
    while True:
        index = compact_text.find(prefix, start)
        if index < 0:
            break
        indexes.append(index)
        start = index + 1
        if len(indexes) > 1:
            return None
    if len(indexes) != 1:
        return None
    end_index = indexes[0] + len(prefix) - 1
    if end_index < 0 or end_index >= len(end_offsets):
        return None
    return end_offsets[end_index]


def _offset_after_ocr_marker_context(text: str, ocr_text: str, marker_index: int) -> Optional[int]:
    before = normalize_ws(ocr_text[:marker_index])
    if not before:
        return 0
    compact_text, end_offsets = _normalized_text_with_end_offsets(text)
    for length in (80, 50, 30, 18, 10):
        if len(before) < length:
            continue
        suffix = before[-length:]
        matches: List[int] = []
        start = 0
        while True:
            found = compact_text.find(suffix, start)
            if found < 0:
                break
            matches.append(found)
            start = found + 1
            if len(matches) > 1:
                break
        if len(matches) == 1:
            end_index = matches[0] + len(suffix) - 1
            if 0 <= end_index < len(end_offsets):
                return end_offsets[end_index]
    return None


def _evidence_target_text(evidence: _SecondaryMarker) -> str:
    if evidence.source == "glm_ocr_body" and not evidence.block_id:
        line_start = evidence.text.rfind("\n", 0, evidence.char_index) + 1
        line_end = evidence.text.find("\n", evidence.char_index)
        if line_end < 0:
            line_end = len(evidence.text)
        start = line_start
        end = line_end
        return evidence.text[start:end]
    return evidence.text


def _offset_for_normalized_prefix(text: str, prefix: str, *, base_offset: int = 0) -> Optional[int]:
    if not prefix:
        return base_offset
    out = []
    last_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if not last_space:
                out.append(" ")
                last_space = True
        else:
            out.append(char)
            last_space = False
        if "".join(out).strip() == prefix:
            return base_offset + index + 1
    return None


def _normalized_text_with_end_offsets(text: str) -> Tuple[str, List[int]]:
    chars: List[str] = []
    offsets: List[int] = []
    last_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if last_space:
                continue
            chars.append(" ")
            offsets.append(index + 1)
            last_space = True
            continue
        chars.append(char)
        offsets.append(index + 1)
        last_space = False
    compact = "".join(chars).strip()
    if compact == "".join(chars):
        return compact, offsets
    leading = len("".join(chars)) - len("".join(chars).lstrip())
    trailing = len("".join(chars).rstrip())
    return compact, offsets[leading:trailing]


def _text_similarity(left: str, right: str) -> float:
    left = normalize_ws(left)
    right = normalize_ws(right)
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _crop_normalized_bbox(
    image: Any,
    page_width: float,
    page_height: float,
    bbox: List[Any],
    scale: float,
) -> Tuple[Any, Tuple[float, float]]:
    import numpy as np  # type: ignore

    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    if max(abs(x0), abs(y0), abs(x1), abs(y1)) <= _NORMALIZED_COORD_THRESHOLD and max(page_width, page_height) > _RAW_PAGE_DIM_THRESHOLD:
        x0 = x0 / _NORMALIZED_COORD_THRESHOLD * page_width
        x1 = x1 / _NORMALIZED_COORD_THRESHOLD * page_width
        y0 = y0 / _NORMALIZED_COORD_THRESHOLD * page_height
        y1 = y1 / _NORMALIZED_COORD_THRESHOLD * page_height
    pad_x = 8.0
    pad_y = 8.0
    left = max(0, int((x0 - pad_x) * scale))
    top = max(0, int((y0 - pad_y) * scale))
    right = min(image.shape[1], int((x1 + pad_x) * scale))
    bottom = min(image.shape[0], int((y1 + pad_y) * scale))
    if right <= left or bottom <= top:
        return np.empty((0, 0, 3), dtype=image.dtype), (0.0, 0.0)
    return image[top:bottom, left:right], (left / scale, top / scale)


def _crop_pil_bbox(
    image: Any,
    page_width: float,
    page_height: float,
    bbox: List[Any],
    scale: float,
) -> Tuple[Any, Tuple[float, float]]:
    import numpy as np  # type: ignore

    arr = np.array(image)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    if max(abs(x0), abs(y0), abs(x1), abs(y1)) <= _NORMALIZED_COORD_THRESHOLD and max(page_width, page_height) > _RAW_PAGE_DIM_THRESHOLD:
        x0 = x0 / _NORMALIZED_COORD_THRESHOLD * page_width
        x1 = x1 / _NORMALIZED_COORD_THRESHOLD * page_width
        y0 = y0 / _NORMALIZED_COORD_THRESHOLD * page_height
        y1 = y1 / _NORMALIZED_COORD_THRESHOLD * page_height
    pad_x = 8.0
    pad_y = 8.0
    left = max(0, int((x0 - pad_x) * scale))
    top = max(0, int((y0 - pad_y) * scale))
    right = min(arr.shape[1], int((x1 + pad_x) * scale))
    bottom = min(arr.shape[0], int((y1 + pad_y) * scale))
    if right <= left or bottom <= top:
        return np.empty((0, 0, 3), dtype=np.uint8), (0.0, 0.0)
    return arr[top:bottom, left:right], (left / scale, top / scale)


def _text_line_bands(binary: Any, *, np: Any) -> List[Tuple[int, int]]:
    projection = binary.sum(axis=1)
    if projection.size == 0:
        return []
    smoothed = np.convolve(projection, np.ones(7) / 7, mode="same")
    rows = np.where(smoothed > 5)[0]
    if len(rows) == 0:
        return []
    bands: List[Tuple[int, int]] = []
    start = int(rows[0])
    previous = int(rows[0])
    for row in rows[1:]:
        row = int(row)
        if row - previous > 6:
            bands.append((start, previous))
            start = row
        previous = row
    bands.append((start, previous))
    return [band for band in bands if band[1] - band[0] >= 8]


def _line_extents(binary: Any, bands: Sequence[Tuple[int, int]], *, np: Any) -> List[Tuple[int, int]]:
    extents: List[Tuple[int, int]] = []
    width = int(binary.shape[1])
    for top, bottom in bands:
        sub = binary[max(0, top - 5): min(binary.shape[0], bottom + 5), :]
        _ys, xs = np.where(sub)
        if len(xs) == 0:
            extents.append((0, max(0, width - 1)))
        else:
            extents.append((int(xs.min()), int(xs.max())))
    return extents


def _wrap_text_to_image_lines(
    text: str,
    bands: Sequence[Tuple[int, int]],
    line_extents: Sequence[Tuple[int, int]],
) -> List[Tuple[int, int]]:
    weights = [_char_visual_weight(char) for char in text]
    total_weight = sum(weights)
    if not text or total_weight <= 0:
        return []
    total_width = sum(max(1, right - left) for left, right in line_extents)
    char_px = total_width / total_weight
    out: List[Tuple[int, int]] = []
    start = 0
    for index, (left, right) in enumerate(line_extents):
        if index == len(bands) - 1:
            out.append((start, len(text)))
            break
        capacity = max(1, right - left) / char_px
        end = start
        current = 0.0
        while end < len(text) and current + weights[end] <= capacity:
            current += weights[end]
            end += 1
        while end < len(text) and text[end] in TERMINAL_PUNCTUATION | CLOSING_PUNCTUATION | QUOTE_BOUNDARY_PUNCTUATION | {"、", ",", "."}:
            end += 1
        if end <= start:
            end = min(len(text), start + 1)
        out.append((start, end))
        start = end
    return out


def _char_visual_weight(char: str) -> float:
    import unicodedata

    if char.isspace():
        return 0.35
    if char.isascii():
        return 0.55 if char.isalnum() else 0.35
    if unicodedata.category(char).startswith("P"):
        return 0.5
    return 1.0


def _project_text_offset(
    offset: int,
    text: str,
    wrapped: Sequence[Tuple[int, int]],
    bands: Sequence[Tuple[int, int]],
    line_extents: Sequence[Tuple[int, int]],
) -> Optional[Tuple[int, float, Tuple[int, int], Tuple[int, int]]]:
    for line_index, (start, end) in enumerate(wrapped):
        if start < offset <= end or (offset == 0 and start == 0):
            left, right = line_extents[line_index]
            line_text = text[start:end]
            line_weight = sum(_char_visual_weight(char) for char in line_text) or 1.0
            prefix_weight = sum(_char_visual_weight(char) for char in text[start:offset])
            x = left + (right - left) * min(1.0, prefix_weight / line_weight)
            return line_index, x, bands[line_index], line_extents[line_index]
    return None


def _score_superscript_zone(binary: Any, x: float, band: Tuple[int, int], *, cv2: Any, np: Any) -> Tuple[float, Dict[str, Any]]:
    line_height = max(1, band[1] - band[0])
    x0 = max(0, int(x - 45))
    x1 = min(binary.shape[1], int(x + 75))
    y0 = max(0, int(band[0] - line_height * 0.25))
    y1 = min(binary.shape[0], int(band[0] + line_height * 0.58))
    if x1 <= x0 or y1 <= y0:
        return 0.0, {}
    zone = binary[y0:y1, x0:x1]
    components = _zone_components(zone, x0, y0, cv2=cv2)
    small = [
        comp for comp in components
        if 8 <= comp["area"] <= 260
        and 2 <= comp["width"] <= 28
        and 4 <= comp["height"] <= max(12, int(line_height * 0.38))
        and comp["y"] <= band[0] + line_height * 0.25
        and comp["x"] >= x - 45
    ]
    if not small:
        return 0.0, {"pdf_marker_components": components[:8]}
    aligned_bonus = 0.0
    for left in small:
        for right in small:
            if left is right:
                continue
            if abs(left["x"] - right["x"]) <= 5 and 5 <= abs(left["y"] - right["y"]) <= max(10, line_height * 0.35):
                aligned_bonus = 1.0
                break
        if aligned_bonus:
            break
    large_penalty = sum(
        0.5 for comp in components
        if comp["height"] > line_height * 0.45 and comp["x"] < x + 65
    )
    score = len(small) + aligned_bonus - large_penalty
    return score, {
        "pdf_marker_components": small[:8],
        "pdf_marker_zone": [x0, y0, x1, y1],
    }


def _zone_components(zone: Any, x_offset: int, y_offset: int, *, cv2: Any) -> List[Dict[str, int]]:
    num, _labels, stats, _centroids = cv2.connectedComponentsWithStats((zone * 255).astype("uint8"), 8)
    out: List[Dict[str, int]] = []
    for index in range(1, num):
        x, y, width, height, area = [int(value) for value in stats[index]]
        if area < 6:
            continue
        out.append(
            {
                "x": x + x_offset,
                "y": y + y_offset,
                "width": width,
                "height": height,
                "area": area,
            }
        )
    return out
