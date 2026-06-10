"""Footnote promotion. Handles splitting MinerU page-footnote blocks that contain multiple hard lines, promoting page-bottom reference-list items to footnotes, and promoting cross-page footnote continuation paragraphs that MinerU mislabeled as regular text."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List, Optional

from ...schema.models import BBox
from ...extraction.text import normalize_ws
from ..constants import _DEFAULT_PAGE_HEIGHT, _NEAR_PAGE_BOTTOM_RATIO
from ..block_access import block_bbox as _bbox, block_page as _block_page
from ..notes.keys import leading_note_marker as _leading_note_marker

_PAGE_HEIGHT_HINT_BBOX_W = 650
_PAGE_HEIGHT_HINT_BBOX_H = 750
_PAGE_HEIGHT_HINT_SMALL = 680.0
_PAGE_BOTTOM_REF_Y0_RATIO = 0.52
_REFERENCE_LIST_MIN_RUN = 2


def split_page_footnote_blocks(blocks: List[Dict[str, Any]]) -> None:
    definition_counts = _page_footnote_definition_counts(blocks)
    ref_markers = _page_note_ref_markers_by_page(blocks)
    deficits = {
        page: max(0, len(ref_markers.get(page, [])) - count)
        for page, count in definition_counts.items()
    }
    i = 0
    while i < len(blocks):
        blk = blocks[i]
        if not _is_splittable_page_footnote(blk):
            i += 1
            continue
        page = _block_page(blk)
        deficit = deficits.get(page, 0) if page is not None else 0
        if deficit <= 0:
            i += 1
            continue
        parts = _split_footnote_text(
            str(blk.get("text", "")),
            ref_markers.get(page, []) if page is not None else [],
            deficit + 1,
        )
        if len(parts) <= 1:
            i += 1
            continue
        split_blocks = _make_split_footnotes(blk, parts)
        blocks[i:i + 1] = split_blocks
        if page is not None:
            deficits[page] = max(0, deficit - (len(parts) - 1))
        i += len(split_blocks)


def recover_unmarked_page_footnote_markers(blocks: List[Dict[str, Any]]) -> None:
    """Align unmarked MinerU footnotes with same-page inline-equation markers."""

    footnotes_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for block in blocks:
        attrs = block.get("attrs") or {}
        page = _block_page(block)
        if block.get("type") == "footnote" and attrs.get("role") == "page_footnote" and page is not None:
            footnotes_by_page.setdefault(page, []).append(block)

    for page, page_footnotes in footnotes_by_page.items():
        page_footnotes.sort(key=_footnote_sort_key)
        markers = _middle_page_inline_markers(page_footnotes) or _page_note_ref_markers(blocks, page)
        if len(markers) != len(page_footnotes):
            continue
        explicit = [
            normalize_ws(str((block.get("attrs") or {}).get("note_marker") or ""))
            or _leading_note_marker(block.get("text", ""))
            for block in page_footnotes
        ]
        if any(expected and expected != actual for expected, actual in zip(explicit, markers)):
            continue
        for block, expected, marker in zip(page_footnotes, explicit, markers):
            if expected:
                continue
            attrs = block.setdefault("attrs", {})
            attrs["note_marker"] = marker
            attrs["note_marker_source"] = "mineru_inline_equation_order"


def promote_page_reference_list_footnotes(blocks: List[Dict[str, Any]]) -> None:
    i = 0
    while i < len(blocks):
        run = _collect_reference_list_run(blocks, i)
        if not run:
            i += 1
            continue
        page = _block_page(blocks[run[0]])
        markers = _reference_list_markers(blocks, run, page)
        if page is not None and _is_page_bottom_reference_run(blocks, run) and _has_matching_page_refs(blocks, page, markers):
            boxes = _split_bbox_vertically(_bbox(blocks[run[0]]), len(run))
            for offset, k in enumerate(run):
                attrs = blocks[k].setdefault("attrs", {})
                blocks[k]["type"] = "footnote"
                blocks[k].setdefault("source", {})["bbox"] = boxes[offset] if offset < len(boxes) else _bbox(blocks[k])
                attrs["role"] = "page_footnote"
                attrs["promoted_from"] = attrs.get("raw_type", "list_item")
                attrs["promote_reason"] = "page_bottom_reference_list"
                marker = markers[offset] if offset < len(markers) else None
                if marker and _leading_note_marker(blocks[k].get("text", "")) is None:
                    attrs["note_marker"] = marker
                    attrs["note_marker_source"] = "reference_list_order"
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
    return (
        blk.get("type") == "footnote"
        and attrs.get("role") == "page_footnote"
        and bool(normalize_ws(str(blk.get("text", ""))))
    )


def _footnote_lines(text: str) -> List[str]:
    return [normalize_ws(line) for line in str(text or "").splitlines() if normalize_ws(line)]


def _split_footnote_text(
    text: str,
    expected_markers: List[str],
    desired_count: int,
) -> List[str]:
    marker_parts = _split_footnote_parts_at_embedded_markers(
        normalize_ws(text),
        expected_markers,
        desired_count,
    )
    if len(marker_parts) > 1:
        return marker_parts
    lines = _footnote_lines(text)
    return _split_footnote_parts(lines, min(len(lines), desired_count))


def _split_footnote_parts_at_embedded_markers(
    text: str,
    expected_markers: List[str],
    desired_count: int,
) -> List[str]:
    if desired_count <= 1 or not text or len(expected_markers) <= 1:
        return [text]
    first_marker = _leading_note_marker(text)
    if first_marker is None or first_marker not in expected_markers:
        return [text]
    marker_index = expected_markers.index(first_marker)
    following_markers = expected_markers[marker_index + 1 : marker_index + desired_count]
    boundaries: List[int] = []
    cursor = 1
    for marker in following_markers:
        boundary = _find_embedded_footnote_marker(text, marker, cursor)
        if boundary is None:
            break
        boundaries.append(boundary)
        cursor = boundary + len(marker)
    if not boundaries:
        return [text]
    cuts = [0, *boundaries, len(text)]
    return [
        normalize_ws(text[cuts[index] : cuts[index + 1]])
        for index in range(len(cuts) - 1)
        if normalize_ws(text[cuts[index] : cuts[index + 1]])
    ]


def _find_embedded_footnote_marker(text: str, marker: str, start: int) -> Optional[int]:
    marker = str(marker or "").strip()
    if not marker:
        return None
    pattern = re.compile(rf"(?<=[。！？；])\s*(?P<marker>{re.escape(marker)})(?=\s|[《“‘（(A-Za-z\u4e00-\u9fff])")
    match = pattern.search(text, start)
    return match.start("marker") if match else None


def _split_footnote_parts(lines: List[str], desired_count: int) -> List[str]:
    if desired_count <= 1:
        return ["\n".join(lines)]
    marker_boundaries = [
        index
        for index, line in enumerate(lines[1:], 1)
        if _leading_note_marker(line) is not None
    ]
    if len(marker_boundaries) >= desired_count - 1:
        boundaries = [0, *marker_boundaries[: desired_count - 1], len(lines)]
        return [
            "\n".join(lines[boundaries[index] : boundaries[index + 1]])
            for index in range(desired_count)
        ]
    if desired_count == len(lines):
        return lines
    return ["\n".join(lines)]


def _page_footnote_definition_counts(blocks: List[Dict[str, Any]]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for block in blocks:
        attrs = block.get("attrs") or {}
        page = _block_page(block)
        if block.get("type") == "footnote" and attrs.get("role") == "page_footnote" and page is not None:
            counts[page] = counts.get(page, 0) + 1
    return counts


def _page_note_ref_markers_by_page(blocks: List[Dict[str, Any]]) -> Dict[int, List[str]]:
    markers: Dict[int, List[str]] = {}
    for block in blocks:
        if block.get("type") == "footnote":
            continue
        attrs = block.get("attrs") or {}
        run_refs = [
            run
            for run in attrs.get("inline_runs") or []
            if isinstance(run, dict) and run.get("type") == "note_ref"
        ]
        refs = run_refs or attrs.get("note_refs") or []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            page = ref.get("source_page")
            if not isinstance(page, int):
                page = _block_page(block)
            if page is not None:
                marker = str(ref.get("marker") or "").strip()
                if marker:
                    markers.setdefault(page, []).append(marker)
    return markers


def _make_split_footnotes(blk: Dict[str, Any], parts: List[str]) -> List[Dict[str, Any]]:
    bbox = _bbox(blk)
    boxes = _split_bbox_vertically(bbox, len(parts))
    out: List[Dict[str, Any]] = []
    split_from = blk.get("block_id")
    for idx, part in enumerate(parts):
        item = deepcopy(blk)
        if idx > 0:
            item["block_id"] = f"{split_from}_{idx + 1}"
        item["text"] = part
        source = item.setdefault("source", {})
        source["bbox"] = boxes[idx] if idx < len(boxes) else bbox
        attrs = item.setdefault("attrs", {})
        attrs["split_from"] = split_from
        attrs["split_index"] = idx + 1
        attrs["split_count"] = len(parts)
        attrs["split_reason"] = "page_footnote_definition_gap"
        out.append(item)
    return out


def _collect_reference_list_run(blocks: List[Dict[str, Any]], start: int) -> List[int]:
    if _is_mineru_reference_list_item(blocks[start]):
        page = _block_page(blocks[start])
        bbox = _bbox(blocks[start])
        out: List[int] = []
        i = start
        while (
            i < len(blocks)
            and _is_mineru_reference_list_item(blocks[i])
            and _block_page(blocks[i]) == page
            and _bbox(blocks[i]) == bbox
        ):
            out.append(i)
            i += 1
        return out if len(out) >= _REFERENCE_LIST_MIN_RUN else []
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


def _is_mineru_reference_list_item(blk: Dict[str, Any]) -> bool:
    attrs = blk.get("attrs") or {}
    return (
        blk.get("type") == "list_item"
        and attrs.get("raw_type") == "list_item"
        and attrs.get("list_type") == "reference_list"
    )


def _reference_list_markers(
    blocks: List[Dict[str, Any]],
    run: List[int],
    page: Optional[int],
) -> List[Optional[str]]:
    explicit = [_leading_note_marker(blocks[k].get("text", "")) for k in run]
    if page is None or all(marker is not None for marker in explicit):
        return explicit
    page_refs = _page_note_ref_markers(blocks, page)
    if len(page_refs) != len(run):
        return explicit
    aligned: List[Optional[str]] = []
    for expected, actual in zip(explicit, page_refs):
        if expected is not None and expected != actual:
            return explicit
        aligned.append(expected or actual)
    return aligned


def _page_note_ref_markers(blocks: List[Dict[str, Any]], page: int) -> List[str]:
    markers: List[str] = []
    for blk in blocks:
        if _block_page(blk) != page or blk.get("type") == "footnote":
            continue
        attrs = blk.get("attrs") or {}
        run_refs = [
            run
            for run in attrs.get("inline_runs") or []
            if isinstance(run, dict) and run.get("type") == "note_ref"
        ]
        refs = run_refs or attrs.get("note_refs") or []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            marker = str(ref.get("marker", "")).strip()
            if marker:
                markers.append(marker)
    return markers


def _middle_page_inline_markers(page_footnotes: List[Dict[str, Any]]) -> List[str]:
    for block in page_footnotes:
        markers = (block.get("attrs") or {}).get("_middle_page_inline_markers")
        if isinstance(markers, list):
            return [str(marker) for marker in markers if str(marker).strip()]
    return []


def _footnote_sort_key(block: Dict[str, Any]) -> tuple[float, float, str]:
    bbox = _bbox(block) or []
    y = float(bbox[1]) if len(bbox) >= 2 else 0.0
    x = float(bbox[0]) if len(bbox) >= 1 else 0.0
    return (y, x, str(block.get("block_id") or ""))


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
