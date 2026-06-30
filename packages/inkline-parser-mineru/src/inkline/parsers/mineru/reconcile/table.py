"""Table continuation reconciliation. Detects and merges table continuation blocks (empty or partial MinerU table output) into the preceding table block, propagating source pages and continuation metadata."""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..extraction.text import normalize_ws
from ..normalize.builders import _table_title_cell_alignments, union_bbox
from ..schema.block_types import FOOTNOTE, PARAGRAPH, TABLE
from .block_access import block_bbox as _bbox
from .block_access import block_page as _block_page
from .constants import _DEFAULT_PAGE_HEIGHT, _NEAR_PAGE_TOP_RATIO
from .layout_helpers import _page_coord_heights

_TABLE_NEAR_PAGE_BOTTOM_RATIO = 0.72
_TABLE_PAGE_BOTTOM_MARKER_RATIO = 0.74

__all__ = ["reconcile_table_continuations"]


def _is_table_continuation_marker(text: str) -> bool:
    t = normalize_ws(text or "").strip()
    t = t.strip("()（）[]【】")
    return t in {"接上页", "接下页", "续表", "续上表"}


def _html_table_inner(html: str) -> str:
    text = html or ""
    start = re.search(r"<table[^>]*>", text, flags=re.I)
    end = re.search(r"</table>\s*$", text, flags=re.I)
    if start and end:
        return text[start.end() : end.start()]
    return text


def _table_column_count(html: str) -> int:
    first_row = re.search(r"<tr[^>]*>(.*?)</tr>", html or "", flags=re.I | re.S)
    if not first_row:
        return 1
    cells = re.findall(r"<t[dh]\b([^>]*)>", first_row.group(1), flags=re.I)
    count = 0
    for attrs in cells:
        colspan = re.search(r'colspan=["\']?(\d+)', attrs or "", flags=re.I)
        count += int(colspan.group(1)) if colspan else 1
    return max(1, count)


def _prepend_table_header_row(html: str, header: str) -> str:
    if not html or not header:
        return html
    escaped = html_lib.escape(header, quote=False)
    if escaped in html[:300] or header in html[:300]:
        return html
    col_count = _table_column_count(html)
    header_row = f'<tr><td colspan="{col_count}">{escaped}</td></tr>'
    return re.sub(r"(<table[^>]*>)", r"\1" + header_row, html, count=1, flags=re.I)


def _strip_continuation_header_rows(html: str) -> str:
    def replace_row(match: re.Match[str]) -> str:
        row = match.group(0)
        text = re.sub(r"<[^>]+>", "", row)
        return "" if _is_table_continuation_marker(text) else row

    return re.sub(r"<tr[^>]*>.*?</tr>", replace_row, html or "", flags=re.I | re.S)


def _merge_table_html(left_html: str, right_html: str) -> str:
    left_inner = _html_table_inner(left_html)
    right_inner = _html_table_inner(_strip_continuation_header_rows(right_html))
    if not left_inner:
        return right_html
    if not right_inner:
        return left_html
    return f"<table>{left_inner}{right_inner}</table>"


def _table_caption(block: Dict[str, Any]) -> str:
    attrs = block.get("attrs") or {}
    return normalize_ws(str(attrs.get("caption") or block.get("text") or ""))


@dataclass(frozen=True)
class _TableContinuationMatch:
    right_idx: int
    marker_idxs: List[int]
    skipped_footnote_idxs: List[int]


@dataclass(frozen=True)
class _TableMergeContext:
    left: Dict[str, Any]
    right: Dict[str, Any]
    left_page: int
    right_page: int
    left_bbox: List[Any]
    right_bbox: List[Any]
    left_attrs: Dict[str, Any]
    right_attrs: Dict[str, Any]
    match: _TableContinuationMatch


