"""Footnote promotion. Handles splitting MinerU page-footnote blocks that contain multiple hard lines, promoting page-bottom reference-list items to footnotes, and promoting cross-page footnote continuation paragraphs that MinerU mislabeled as regular text."""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Optional

from ...schema.models import BBox
from ...extraction.text import normalize_ws
from ..common import _DEFAULT_PAGE_HEIGHT, _NEAR_PAGE_BOTTOM_RATIO, _bbox, _block_page, _leading_note_marker

_PAGE_HEIGHT_HINT_BBOX_W = 650
_PAGE_HEIGHT_HINT_BBOX_H = 750
_PAGE_HEIGHT_HINT_SMALL = 680.0
_PAGE_BOTTOM_REF_Y0_RATIO = 0.52
_REFERENCE_LIST_MIN_RUN = 2


def split_page_footnote_blocks(blocks: List[Dict[str, Any]]) -> None:
    i = 0
    while i < len(blocks):
        blk = blocks[i]
        if not _is_splittable_page_footnote(blk):
            i += 1
            continue
        lines = _footnote_lines(blk.get("text", ""))
        if len(lines) <= 1:
            i += 1
            continue
        split_blocks = _make_split_footnotes(blk, lines)
        blocks[i:i + 1] = split_blocks
        i += len(split_blocks)


def promote_page_reference_list_footnotes(blocks: List[Dict[str, Any]]) -> None:
    i = 0
    while i < len(blocks):
        run = _collect_reference_list_run(blocks, i)
        if not run:
            i += 1
            continue
        markers = [_leading_note_marker(blocks[k].get("text", "")) for k in run]
        page = _block_page(blocks[run[0]])
        if page is not None and _is_page_bottom_reference_run(blocks, run) and _has_matching_page_refs(blocks, page, markers):
            boxes = _split_bbox_vertically(_bbox(blocks[run[0]]), len(run))
            for offset, k in enumerate(run):
                attrs = blocks[k].setdefault("attrs", {})
                blocks[k]["type"] = "footnote"
                blocks[k].setdefault("source", {})["bbox"] = boxes[offset] if offset < len(boxes) else _bbox(blocks[k])
                attrs["role"] = "page_footnote"
                attrs["promoted_from"] = attrs.get("raw_type", "list_item")
                attrs["promote_reason"] = "page_bottom_reference_list"
        i = run[-1] + 1


def promote_cross_page_footnote_continuation_paragraphs(blocks: List[Dict[str, Any]]) -> None:
    TEXT_LIKE_TYPES = {"paragraph", "display_block", "blockquote", "list_item"}
    from .merge import _has_next_page_continuation, _has_previous_page_continuation

    i = 0
    while i < len(blocks):
        blk = blocks[i]

        if blk.get("type") not in TEXT_LIKE_TYPES:
            i += 1
            continue
        if not _has_previous_page_continuation(blk):
            i += 1
            continue
        page = _block_page(blk)
        if page is None:
            i += 1
            continue

        prev_page = page - 1
        found_prev = False
        for j in range(i - 1, -1, -1):
            prev_blk = blocks[j]
            prev_bp = _block_page(prev_blk)
            if prev_bp is not None and prev_bp < prev_page:
                break
            if prev_blk.get("type") == "footnote" and prev_bp == prev_page and _has_next_page_continuation(prev_blk):
                found_prev = True
                break

        if not found_prev:
            i += 1
            continue

        _promote_text_block_to_page_footnote(blk)
        i += 1

        while i < len(blocks):
            cur = blocks[i]
            cur_page = _block_page(cur)
            if cur_page is not None and cur_page != page:
                break
            if cur.get("type") == "footnote":
                break
            if cur.get("type") not in TEXT_LIKE_TYPES:
                break
            _promote_text_block_to_page_footnote(cur)
            i += 1


def _promote_text_block_to_page_footnote(blk: Dict[str, Any]) -> None:
    promoted_from = (blk.get("attrs") or {}).get("raw_type") or blk.get("type")
    blk["type"] = "footnote"
    attrs = blk.setdefault("attrs", {})
    attrs["role"] = "page_footnote"
    attrs["promoted_from"] = promoted_from
    attrs["promote_reason"] = "cross_page_footnote_continuation_paragraph"


