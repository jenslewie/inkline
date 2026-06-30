"""Figure caption reconciliation. Collects figure captions and footnote-like text below figures, then attaches them to the nearest preceding figure block. Uses text style metrics to detect caption vs body text boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from ..normalize.builders import union_bbox
from ..schema.block_types import (
    CAPTION,
    DISPLAY_BLOCK,
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

CAPTION_TEXT_TYPES = {PARAGRAPH, CAPTION, DISPLAY_BLOCK}
FIGURE_FLOW_BOUNDARY_TYPES = {FOOTNOTE, TABLE, FIGURE, TABLE_CONTINUATION}
FIGURE_EMBEDDED_TEXT_TYPES = {HEADING, PARAGRAPH}
FIGURE_FOLLOWING_CAPTION_TYPES = {HEADING, PARAGRAPH, CAPTION}


@dataclass(frozen=True)
class _FigureCaptionContext:
    figure: Dict[str, Any]
    page: int
    page_width: float
    page_height: float
    bbox: BBox


@dataclass(frozen=True)
class _ImageOverlapContext:
    figure: Dict[str, Any]
    page: int
    page_width: float
    attrs: Dict[str, Any]
    stable_bbox: BBox
    ocr_text: str


@dataclass(frozen=True)
class _LegendStripContext:
    page: int
    page_height: float
    figure_height: float
    anchor_left: float
    anchor_right: float
    anchor_width: float
    max_gap: float
    max_strip_bottom: float


@dataclass(frozen=True)
class _LegendStripState:
    out: List[int]
    current_bottom: float
    has_visual_fragment: bool = False
    has_text_fragment: bool = False
    total_text_chars: int = 0
    rejected: bool = False


@dataclass(frozen=True)
class _FigurePairGeometry:
    page_width: float
    page_height: float
    left_width: float
    left_height: float
    right_width: float
    right_height: float
    vertical_overlap: float
    horizontal_overlap: float
    horizontal_gap: float
    vertical_gap: float


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
    _absorb_following_visual_legend_strips(blocks)
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
        context = _figure_caption_context(self.blocks, figure_idx)
        if context is None:
            return []
        out: List[int] = []
        j = figure_idx + 1
        saw_text = False
        while j < len(self.blocks):
            candidate = self.blocks[j]
            if _block_page(candidate) != context.page:
                break
            if self._body_flow_resumed(candidate, context, out):
                break
            if self._is_flow_boundary(candidate):
                break
            if self._accept_heading(candidate, context.figure, out, saw_text):
                out.append(j)
                saw_text = True
                j += 1
                continue
            if self._accept_paragraph(candidate, context.figure, out, saw_text):
                out.append(j)
                saw_text = True
                j += 1
                continue
            break
        out = self._trim_body_text_tail(out, context)
        return out if any(self.blocks[k].get("type") in CAPTION_TEXT_TYPES for k in out) else []

    @staticmethod
    def _is_flow_boundary(candidate: Dict[str, Any]) -> bool:
        return candidate.get("type") in FIGURE_FLOW_BOUNDARY_TYPES

    def _body_flow_resumed(
        self,
        candidate: Dict[str, Any],
        context: _FigureCaptionContext,
        caption_idxs: List[int],
    ) -> bool:
        cbb = _bbox(candidate)
        if not cbb:
            return False
        width = float(cbb[2]) - float(cbb[0])
        gap = float(cbb[1]) - float(context.bbox[3])
        body_layout = float(cbb[0]) < context.page_width * 0.12 and width > context.page_width * 0.50
        heading_continuation = (
            bool(caption_idxs)
            and self.blocks[caption_idxs[-1]].get("type") == HEADING
            and _is_caption_continuation(self.blocks[caption_idxs[-1]], candidate)
        )
        return body_layout and gap > 0 and not heading_continuation

    def _trim_body_text_tail(
        self, caption_idxs: List[int], context: _FigureCaptionContext
    ) -> List[int]:
        if not caption_idxs:
            return caption_idxs
        last = self.blocks[caption_idxs[-1]]
        last_cbb = _bbox(last)
        if not last_cbb:
            return caption_idxs
        if not self._is_body_text_tail(caption_idxs, last, last_cbb, context):
            return caption_idxs
        return caption_idxs[:-1] if len(caption_idxs) > 1 else []

    def _is_body_text_tail(
        self,
        caption_idxs: List[int],
        last: Dict[str, Any],
        last_bbox: BBox,
        context: _FigureCaptionContext,
    ) -> bool:
        width = float(last_bbox[2]) - float(last_bbox[0])
        gap = float(last_bbox[1]) - float(context.bbox[3])
        heading_continuation = (
            len(caption_idxs) > 1
            and self.blocks[caption_idxs[-2]].get("type") == HEADING
            and _is_caption_continuation(self.blocks[caption_idxs[-2]], last)
        )
        body_width = width > context.page_width * 0.50
        body_left = float(last_bbox[0]) < context.page_width * 0.12
        far_from_figure = gap > context.page_height * 0.10
        return not heading_continuation and body_width and (body_left or far_from_figure)

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
    attrs["caption_raw_types"] = [_caption_raw_type(b) for b in caption_blocks]
    attrs["caption_merge_reason"] = "nearby_figure_caption_layout"
    caption_bbox = union_bbox([_bbox(b) for b in caption_blocks])
    if caption_bbox:
        attrs["caption_bbox"] = caption_bbox
    source = figure.setdefault("source", {})
    original_bbox = source.get("bbox")
    if original_bbox:
        attrs.setdefault("image_bbox", original_bbox)
    source["bbox"] = union_bbox([original_bbox, caption_bbox])


def _figure_caption_context(
    blocks: List[Dict[str, Any]], figure_idx: int
) -> Optional[_FigureCaptionContext]:
    figure = blocks[figure_idx]
    page = _block_page(figure)
    bbox = _bbox(figure)
    if page is None or not bbox:
        return None
    return _FigureCaptionContext(
        figure=figure,
        page=page,
        page_width=_page_coord_widths(blocks).get(page, _DEFAULT_PAGE_HEIGHT),
        page_height=_page_coord_heights(blocks).get(page, _DEFAULT_PAGE_HEIGHT),
        bbox=bbox,
    )


def _caption_raw_type(block: Dict[str, Any]) -> Any:
    attrs = block.get("attrs") or {}
    raw_type = attrs.get("raw_type")
    if raw_type:
        return raw_type
    raw_types = attrs.get("raw_types")
    if isinstance(raw_types, list) and len(raw_types) == 1 and raw_types[0]:
        return raw_types[0]
    return block.get("type")


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
    i = 0
    while i < len(blocks):
        context = _image_overlap_context(blocks[i], page_widths)
        if context is None:
            i += 1
            continue
        _absorb_overlapping_text_after_figure(blocks, i + 1, context)
        i += 1


def _image_overlap_context(
    figure: Dict[str, Any], page_widths: Dict[int, float]
) -> Optional[_ImageOverlapContext]:
    if figure.get("type") != FIGURE:
        return None
    page = _block_page(figure)
    if page is None:
        return None
    attrs = figure.setdefault("attrs", {})
    stable_bbox = list(attrs.get("image_bbox") or _bbox(figure) or [])
    if not stable_bbox:
        return None
    return _ImageOverlapContext(
        figure=figure,
        page=page,
        page_width=page_widths.get(page, _DEFAULT_PAGE_HEIGHT),
        attrs=attrs,
        stable_bbox=stable_bbox,
        ocr_text=str(attrs.get("ocr_text_in_image", "")).strip(),
    )


def _absorb_overlapping_text_after_figure(
    blocks: List[Dict[str, Any]], start_idx: int, context: _ImageOverlapContext
) -> None:
    safe_absorb_types = {PARAGRAPH, CAPTION, HEADING}
    j = start_idx
    while j < len(blocks):
        candidate = blocks[j]
        candidate_type = candidate.get("type")
        if candidate_type in FIGURE_FLOW_BOUNDARY_TYPES or candidate_type not in safe_absorb_types:
            break
        if _block_page(candidate) != context.page:
            break
        candidate_bbox = _bbox(candidate)
        if not candidate_bbox:
            j += 1
            continue
        if _is_body_width_text(candidate_bbox, context.page_width):
            break
        if not _overlaps_stable_image_region(candidate, candidate_bbox, context):
            j += 1
            continue
        if not context.attrs.get("image_bbox"):
            context.attrs["image_bbox"] = list(context.stable_bbox)
        _absorb_text_blocks_into_figure(
            context.figure, [candidate], reason="image_overlapping_text"
        )
        del blocks[j]


def _is_body_width_text(bbox: BBox, page_width: float) -> bool:
    width = float(bbox[2]) - float(bbox[0])
    return float(bbox[0]) < page_width * 0.12 and width > page_width * 0.50


def _overlaps_stable_image_region(
    candidate: Dict[str, Any], candidate_bbox: BBox, context: _ImageOverlapContext
) -> bool:
    center_x = (float(candidate_bbox[0]) + float(candidate_bbox[2])) / 2.0
    center_y = (float(candidate_bbox[1]) + float(candidate_bbox[3])) / 2.0
    return (
        _center_inside_bbox(center_x, center_y, context.stable_bbox)
        or _area_overlap_ratio(candidate_bbox, context.stable_bbox) >= 0.50
        or _ocr_edge_match(candidate, center_x, center_y, context)
    )


def _center_inside_bbox(center_x: float, center_y: float, bbox: BBox) -> bool:
    return (
        float(bbox[0]) - 5.0 <= center_x <= float(bbox[2]) + 5.0
        and float(bbox[1]) - 5.0 <= center_y <= float(bbox[3]) + 5.0
    )


def _area_overlap_ratio(candidate_bbox: BBox, image_bbox: BBox) -> float:
    ix0 = max(float(candidate_bbox[0]), float(image_bbox[0]))
    iy0 = max(float(candidate_bbox[1]), float(image_bbox[1]))
    ix1 = min(float(candidate_bbox[2]), float(image_bbox[2]))
    iy1 = min(float(candidate_bbox[3]), float(image_bbox[3]))
    if ix0 >= ix1 or iy0 >= iy1:
        return 0.0
    text_area = max(
        1.0,
        (float(candidate_bbox[2]) - float(candidate_bbox[0]))
        * (float(candidate_bbox[3]) - float(candidate_bbox[1])),
    )
    return ((ix1 - ix0) * (iy1 - iy0)) / text_area


def _ocr_edge_match(
    candidate: Dict[str, Any],
    center_x: float,
    center_y: float,
    context: _ImageOverlapContext,
) -> bool:
    candidate_text = str(candidate.get("text", "")).strip()
    if not context.ocr_text or not candidate_text:
        return False
    near_edge = (
        abs(center_x - float(context.stable_bbox[0])) <= 10.0
        or abs(center_x - float(context.stable_bbox[2])) <= 10.0
        or abs(center_y - float(context.stable_bbox[1])) <= 10.0
        or abs(center_y - float(context.stable_bbox[3])) <= 10.0
    )
    return near_edge and candidate_text in context.ocr_text


def _absorb_following_visual_legend_strips(blocks: List[Dict[str, Any]]) -> None:
    """Absorb compact legend/title strips that MinerU emitted below a visual figure.

    These are not reading-flow captions. They are pieces of the source image,
    often emitted as text/image/text immediately below a map or diagram.
    """
    i = 0
    while i < len(blocks):
        figure = blocks[i]
        if figure.get("type") != FIGURE:
            i += 1
            continue
        strip_idxs = _following_visual_legend_strip_indices(blocks, i)
        if not strip_idxs:
            i += 1
            continue
        for idx in strip_idxs:
            candidate = blocks[idx]
            if candidate.get("type") == FIGURE:
                _merge_figure_fragment_pair(figure, candidate)
            else:
                _absorb_text_blocks_into_figure(
                    figure, [candidate], reason="following_visual_legend_strip"
                )
        attrs = figure.setdefault("attrs", {})
        existing_captions = [cap for cap in attrs.get("captions") or [] if cap]
        if existing_captions:
            attrs["visual_legend_captions_absorbed"] = existing_captions
            attrs["captions"] = []
        for idx in reversed(strip_idxs):
            del blocks[idx]
        i += 1


def _following_visual_legend_strip_indices(
    blocks: List[Dict[str, Any]], figure_idx: int
) -> List[int]:
    context = _legend_strip_context(blocks, figure_idx)
    if context is None:
        return []
    state = _LegendStripState(out=[], current_bottom=context.max_strip_bottom - context.page_height * 0.14)
    j = figure_idx + 1
    while j < len(blocks):
        candidate = blocks[j]
        updated = _next_legend_strip_state(candidate, j, context, state)
        if updated is None:
            break
        if updated.rejected:
            return []
        state = updated
        j += 1
    return _accepted_legend_strip_indices(state)


def _legend_strip_context(
    blocks: List[Dict[str, Any]], figure_idx: int
) -> Optional[_LegendStripContext]:
    figure = blocks[figure_idx]
    page = _block_page(figure)
    bbox = _bbox(figure)
    if page is None or not bbox:
        return None
    page_height = _page_coord_heights(blocks).get(page, _DEFAULT_PAGE_HEIGHT)
    anchor_left = float(bbox[0])
    anchor_right = float(bbox[2])
    return _LegendStripContext(
        page=page,
        page_height=page_height,
        figure_height=max(1.0, float(bbox[3]) - float(bbox[1])),
        anchor_left=anchor_left,
        anchor_right=anchor_right,
        anchor_width=max(1.0, anchor_right - anchor_left),
        max_gap=page_height * 0.08,
        max_strip_bottom=float(bbox[3]) + page_height * 0.14,
    )


def _next_legend_strip_state(
    candidate: Dict[str, Any],
    idx: int,
    context: _LegendStripContext,
    state: _LegendStripState,
) -> Optional[_LegendStripState]:
    if _block_page(candidate) != context.page:
        return None
    candidate_type = candidate.get("type")
    if candidate_type in FIGURE_FLOW_BOUNDARY_TYPES and candidate_type != FIGURE:
        return None
    if candidate_type not in FIGURE_FOLLOWING_CAPTION_TYPES | {FIGURE}:
        return None
    bbox = _bbox(candidate)
    if not bbox or not _legend_strip_bbox_attached(bbox, context, state.current_bottom):
        return None
    if candidate_type == FIGURE:
        return _with_visual_legend_fragment(idx, bbox, context, state)
    return _with_text_legend_fragment(candidate, idx, bbox, context, state)


def _legend_strip_bbox_attached(
    bbox: BBox, context: _LegendStripContext, current_bottom: float
) -> bool:
    gap = float(bbox[1]) - current_bottom
    if not -40.0 <= gap <= context.max_gap:
        return False
    if float(bbox[3]) > context.max_strip_bottom:
        return False
    candidate_left = float(bbox[0])
    candidate_right = float(bbox[2])
    candidate_width = max(1.0, candidate_right - candidate_left)
    center_x = (candidate_left + candidate_right) / 2.0
    overlap = min(context.anchor_right, candidate_right) - max(context.anchor_left, candidate_left)
    return (
        context.anchor_left - context.anchor_width * 0.08
        <= center_x
        <= context.anchor_right + context.anchor_width * 0.08
        or overlap >= min(context.anchor_width, candidate_width) * 0.35
    )


def _with_visual_legend_fragment(
    idx: int, bbox: BBox, context: _LegendStripContext, state: _LegendStripState
) -> Optional[_LegendStripState]:
    candidate_height = max(1.0, float(bbox[3]) - float(bbox[1]))
    if candidate_height > context.figure_height * 0.18:
        return None
    return _LegendStripState(
        out=[*state.out, idx],
        current_bottom=max(state.current_bottom, float(bbox[3])),
        has_visual_fragment=True,
        has_text_fragment=state.has_text_fragment,
    total_text_chars=state.total_text_chars,
        rejected=state.rejected,
    )


def _with_text_legend_fragment(
    candidate: Dict[str, Any],
    idx: int,
    bbox: BBox,
    context: _LegendStripContext,
    state: _LegendStripState,
) -> Optional[_LegendStripState]:
    if not _is_compact_visual_legend_text(candidate, bbox, context.anchor_width, context.page_height):
        return _LegendStripState(out=[], current_bottom=state.current_bottom, rejected=True)
    text_chars = state.total_text_chars + len(str(candidate.get("text", "")).strip())
    if text_chars > 160:
        return _LegendStripState(out=[], current_bottom=state.current_bottom, rejected=True)
    return _LegendStripState(
        out=[*state.out, idx],
        current_bottom=max(state.current_bottom, float(bbox[3])),
        has_visual_fragment=state.has_visual_fragment,
        has_text_fragment=True,
        total_text_chars=text_chars,
        rejected=state.rejected,
    )


def _accepted_legend_strip_indices(state: _LegendStripState) -> List[int]:
    if len(state.out) < 2 or not state.has_text_fragment:
        return []
    if not state.has_visual_fragment and len(state.out) < 3:
        return []
    return state.out


def _is_compact_visual_legend_text(
    candidate: Dict[str, Any],
    bbox: BBox,
    anchor_width: float,
    page_height: float,
) -> bool:
    text = str(candidate.get("text", "")).strip()
    if not text:
        return False
    compact_len = len(text.replace(" ", ""))
    if compact_len > 80:
        return False
    height = max(1.0, float(bbox[3]) - float(bbox[1]))
    width = max(1.0, float(bbox[2]) - float(bbox[0]))
    if height > page_height * 0.055:
        return False
    return not (compact_len > 45 and width > anchor_width * 0.65)


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
    geometry = _figure_pair_geometry(blocks, left, lbb, rbb)
    union = union_bbox([lbb, rbb])
    side_by_side = (
        _is_side_by_side_fragment(lbb, rbb, geometry)
        and bool(union)
        and _has_following_caption_for_figure_pair(blocks, left_idx, union)
    )
    left_attrs = left.get("attrs") or {}
    below_fragment = _is_below_figure_fragment(geometry, bool(left_attrs.get("captions")))
    return side_by_side or below_fragment


def _figure_pair_geometry(
    blocks: List[Dict[str, Any]], left: Dict[str, Any], left_bbox: BBox, right_bbox: BBox
) -> _FigurePairGeometry:
    page = _block_page(left)
    page_width = _page_coord_widths(blocks).get(page, _DEFAULT_PAGE_HEIGHT)
    page_height = _page_coord_heights(blocks).get(page, _DEFAULT_PAGE_HEIGHT)
    left_width = max(1.0, float(left_bbox[2]) - float(left_bbox[0]))
    left_height = max(1.0, float(left_bbox[3]) - float(left_bbox[1]))
    right_width = max(1.0, float(right_bbox[2]) - float(right_bbox[0]))
    right_height = max(1.0, float(right_bbox[3]) - float(right_bbox[1]))
    return _FigurePairGeometry(
        page_width=page_width,
        page_height=page_height,
        left_width=left_width,
        left_height=left_height,
        right_width=right_width,
        right_height=right_height,
        vertical_overlap=min(float(left_bbox[3]), float(right_bbox[3]))
        - max(float(left_bbox[1]), float(right_bbox[1])),
        horizontal_overlap=min(float(left_bbox[2]), float(right_bbox[2]))
        - max(float(left_bbox[0]), float(right_bbox[0])),
        horizontal_gap=float(right_bbox[0]) - float(left_bbox[2]),
        vertical_gap=float(right_bbox[1]) - float(left_bbox[3]),
    )


def _is_side_by_side_fragment(
    left_bbox: BBox, right_bbox: BBox, geometry: _FigurePairGeometry
) -> bool:
    return (
        geometry.vertical_overlap >= min(geometry.left_height, geometry.right_height) * 0.40
        and -25.0 <= geometry.horizontal_gap <= geometry.page_width * 0.08
        and abs(float(left_bbox[1]) - float(right_bbox[1])) <= geometry.page_height * 0.10
        and abs(float(left_bbox[3]) - float(right_bbox[3])) <= geometry.page_height * 0.12
    )


def _is_below_figure_fragment(
    geometry: _FigurePairGeometry, left_has_caption: bool
) -> bool:
    small_relative_to_left = geometry.right_height <= geometry.left_height * 0.35
    return (
        geometry.horizontal_overlap >= min(geometry.left_width, geometry.right_width) * 0.40
        and -15.0 <= geometry.vertical_gap <= geometry.page_height * 0.12
        and (
            geometry.right_height <= geometry.page_height * 0.08
            or (left_has_caption and small_relative_to_left)
        )
    )


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
    if previous_text.endswith(("。", "！", "？", ".", "）")) and previous.get("type") != HEADING:
        return False
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