@dataclass(frozen=True)
class _TableContinuationDetector:
    """Detect adjacent-page table continuations using layout and printer labels."""

    page_heights: Dict[int, float]

    def match(
        self, blocks: List[Dict[str, Any]], left_idx: int
    ) -> Optional[_TableContinuationMatch]:
        left = blocks[left_idx]
        left_page = _block_page(left)
        left_bbox = _bbox(left)
        if left.get("type") != TABLE or left_page is None or not left_bbox:
            return None
        if not self._is_table_near_page_bottom(left, left_page, left_bbox):
            return None
        candidate = self._next_table_candidate(blocks, left_idx + 1, left_page)
        if not candidate:
            return None
        right = blocks[candidate.right_idx]
        right_page = _block_page(right)
        right_bbox = _bbox(right)
        if right_page is None or right_page != left_page + 1 or not right_bbox:
            return None
        if not self._is_table_near_page_top(right_page, right_bbox):
            return None
        right_caption = _table_caption(right)
        has_continuation_marker = bool(candidate.marker_idxs) or _is_table_continuation_marker(
            right_caption
        )
        return candidate if has_continuation_marker else None

    def _is_table_near_page_bottom(
        self, left: Dict[str, Any], page: int, bbox: List[float]
    ) -> bool:
        page_height = self.page_heights.get(page, _DEFAULT_PAGE_HEIGHT)
        return float(bbox[3]) >= page_height * _TABLE_NEAR_PAGE_BOTTOM_RATIO

    def _is_table_near_page_top(self, page: int, bbox: List[float]) -> bool:
        return (
            float(bbox[1])
            <= self.page_heights.get(page, _DEFAULT_PAGE_HEIGHT) * _NEAR_PAGE_TOP_RATIO
        )

    def _is_page_bottom_marker(self, block: Dict[str, Any]) -> bool:
        if block.get("type") != PARAGRAPH or not _is_table_continuation_marker(
            str(block.get("text", ""))
        ):
            return False
        page = _block_page(block)
        bbox = _bbox(block)
        if page is None or not bbox:
            return False
        page_height = self.page_heights.get(page, _DEFAULT_PAGE_HEIGHT)
        return float(bbox[1]) >= page_height * _TABLE_PAGE_BOTTOM_MARKER_RATIO

    def _next_table_candidate(
        self, blocks: List[Dict[str, Any]], start_idx: int, left_page: int
    ) -> Optional[_TableContinuationMatch]:
        marker_idxs: List[int] = []
        skipped_footnote_idxs: List[int] = []
        j = start_idx
        while j < len(blocks):
            b = blocks[j]
            page = _block_page(b)
            if page is not None and page > left_page + 1:
                return None
            if self._is_page_bottom_marker(b):
                marker_idxs.append(j)
                j += 1
                continue
            if b.get("type") == FOOTNOTE:
                skipped_footnote_idxs.append(j)
                j += 1
                continue
            if b.get("type") == TABLE:
                return _TableContinuationMatch(j, marker_idxs, skipped_footnote_idxs)
            return None
        return None


def reconcile_table_continuations(blocks: List[Dict[str, Any]]) -> None:
    """Merge tables split across adjacent pages and drop visible continuation labels.

    The signal is layout first: a table near a page bottom, an optional short
    page-bottom continuation marker, optional footnotes, then a table at the top
    of the following page. Text is used only to recognize the printer's
    continuation label, not the table topic.
    """
    detector = _TableContinuationDetector(page_heights=_page_coord_heights(blocks))
    i = 0
    while i < len(blocks):
        match = detector.match(blocks, i)
        context = _table_merge_context(blocks, i, match)
        if context is None:
            i += 1
            continue
        _merge_table_attrs(blocks, context)
        _merge_table_source(context)
        _delete_merged_table_blocks(blocks, context.match)
        i += 1