def _is_splittable_page_footnote(blk: Dict[str, Any]) -> bool:
    attrs = blk.get("attrs") or {}
    return blk.get("type") == "footnote" and attrs.get("role") == "page_footnote" and "\n" in str(blk.get("text", ""))


def _footnote_lines(text: str) -> List[str]:
    return [normalize_ws(line) for line in str(text or "").splitlines() if normalize_ws(line)]


def _make_split_footnotes(blk: Dict[str, Any], lines: List[str]) -> List[Dict[str, Any]]:
    bbox = _bbox(blk)
    boxes = _split_bbox_vertically(bbox, len(lines))
    out: List[Dict[str, Any]] = []
    split_from = blk.get("block_id")
    for idx, line in enumerate(lines):
        item = deepcopy(blk)
        if idx > 0:
            item["block_id"] = f"{split_from}_{idx + 1}"
        item["text"] = line
        source = item.setdefault("source", {})
        source["bbox"] = boxes[idx] if idx < len(boxes) else bbox
        attrs = item.setdefault("attrs", {})
        attrs["split_from"] = split_from
        attrs["split_index"] = idx + 1
        attrs["split_count"] = len(lines)
        attrs["split_reason"] = "page_footnote_hard_line_break"
        out.append(item)
    return out


def _collect_reference_list_run(blocks: List[Dict[str, Any]], start: int) -> List[int]:
    if not _is_reference_list_item(blocks[start]):
        return []
    page = _block_page(blocks[start])
    bbox = _bbox(blocks[start])
    out: List[int] = []
    i = start
    while i < len(blocks) and _is_reference_list_item(blocks[i]) and _block_page(blocks[i]) == page and _bbox(blocks[i]) == bbox:
        out.append(i)
        i += 1
    return out if len(out) >= _REFERENCE_LIST_MIN_RUN else []


def _is_reference_list_item(blk: Dict[str, Any]) -> bool:
    attrs = blk.get("attrs") or {}
    return blk.get("type") == "list_item" and attrs.get("raw_type") == "list_item" and _leading_note_marker(blk.get("text", "")) is not None


def _is_page_bottom_reference_run(blocks: List[Dict[str, Any]], run: List[int]) -> bool:
    bbox = _bbox(blocks[run[0]])
    if not bbox:
        return False
    h = _page_height_hint(blocks[run[0]])
    return float(bbox[1]) >= h * _PAGE_BOTTOM_REF_Y0_RATIO and float(bbox[3]) >= h * _NEAR_PAGE_BOTTOM_RATIO


def _has_matching_page_refs(blocks: List[Dict[str, Any]], page: int, markers: List[Optional[str]]) -> bool:
    note_markers = {m for m in markers if m}
    if not note_markers:
        return False
    refs = set()
    for blk in blocks:
        if _block_page(blk) != page:
            continue
        if blk.get("type") not in {"paragraph", "display_block", "caption", "blockquote", "list_item"}:
            continue
        for ref in blk.get("attrs", {}).get("note_refs") or []:
            marker = str(ref.get("marker", "")).strip()
            if marker:
                refs.add(marker)
    return bool(refs & note_markers)


def _page_height_hint(blk: Dict[str, Any]) -> float:
    bbox = _bbox(blk)
    if not bbox:
        return _DEFAULT_PAGE_HEIGHT
    return _DEFAULT_PAGE_HEIGHT if float(bbox[2]) > _PAGE_HEIGHT_HINT_BBOX_W or float(bbox[3]) > _PAGE_HEIGHT_HINT_BBOX_H else _PAGE_HEIGHT_HINT_SMALL


def _split_bbox_vertically(bbox: Optional[BBox], count: int) -> List[Optional[BBox]]:
    if not bbox or count <= 0:
        return [bbox] * max(count, 0)
    x0, y0, x1, y1 = [float(v) for v in bbox[:4]]
    height = max(1.0, y1 - y0)
    step = height / count
    boxes: List[Optional[BBox]] = []
    for idx in range(count):
        top = y0 + step * idx
        bottom = y1 if idx == count - 1 else y0 + step * (idx + 1)
        boxes.append([x0, top, x1, bottom])
    return boxes
