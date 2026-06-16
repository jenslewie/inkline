"""Figure caption reconciliation. Collects figure captions and footnote-like text below figures, then attaches them to the nearest preceding figure block. Uses text style metrics to detect caption vs body text boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from ..normalize.builders import union_bbox
from ..schema.block_types import (
    CAPTION,
    FIGURE,
    FOOTNOTE,
    HEADING,
    PARAGRAPH,
    TABLE,
    TABLE_CONTINUATION,
)
from ..schema.models import BBox
from .block_access import block_bbox as _bbox
from .block_access import block_page as _block_page
from .constants import _DEFAULT_PAGE_HEIGHT
from .layout_helpers import _page_coord_heights, _page_coord_widths

__all__ = ["reconcile_figure_captions"]

CAPTION_TEXT_TYPES = {PARAGRAPH, CAPTION}
FIGURE_FLOW_BOUNDARY_TYPES = {FOOTNOTE, TABLE, FIGURE, TABLE_CONTINUATION}
FIGURE_EMBEDDED_TEXT_TYPES = {HEADING, PARAGRAPH}
FIGURE_FOLLOWING_CAPTION_TYPES = {HEADING, PARAGRAPH, CAPTION}


class _TextStyleProvider(Protocol):
    def block_style_size(self, block: Dict[str, Any]) -> Optional[float]: ...

    def page_body_style_size(self, page: int, blocks: List[Dict[str, Any]]) -> Optional[float]: ...


def reconcile_figure_captions(
    blocks: List[Dict[str, Any]], text_style: Optional[_TextStyleProvider] = None
) -> None:
    """Attach nearby title/paragraph caption blocks to preceding figures.

    MinerU sometimes emits a figure as an image block followed by a title and a
    paragraph that are visually part of the figure caption. Keeping those as
    normal flow blocks can prevent cross-page paragraph continuation.
    """

    _absorb_preceding_embedded_figure_text(blocks)
    _absorb_image_overlapping_text(blocks)
    _merge_adjacent_figure_fragments(blocks)

    i = 0
    while i < len(blocks):
        figure = blocks[i]
        if figure.get("type") != FIGURE:
            i += 1
            continue
        caption_idxs = _FigureCaptionDetector(blocks, text_style).collect_indices(i)
        if not caption_idxs:
            i += 1
            continue
        caption_blocks = [blocks[k] for k in caption_idxs]
        _attach_captions(figure, caption_blocks)
        for k in reversed(caption_idxs):
            del blocks[k]
        i += 1

    for idx, b in enumerate(blocks):
        if b.get("type") != CAPTION:
            continue
        prev_is_figure = idx > 0 and blocks[idx - 1].get("type") == FIGURE
        next_is_figure = idx + 1 < len(blocks) and blocks[idx + 1].get("type") == FIGURE
        if prev_is_figure or next_is_figure:
            continue
        b.setdefault("attrs", {})["caption_role"] = "legend"


@dataclass(frozen=True)
class _FigureCaptionDetector:
    """Detect caption blocks visually attached to a figure."""

    blocks: List[Dict[str, Any]]
    text_style: Optional[_TextStyleProvider] = None

    def collect_indices(self, figure_idx: int) -> List[int]:
        figure = self.blocks[figure_idx]
        page = _block_page(figure)
        if page is None:
            return []
        page_width = _page_coord_widths(self.blocks).get(page, _DEFAULT_PAGE_HEIGHT)
        page_height = _page_coord_heights(self.blocks).get(page, _DEFAULT_PAGE_HEIGHT)
        fbb = _bbox(figure)
        out: List[int] = []
        j = figure_idx + 1
        saw_text = False
        while j < len(self.blocks):
            candidate = self.blocks[j]
            if _block_page(candidate) != page:
                break
            cbb = _bbox(candidate)
            # Body text guard: if block looks like body content and is past the figure,
            # don't even try to match as caption
            if fbb and cbb:
                cw = float(cbb[2]) - float(cbb[0])
                gap = float(cbb[1]) - float(fbb[3])
                body_layout = float(cbb[0]) < page_width * 0.12 and cw > page_width * 0.50
                if body_layout and gap > 0:
                    break
            if self._is_flow_boundary(candidate):
                break
            if self._accept_heading(candidate, figure, out, saw_text):
                out.append(j)
                saw_text = True
                j += 1
                continue
            if self._accept_paragraph(candidate, figure, out, saw_text):
                out.append(j)
                saw_text = True
                j += 1
                continue
            break
        # Post-check: reject any accepted candidate that has returned to body text
        if out and fbb:
            last = self.blocks[out[-1]]
            last_cbb = _bbox(last)
            if last_cbb:
                last_cw = float(last_cbb[2]) - float(last_cbb[0])
                last_gap = float(last_cbb[1]) - float(fbb[3])
                if (
                    float(last_cbb[0]) < page_width * 0.12 and last_cw > page_width * 0.50
                ) or (last_gap > page_height * 0.10 and last_cw > page_width * 0.50):
                    return out[:-1] if len(out) > 1 else []
        return out if any(self.blocks[k].get("type") in CAPTION_TEXT_TYPES for k in out) else []

    @staticmethod
    def _is_flow_boundary(candidate: Dict[str, Any]) -> bool:
        return candidate.get("type") in FIGURE_FLOW_BOUNDARY_TYPES

    def _accept_heading(
        self,
        candidate: Dict[str, Any],
        figure: Dict[str, Any],
        caption_idxs: List[int],
        saw_text: bool,
    ) -> bool:
        if candidate.get("type") != HEADING:
            return False
        if saw_text or not _is_caption_like_heading(candidate):
            return False
        return _is_near_figure_caption_region(figure, candidate, caption_idxs, self.blocks)

    def _accept_paragraph(
        self,
        candidate: Dict[str, Any],
        figure: Dict[str, Any],
        caption_idxs: List[int],
        saw_text: bool,
    ) -> bool:
        if candidate.get("type") not in CAPTION_TEXT_TYPES:
            return False
        if candidate.get("type") == CAPTION and not saw_text:
            return False
        if not saw_text and _is_body_paragraph_after_large_float(figure, candidate, self.blocks):
            return False
        if caption_idxs and _is_body_sized_text_after_completed_caption(
            self.blocks[caption_idxs[-1]],
            candidate,
            self.blocks,
            self.text_style,
        ):
            return False
        return _is_near_figure_caption_region(figure, candidate, caption_idxs, self.blocks)


def _attach_captions(figure: Dict[str, Any], caption_blocks: List[Dict[str, Any]]) -> None:
    caption_text = "\n".join(
        str(b.get("text", "")).strip() for b in caption_blocks if str(b.get("text", "")).strip()
    )
    attrs = figure.setdefault("attrs", {})
    existing = attrs.setdefault("captions", [])
    if caption_text and caption_text not in existing:
        existing.append(caption_text)
    attrs["caption_block_ids"] = [b.get("block_id") for b in caption_blocks if b.get("block_id")]
    attrs["caption_raw_types"] = [(b.get("attrs") or {}).get("raw_type") for b in caption_blocks]
    attrs["caption_merge_reason"] = "nearby_figure_caption_layout"
    caption_bbox = union_bbox([_bbox(b) for b in caption_blocks])
    if caption_bbox:
        attrs["caption_bbox"] = caption_bbox
    source = figure.setdefault("source", {})
    original_bbox = source.get("bbox")
    if original_bbox:
        attrs.setdefault("image_bbox", original_bbox)
    source["bbox"] = union_bbox([original_bbox, caption_bbox])


def _absorb_image_overlapping_text(blocks: List[Dict[str, Any]]) -> None:
    """Absorb non-figure text blocks that overlap or are contained within a figure's image bbox.

    Uses three geometric criteria (OR): center containment, area overlap >= 0.50,
    OCR mechanical match at image edge. Body-text guard prevents false absorption
    of full-width body paragraphs. Only absorbs safe text types (paragraph, caption,
    heading) — flow boundaries (footnote, table, etc.) are never absorbed.
    Uses the original image bbox for all geometric decisions so absorption cannot
    snowball beyond the initial visual region.
    """
    if not blocks:
        return

    page_widths = _page_coord_widths(blocks)

    # Safe text types that can be absorbed; flow boundaries are excluded
    _SAFE_ABSORB_TYPES = {PARAGRAPH, CAPTION, HEADING}

    i = 0
    while i < len(blocks):
        figure = blocks[i]
        if figure.get("type") != FIGURE:
            i += 1
            continue

        page = _block_page(figure)
        if page is None:
            i += 1
            continue

        page_width = page_widths.get(page, _DEFAULT_PAGE_HEIGHT)

        # Capture the original image bbox before any absorption — used as
        # the stable geometric reference so the region never snowballs.
        # Only persisted to attrs when absorption actually occurs.
        attrs = figure.setdefault("attrs", {})
        stable_bbox = list(attrs.get("image_bbox") or _bbox(figure) or [])
        if not stable_bbox:
            i += 1
            continue

        ocr_text = str(attrs.get("ocr_text_in_image", "")).strip()

        j = i + 1
        while j < len(blocks):
            candidate = blocks[j]
            # Only absorb safe text types; stop on flow boundaries and any
            # other content-bearing type not explicitly whitelisted.
            cand_type = candidate.get("type")
            if cand_type in FIGURE_FLOW_BOUNDARY_TYPES or cand_type not in _SAFE_ABSORB_TYPES:
                break
            if _block_page(candidate) != page:
                break

            cbb = _bbox(candidate)
            if not cbb:
                j += 1
                continue

            # Body text guard: full-width block near body left margin means
            # body flow has resumed — stop scanning, not just skip this block.
            cw = float(cbb[2]) - float(cbb[0])
            if float(cbb[0]) < page_width * 0.12 and cw > page_width * 0.50:
                break

            # Criterion 1: center containment (using stable original bbox)
            center_x = (float(cbb[0]) + float(cbb[2])) / 2.0
            center_y = (float(cbb[1]) + float(cbb[3])) / 2.0
            center_contained = (
                float(stable_bbox[0]) - 5.0 <= center_x <= float(stable_bbox[2]) + 5.0
                and float(stable_bbox[1]) - 5.0 <= center_y <= float(stable_bbox[3]) + 5.0
            )

            # Criterion 2: area overlap (using stable original bbox)
            ix0 = max(float(cbb[0]), float(stable_bbox[0]))
            iy0 = max(float(cbb[1]), float(stable_bbox[1]))
            ix1 = min(float(cbb[2]), float(stable_bbox[2]))
            iy1 = min(float(cbb[3]), float(stable_bbox[3]))
            area_overlap = 0.0
            text_area = max(1.0, (float(cbb[2]) - float(cbb[0])) * (float(cbb[3]) - float(cbb[1])))
            if ix0 < ix1 and iy0 < iy1:
                intersection_area = (ix1 - ix0) * (iy1 - iy0)
                area_overlap = intersection_area / text_area

            # Criterion 3: OCR mechanical match (using stable original bbox)
            ocr_match = False
            candidate_text = str(candidate.get("text", "")).strip()
            if ocr_text and candidate_text:
                near_edge = (
                    abs(center_x - float(stable_bbox[0])) <= 10.0
                    or abs(center_x - float(stable_bbox[2])) <= 10.0
                    or abs(center_y - float(stable_bbox[1])) <= 10.0
                    or abs(center_y - float(stable_bbox[3])) <= 10.0
                )
                if near_edge and candidate_text in ocr_text:
                    ocr_match = True

            if not (center_contained or area_overlap >= 0.50 or ocr_match):
                j += 1
                continue

            # Persist the original bbox now that we're actually absorbing
            if not attrs.get("image_bbox"):
                attrs["image_bbox"] = list(stable_bbox)

            _absorb_text_blocks_into_figure(
                figure, [candidate], reason="image_overlapping_text"
            )
            del blocks[j]
            # Do NOT re-check the same figure — stable_bbox is immutable
            # so no snowballing. Just continue scanning remaining candidates.
            continue

        i += 1


def _absorb_preceding_embedded_figure_text(blocks: List[Dict[str, Any]]) -> None:
    i = 1
    while i < len(blocks):
        figure = blocks[i]
        candidate = blocks[i - 1]
        if figure.get("type") != FIGURE or candidate.get("type") not in FIGURE_EMBEDDED_TEXT_TYPES:
            i += 1
            continue
        if not _is_preceding_embedded_figure_text(candidate, figure):
            i += 1
            continue
        _absorb_text_blocks_into_figure(
            figure, [candidate], reason="preceding_embedded_figure_text_layout"
        )
        del blocks[i - 1]
        continue


def _is_preceding_embedded_figure_text(candidate: Dict[str, Any], figure: Dict[str, Any]) -> bool:
    if _block_page(candidate) != _block_page(figure):
        return False
    text = str(candidate.get("text", "")).strip()
    cbb = _bbox(candidate)
    fbb = _bbox(figure)
    if not text or not cbb or not fbb:
        return False
    gap = float(fbb[1]) - float(cbb[3])
    candidate_center = (float(cbb[0]) + float(cbb[2])) / 2.0
    horizontally_inside = float(fbb[0]) - 20.0 <= candidate_center <= float(fbb[2]) + 20.0
    narrow_or_short = len(text) <= 60 and (float(cbb[2]) - float(cbb[0])) <= max(
        220.0, (float(fbb[2]) - float(fbb[0])) * 0.45
    )
    return -8.0 <= gap <= 12.0 and horizontally_inside and narrow_or_short


def _absorb_text_blocks_into_figure(
    figure: Dict[str, Any], text_blocks: List[Dict[str, Any]], reason: str
) -> None:
    attrs = figure.setdefault("attrs", {})
    absorbed_text = attrs.setdefault("absorbed_text", [])
    for block in text_blocks:
        text = str(block.get("text", "")).strip()
        if text and text not in absorbed_text:
            absorbed_text.append(text)
    absorbed_ids = attrs.setdefault("absorbed_block_ids", [])
    for block in text_blocks:
        block_id = block.get("block_id")
        if block_id and block_id not in absorbed_ids:
            absorbed_ids.append(block_id)
    attrs["absorbed_block_count"] = len(absorbed_ids)
    attrs["embedded_text_absorbed"] = True
    attrs["embedded_text_absorb_reason"] = reason
    ocr_text = str(attrs.get("ocr_text_in_image") or "").strip()
    extra_text = "\n".join(
        str(block.get("text", "")).strip()
        for block in text_blocks
        if str(block.get("text", "")).strip()
    )
    if extra_text and extra_text not in ocr_text:
        attrs["ocr_text_in_image"] = "\n".join(part for part in [ocr_text, extra_text] if part)
    source = figure.setdefault("source", {})
    source["bbox"] = union_bbox([source.get("bbox"), *[_bbox(block) for block in text_blocks]])


def _merge_adjacent_figure_fragments(blocks: List[Dict[str, Any]]) -> None:
    i = 0
    while i + 1 < len(blocks):
        left = blocks[i]
        right = blocks[i + 1]
        if left.get("type") != FIGURE or right.get("type") != FIGURE:
            i += 1
            continue
        if not _is_same_visual_figure_fragment(blocks, i):
            i += 1
            continue
        _merge_figure_fragment_pair(left, right)
        del blocks[i + 1]


def _is_same_visual_figure_fragment(blocks: List[Dict[str, Any]], left_idx: int) -> bool:
    left = blocks[left_idx]
    right = blocks[left_idx + 1]
    if _block_page(left) != _block_page(right):
        return False
    lbb = _bbox(left)
    rbb = _bbox(right)
    if not lbb or not rbb:
        return False
    page = _block_page(left)
    page_width = (
        _page_coord_widths(blocks).get(page, _DEFAULT_PAGE_HEIGHT)
        if page is not None
        else _DEFAULT_PAGE_HEIGHT
    )
    page_height = (
        _page_coord_heights(blocks).get(page, _DEFAULT_PAGE_HEIGHT)
        if page is not None
        else _DEFAULT_PAGE_HEIGHT
    )
    lw = max(1.0, float(lbb[2]) - float(lbb[0]))
    lh = max(1.0, float(lbb[3]) - float(lbb[1]))
    rw = max(1.0, float(rbb[2]) - float(rbb[0]))
    rh = max(1.0, float(rbb[3]) - float(rbb[1]))
    vertical_overlap = min(float(lbb[3]), float(rbb[3])) - max(float(lbb[1]), float(rbb[1]))
    horizontal_gap = float(rbb[0]) - float(lbb[2])
    union = union_bbox([lbb, rbb])
    side_by_side_layout = (
        vertical_overlap >= min(lh, rh) * 0.40
        and -25.0 <= horizontal_gap <= page_width * 0.08
        and abs(float(lbb[1]) - float(rbb[1])) <= page_height * 0.10
        and abs(float(lbb[3]) - float(rbb[3])) <= page_height * 0.12
    )
    side_by_side = (
        side_by_side_layout
        and bool(union)
        and _has_following_caption_for_figure_pair(blocks, left_idx, union)
    )
    horizontal_overlap = min(float(lbb[2]), float(rbb[2])) - max(float(lbb[0]), float(rbb[0]))
    vertical_gap = float(rbb[1]) - float(lbb[3])
    left_attrs = left.get("attrs") or {}
    # Below-fragment: the lower block must be small relative to the left
    # figure (≤35% of left height) so only legend/sub-map fragments merge,
    # not independent full-size stacked figures. The page-height cap is kept
    # for uncaptioned left figures as an additional small-fragment signal.
    left_has_caption = bool(left_attrs.get("captions"))
    small_relative_to_left = rh <= lh * 0.35
    below_fragment = (
        horizontal_overlap >= min(lw, rw) * 0.40
        and -15.0 <= vertical_gap <= page_height * 0.12
        and (rh <= page_height * 0.08 or (left_has_caption and small_relative_to_left))
    )
    return side_by_side or below_fragment


def _has_following_caption_for_figure_pair(
    blocks: List[Dict[str, Any]], left_idx: int, pair_bbox: BBox
) -> bool:
    pair_page = _block_page(blocks[left_idx])
    if pair_page is None:
        return False
    pair_width = max(1.0, float(pair_bbox[2]) - float(pair_bbox[0]))
    pair_bottom = float(pair_bbox[3])
    for candidate in blocks[left_idx + 2 : left_idx + 6]:
        if _block_page(candidate) != pair_page:
            return False
        if candidate.get("type") in FIGURE_FLOW_BOUNDARY_TYPES:
            return False
        if candidate.get("type") not in FIGURE_FOLLOWING_CAPTION_TYPES:
            continue
        cbb = _bbox(candidate)
        if not cbb:
            continue
        gap = float(cbb[1]) - pair_bottom
        if not -20.0 <= gap <= 150.0:
            continue
        overlap = min(float(pair_bbox[2]), float(cbb[2])) - max(float(pair_bbox[0]), float(cbb[0]))
        candidate_width = float(cbb[2]) - float(cbb[0])
        if overlap >= pair_width * 0.50 or candidate_width >= pair_width * 0.45:
            return True
    return False


def _merge_figure_fragment_pair(left: Dict[str, Any], right: Dict[str, Any]) -> None:
    left_attrs = left.setdefault("attrs", {})
    right_attrs = right.get("attrs") or {}
    image_paths = left_attrs.setdefault("fragment_image_paths", [])
    for path in [left_attrs.get("image_path"), right_attrs.get("image_path")]:
        if path and path not in image_paths:
            image_paths.append(path)
    fragment_ids = left_attrs.setdefault("fragment_block_ids", [])
    for block_id in [left.get("block_id"), right.get("block_id")]:
        if block_id and block_id not in fragment_ids:
            fragment_ids.append(block_id)
    for key in ("captions", "footnotes"):
        values = list(left_attrs.get(key) or [])
        for value in right_attrs.get(key) or []:
            if value and value not in values:
                values.append(value)
        left_attrs[key] = values
    ocr_parts = [
        str(left_attrs.get("ocr_text_in_image") or "").strip(),
        str(right_attrs.get("ocr_text_in_image") or "").strip(),
    ]
    left_attrs["ocr_text_in_image"] = "\n".join(part for part in ocr_parts if part)
    left_attrs["figure_fragment_merge_reason"] = "adjacent_same_page_figure_fragments"
    source = left.setdefault("source", {})
    right_source = right.get("source") or {}
    source["bbox"] = union_bbox([source.get("bbox"), right_source.get("bbox")])
    pages = source.setdefault("pages", [source.get("page")])
    for page in right_source.get("pages") or [right_source.get("page")]:
        if page is not None and page not in pages:
            pages.append(page)
    spans = source.setdefault("spans", [])
    if not spans:
        spans.append(
            {"page": source.get("page"), "bbox": _bbox(left), "block_id": left.get("block_id")}
        )
    spans.append(
        {
            "page": right_source.get("page"),
            "bbox": right_source.get("bbox"),
            "block_id": right.get("block_id"),
        }
    )


def _is_caption_like_heading(block: Dict[str, Any]) -> bool:
    attrs = block.get("attrs") or {}
    if attrs.get("role") == "chapter_title":
        return False
    text = str(block.get("text", "")).strip()
    return 0 < len(text) <= 60


def _is_near_figure_caption_region(
    figure: Dict[str, Any],
    candidate: Dict[str, Any],
    existing_caption_idxs: List[int],
    blocks: List[Dict[str, Any]],
) -> bool:
    fbb = _bbox(figure)
    cbb = _bbox(candidate)
    if not fbb or not cbb:
        return False
    if existing_caption_idxs:
        return _is_caption_continuation(blocks[existing_caption_idxs[-1]], candidate)
    region = fbb
    page = _block_page(figure)
    page_width = (
        _page_coord_widths(blocks).get(page, _DEFAULT_PAGE_HEIGHT)
        if page is not None
        else _DEFAULT_PAGE_HEIGHT
    )
    page_height = (
        _page_coord_heights(blocks).get(page, _DEFAULT_PAGE_HEIGHT)
        if page is not None
        else _DEFAULT_PAGE_HEIGHT
    )
    return (
        _is_right_side_caption(region, cbb)
        or _is_below_caption(region, cbb, page_width, page_height)
        or (candidate.get("type") == HEADING and _is_below_caption_heading(region, cbb))
    )


def _is_caption_continuation(previous: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
    pbb = _bbox(previous)
    cbb = _bbox(candidate)
    if not pbb or not cbb:
        return False
    x_delta = abs(float(cbb[0]) - float(pbb[0]))
    y_gap = float(cbb[1]) - float(pbb[3])
    previous_text = str(previous.get("text", "")).strip()
    if previous_text.endswith(("。", "！", "？", ".", "）")) and y_gap > 24.0:
        return False
    return x_delta <= 35.0 and -10.0 <= y_gap <= 90.0


def _is_body_sized_text_after_completed_caption(
    previous: Dict[str, Any],
    candidate: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    text_style: Optional[_TextStyleProvider],
) -> bool:
    if text_style is None:
        return False
    previous_text = str(previous.get("text", "")).strip()
    if not previous_text.endswith(("。", "！", "？", ".", "）")):
        return False
    page = _block_page(candidate)
    if page is None:
        return False
    candidate_size = text_style.block_style_size(candidate)
    if candidate_size is None:
        return False
    body_size = text_style.page_body_style_size(page, blocks)
    previous_size = text_style.block_style_size(previous)
    if body_size is not None and candidate_size >= body_size * 0.94:
        return True
    if previous_size is not None and candidate_size >= previous_size * 1.12:
        return body_size is None or candidate_size >= body_size * 0.88
    return False


def _is_body_paragraph_after_large_float(
    figure: Dict[str, Any], candidate: Dict[str, Any], blocks: List[Dict[str, Any]]
) -> bool:
    fbb = _bbox(figure)
    cbb = _bbox(candidate)
    if not fbb or not cbb:
        return False
    page = _block_page(figure)
    page_width = (
        _page_coord_widths(blocks).get(page, _DEFAULT_PAGE_HEIGHT)
        if page is not None
        else _DEFAULT_PAGE_HEIGHT
    )
    page_height = (
        _page_coord_heights(blocks).get(page, _DEFAULT_PAGE_HEIGHT)
        if page is not None
        else _DEFAULT_PAGE_HEIGHT
    )
    figure_width = float(fbb[2]) - float(fbb[0])
    figure_height = float(fbb[3]) - float(fbb[1])
    candidate_width = float(cbb[2]) - float(cbb[0])
    gap = float(cbb[1]) - float(fbb[3])
    large_float = figure_width >= page_width * 0.70 or figure_height >= page_height * 0.45
    body_aligned = float(cbb[0]) <= page_width * 0.14 and candidate_width >= page_width * 0.50
    return large_float and body_aligned and 0 <= gap <= page_height * 0.12


def _is_right_side_caption(region: BBox, cbb: BBox) -> bool:
    vertical_overlap = min(float(region[3]), float(cbb[3])) - max(float(region[1]), float(cbb[1]))
    gap = float(cbb[0]) - float(region[2])
    return vertical_overlap >= -35.0 and -70.0 <= gap <= 180.0


def _is_below_caption(region: BBox, cbb: BBox, page_width: float, page_height: float) -> bool:
    gap = float(cbb[1]) - float(region[3])
    horizontal_overlap = min(float(region[2]), float(cbb[2])) - max(float(region[0]), float(cbb[0]))
    region_width = max(1.0, float(region[2]) - float(region[0]))
    region_height = max(1.0, float(region[3]) - float(region[1]))
    candidate_width = max(1.0, float(cbb[2]) - float(cbb[0]))
    large_float = region_width >= page_width * 0.62 or region_height >= page_height * 0.45
    body_width_text = candidate_width >= page_width * 0.62
    if large_float and body_width_text:
        return False
    return -15.0 <= gap <= 90.0 and horizontal_overlap >= region_width * 0.35


def _is_below_caption_heading(region: BBox, cbb: BBox) -> bool:
    gap = float(cbb[1]) - float(region[3])
    horizontal_overlap = min(float(region[2]), float(cbb[2])) - max(float(region[0]), float(cbb[0]))
    region_width = max(1.0, float(region[2]) - float(region[0]))
    left_aligned_near_region = abs(float(cbb[0]) - float(region[0])) <= 85.0
    return -15.0 <= gap <= 90.0 and (
        horizontal_overlap >= region_width * 0.10
        or region_width <= 280.0
        or left_aligned_near_region
    )