def _table_merge_context(
    blocks: List[Dict[str, Any]],
    left_idx: int,
    match: Optional[_TableContinuationMatch],
) -> Optional[_TableMergeContext]:
    if match is None:
        return None
    left = blocks[left_idx]
    right = blocks[match.right_idx]
    left_page = _block_page(left)
    right_page = _block_page(right)
    left_bbox = _bbox(left)
    right_bbox = _bbox(right)
    if left_page is None or right_page is None or not left_bbox or not right_bbox:
        return None
    return _TableMergeContext(
        left=left,
        right=right,
        left_page=left_page,
        right_page=right_page,
        left_bbox=left_bbox,
        right_bbox=right_bbox,
        left_attrs=left.setdefault("attrs", {}),
        right_attrs=right.get("attrs") or {},
        match=match,
    )


def _merge_table_attrs(blocks: List[Dict[str, Any]], context: _TableMergeContext) -> None:
    _promote_left_table_header(context)
    context.left_attrs["html"] = _merge_table_html(
        str(context.left_attrs.get("html") or ""), str(context.right_attrs.get("html") or "")
    )
    _refresh_table_cell_alignments(context.left_attrs)
    context.left_attrs["footnotes"] = _merged_table_footnotes(context)
    context.left_attrs["table_notes"] = _merged_table_notes(context)
    context.left_attrs["continued"] = True
    context.left_attrs["continuation_block_ids"] = [context.right.get("block_id")]
    context.left_attrs["continuation_marker_block_ids"] = _marker_block_ids(
        blocks, context.match.marker_idxs
    )
    if context.right_attrs.get("image_path"):
        context.left_attrs["continuation_image_paths"] = [context.right_attrs["image_path"]]


def _promote_left_table_header(context: _TableMergeContext) -> None:
    text = context.left.get("text")
    if not text or _is_table_continuation_marker(str(text)):
        return
    context.left_attrs["table_header"] = text
    context.left_attrs["html"] = _prepend_table_header_row(
        str(context.left_attrs.get("html") or ""), str(text)
    )
    context.left["text"] = ""


def _refresh_table_cell_alignments(attrs: Dict[str, Any]) -> None:
    cell_alignments = _table_title_cell_alignments(str(attrs.get("html") or ""))
    if cell_alignments:
        attrs["cell_alignments"] = cell_alignments


def _merged_table_footnotes(context: _TableMergeContext) -> List[Any]:
    footnotes = list(context.left_attrs.get("footnotes") or [])
    for footnote in context.right_attrs.get("footnotes") or []:
        if footnote and footnote not in footnotes:
            footnotes.append(footnote)
    return footnotes


def _merged_table_notes(context: _TableMergeContext) -> List[Any]:
    all_notes = list(context.left_attrs.get("table_notes") or context.left_attrs.get("footnotes") or [])
    right_notes = context.right_attrs.get("table_notes") or context.right_attrs.get("footnotes") or []
    for note in right_notes:
        if note and note not in all_notes and not _is_table_continuation_marker(note):
            all_notes.append(note)
    return [note for note in all_notes if not _is_table_continuation_marker(note)]


def _marker_block_ids(blocks: List[Dict[str, Any]], marker_idxs: List[int]) -> List[Any]:
    return [blocks[idx].get("block_id") for idx in marker_idxs if blocks[idx].get("block_id")]


def _merge_table_source(context: _TableMergeContext) -> None:
    source = context.left.setdefault("source", {})
    pages = source.setdefault("pages", [source.get("page")])
    if context.right_page not in pages:
        pages.append(context.right_page)
    source["bbox"] = union_bbox([_bbox(context.left), _bbox(context.right)])
    spans = source.setdefault("spans", [])
    if not spans:
        spans.append(
            {
                "page": context.left_page,
                "bbox": context.left_bbox,
                "block_id": context.left.get("block_id"),
            }
        )
    spans.append(
        {
            "page": context.right_page,
            "bbox": context.right_bbox,
            "block_id": context.right.get("block_id"),
        }
    )


def _delete_merged_table_blocks(
    blocks: List[Dict[str, Any]], match: _TableContinuationMatch
) -> None:
    remove_idxs = sorted([match.right_idx, *match.marker_idxs], reverse=True)
    for idx in remove_idxs:
        del blocks[idx]
