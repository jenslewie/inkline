"""Table continuation reconciliation. Detects and merges table continuation blocks (empty or partial MinerU table output) into the preceding table block, propagating source pages and continuation metadata."""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..normalize.builders import union_bbox
from ..extraction.text import normalize_ws
from .constants import _DEFAULT_PAGE_HEIGHT, _NEAR_PAGE_TOP_RATIO
from .block_access import block_bbox as _bbox, block_page as _block_page
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
class _TableContinuationDetector:
    """Detect adjacent-page table continuations using layout and printer labels."""

    page_heights: Dict[int, float]

    def match(self, blocks: List[Dict[str, Any]], left_idx: int) -> Optional[_TableContinuationMatch]:
        left = blocks[left_idx]
        left_page = _block_page(left)
        left_bbox = _bbox(left)
        if left.get("type") != "table" or left_page is None or not left_bbox:
            return None
        if not self._is_table_near_page_bottom(left, left_page, left_bbox):
            return None
        candidate = self._next_table_candidate(blocks, left_idx + 1, left_page)
        if not candidate:
            return None
        right = blocks[candidate.right_idx]
        right_page = _block_page(right)
        right_bbox = _bbox(right)
        if right_page != left_page + 1 or not right_bbox:
            return None
        if not self._is_table_near_page_top(right_page, right_bbox):
            return None
        right_caption = _table_caption(right)
        has_continuation_marker = bool(candidate.marker_idxs) or _is_table_continuation_marker(right_caption)
        return candidate if has_continuation_marker else None

    def _is_table_near_page_bottom(self, left: Dict[str, Any], page: int, bbox: List[float]) -> bool:
        page_height = self.page_heights.get(page, _DEFAULT_PAGE_HEIGHT)
        return float(bbox[3]) >= page_height * _TABLE_NEAR_PAGE_BOTTOM_RATIO

    def _is_table_near_page_top(self, page: int, bbox: List[float]) -> bool:
        return float(bbox[1]) <= self.page_heights.get(page, _DEFAULT_PAGE_HEIGHT) * _NEAR_PAGE_TOP_RATIO

    def _is_page_bottom_marker(self, block: Dict[str, Any]) -> bool:
        if block.get("type") != "paragraph" or not _is_table_continuation_marker(str(block.get("text", ""))):
            return False
        page = _block_page(block)
        bbox = _bbox(block)
        if page is None or not bbox:
            return False
        page_height = self.page_heights.get(page, _DEFAULT_PAGE_HEIGHT)
        return float(bbox[1]) >= page_height * _TABLE_PAGE_BOTTOM_MARKER_RATIO

    def _next_table_candidate(self, blocks: List[Dict[str, Any]], start_idx: int, left_page: int) -> Optional[_TableContinuationMatch]:
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
            if b.get("type") == "footnote":
                skipped_footnote_idxs.append(j)
                j += 1
                continue
            if b.get("type") == "table":
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
        left = blocks[i]
        left_page = _block_page(left)
        left_bbox = _bbox(left)
        match = detector.match(blocks, i)
        if not match or left_page is None or not left_bbox:
            i += 1
            continue
        right_idx = match.right_idx
        marker_idxs = match.marker_idxs
        skipped_footnote_idxs = match.skipped_footnote_idxs
        right = blocks[right_idx]
        right_page = _block_page(right)
        right_bbox = _bbox(right)
        if right_page is None or not right_bbox:
            i += 1
            continue

        left_attrs = left.setdefault("attrs", {})
        right_attrs = right.get("attrs") or {}
        if left.get("text") and not _is_table_continuation_marker(str(left.get("text", ""))):
            left_attrs["table_header"] = left.get("text")
            left_attrs["html"] = _prepend_table_header_row(str(left_attrs.get("html") or ""), str(left.get("text")))
            left["text"] = ""
        left_attrs["html"] = _merge_table_html(str(left_attrs.get("html") or ""), str(right_attrs.get("html") or ""))
        footnotes = list(left_attrs.get("footnotes") or [])
        for footnote in right_attrs.get("footnotes") or []:
            if footnote and footnote not in footnotes:
                footnotes.append(footnote)
        for idx in skipped_footnote_idxs:
            footnote = blocks[idx]
            text = normalize_ws(str(footnote.get("text", "")))
            if text and text not in footnotes:
                footnotes.append(text)
        left_attrs["footnotes"] = footnotes
        left_attrs["continued"] = True
        left_attrs["continuation_block_ids"] = [right.get("block_id")]
        left_attrs["continuation_marker_block_ids"] = [
            blocks[idx].get("block_id") for idx in marker_idxs if blocks[idx].get("block_id")
        ]
        if right_attrs.get("image_path"):
            left_attrs["continuation_image_paths"] = [right_attrs["image_path"]]

        source = left.setdefault("source", {})
        pages = source.setdefault("pages", [source.get("page")])
        if right_page not in pages:
            pages.append(right_page)
        source["bbox"] = union_bbox([_bbox(left), _bbox(right)])
        spans = source.setdefault("spans", [])
        if not spans:
            spans.append({"page": left_page, "bbox": left_bbox, "block_id": left.get("block_id")})
        spans.append({"page": right_page, "bbox": right_bbox, "block_id": right.get("block_id")})

        remove_idxs = sorted([right_idx, *marker_idxs, *skipped_footnote_idxs], reverse=True)
        for idx in remove_idxs:
            del blocks[idx]
        i += 1
