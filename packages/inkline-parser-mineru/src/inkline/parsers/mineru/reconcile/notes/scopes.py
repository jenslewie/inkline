"""Note scope inference and endnote section strategy. Infers chapter-level scopes from content headings, detects note section boundaries, normalizes scope keys (Chinese/roman numerals), and collects endnote candidates. Contains _EndnoteSectionStrategy, _NoteContext, and the scope inference pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Protocol

from ...extraction.text import normalize_note_marker, normalize_ws
from ...schema.block_types import HEADING, LIST_ITEM, PARAGRAPH
from ...schema.models import CanonicalBlock
from ...schema.patterns import PART_RE
from ..block_access import block_id as _block_id
from ..notes.keys import chinese_to_int as _chinese_to_int
from ..notes.keys import leading_note_marker as _com_leading_note_marker

CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百\d]+[章节]|[IVXLCDMivxlcdm]+|\d{1,2})[\s.．、:\n：]+"
)
NOTE_SUBSECTION_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百\d]+[章节]|[IVXLCDMivxlcdm]+|\d{1,2})\s+[“”\"'‘’]*[\u4e00-\u9fff]"
)


@dataclass(frozen=True)
class _NoteCandidate:
    block_id: str
    marker: Optional[str]
    strategy: str
    confidence: str
    page: Optional[int] = None
    scope_key: Optional[str] = None
    block_index: int = -1

    @property
    def note_id(self) -> str:
        return f"note_{self.block_id}"


class _NoteResolutionStrategy(Protocol):
    name: str

    def collect(
        self, blocks: List[CanonicalBlock], context: "_NoteContext"
    ) -> List[_NoteCandidate]: ...

    def resolve(
        self,
        ref_block: CanonicalBlock,
        ref: Dict[str, Any],
        candidates: List[_NoteCandidate],
        context: "_NoteContext",
    ) -> Optional[_NoteCandidate]: ...


class _NoteContext:
    def __init__(self, blocks: List[CanonicalBlock]) -> None:
        self.block_pages = {_block_id(b): _pages_for_block(b) for b in blocks if _block_id(b)}
        self.block_scopes = _infer_block_scopes(blocks)

    def pages_for(self, block: CanonicalBlock) -> List[int]:
        return self.block_pages.get(_block_id(block), _pages_for_block(block))

    def scope_for(self, block: CanonicalBlock) -> Optional[str]:
        return self.block_scopes.get(_block_id(block))


class _NoteSectionState:
    def __init__(self) -> None:
        self.in_section: bool = False
        self.current_scope: Optional[str] = None
        self.last_content_scope: Optional[str] = None
        self.section_start: Optional[int] = None

    def enter_section(self, scope: Optional[str], index: int) -> None:
        self.in_section = True
        self.current_scope = scope
        self.section_start = index

    def exit_section(self, last_scope: str) -> None:
        self.last_content_scope = last_scope
        self.in_section = False
        self.current_scope = last_scope
        self.section_start = None


class _EndnoteSectionStrategy:
    def __init__(self, name: str, scope_required: bool) -> None:
        self.name = name
        self.scope_required = scope_required

    def collect(self, blocks: List[CanonicalBlock], context: _NoteContext) -> List[_NoteCandidate]:
        out: List[_NoteCandidate] = []
        state = _NoteSectionState()
        for i, block in enumerate(blocks):
            text = normalize_ws(block.get("text", ""))
            typ = block.get("type")
            if typ == HEADING and _is_note_section_heading(block, blocks, i):
                state.enter_section(state.last_content_scope, i)
                continue

            if state.in_section:
                continued = self._handle_note_section_block(block, i, text, typ, blocks, state, out)
                if continued:
                    continue
            elif typ == HEADING and _looks_like_content_heading(block):
                state.last_content_scope = _normalize_scope(text)
        return out

    def _handle_note_section_block(
        self,
        block: CanonicalBlock,
        i: int,
        text: str,
        typ: str,
        blocks: List[CanonicalBlock],
        state: _NoteSectionState,
        out: List[_NoteCandidate],
    ) -> bool:
        if (
            typ == HEADING
            and _looks_like_note_subsection(text, state.section_start, i)
            and _heading_starts_note_subsection(blocks, i)
        ):
            new_scope = _normalize_scope(text)
            _reassign_preheading_reset_candidates(out, new_scope, state.current_scope, i)
            state.current_scope = new_scope
            return True
        if typ == HEADING and _looks_like_content_heading(block):
            if _heading_continues_note_section(blocks, i):
                state.current_scope = None
                return True
            state.exit_section(_normalize_scope(text))
            return True
        if (
            typ in {LIST_ITEM, PARAGRAPH}
            and _looks_like_note_subsection(text, state.section_start, i)
            and _block_starts_note_subsection(blocks, i)
        ):
            state.current_scope = _normalize_scope(text)
            return True
        marker = _leading_note_marker(text)
        if marker:
            bid = _block_id(block)
            if bid:
                out.append(
                    _NoteCandidate(
                        block_id=bid,
                        marker=marker,
                        scope_key=state.current_scope if self.scope_required else None,
                        strategy=self.name,
                        confidence="medium",
                        block_index=i,
                    )
                )
            return True
        if typ in {LIST_ITEM, PARAGRAPH} and _looks_like_note_subsection(
            text, state.section_start, i
        ):
            state.current_scope = _normalize_scope(text)
            return True
        return False

    def resolve(
        self,
        ref_block: CanonicalBlock,
        ref: Dict[str, Any],
        candidates: List[_NoteCandidate],
        context: _NoteContext,
    ) -> Optional[_NoteCandidate]:
        marker = normalize_note_marker(ref.get("marker", ""))
        matches = [c for c in candidates if c.strategy == self.name and c.marker == marker]
        if self.scope_required:
            scope = context.scope_for(ref_block)
            scoped = [c for c in matches if c.scope_key and c.scope_key == scope]
            if len(scoped) == 1:
                return scoped[0]
            return None
        if len(matches) == 1:
            return matches[0]
        return None


def _leading_note_marker(text: str) -> Optional[str]:
    return _com_leading_note_marker(text, include_superscript=True)


def _pages_for_block(block: CanonicalBlock) -> List[int]:
    source = block.get("source") or {}
    pages = source.get("pages")
    if isinstance(pages, list):
        return [int(p) for p in pages if isinstance(p, int)]
    page = source.get("page")
    return [int(page)] if isinstance(page, int) else []


def _is_note_section_heading(
    block: CanonicalBlock, blocks: List[CanonicalBlock], index: int
) -> bool:
    if block.get("type") != HEADING:
        return False
    text = normalize_ws(block.get("text", ""))
    first_line = text.split("\n", 1)[0].strip()
    if len(first_line) > 20 or not first_line:
        return False
    if CHAPTER_HEADING_RE.match(first_line) or PART_RE.match(first_line):
        return False
    found_note_marker = False
    for j in range(index + 1, min(index + 8, len(blocks))):
        nxt = blocks[j]
        nxt_type = nxt.get("type")
        if nxt_type == HEADING:
            nxt_text = normalize_ws(nxt.get("text", ""))
            return _looks_like_note_subsection(
                nxt_text, None, j
            ) and _heading_starts_note_subsection(blocks, j)
        if nxt_type == LIST_ITEM and _leading_note_marker(nxt.get("text", "")):
            if found_note_marker:
                return True
            found_note_marker = True
    return False


def _looks_like_note_subsection(
    text: str, section_start_index: Optional[int], block_index: int
) -> bool:
    text = normalize_ws(text)
    if not text or len(text) > 80:
        return False
    if _ends_like_note_sentence(text):
        return False
    if section_start_index is not None and block_index == section_start_index + 1:
        return not bool(_leading_note_marker(text)) or bool(NOTE_SUBSECTION_RE.match(text))
    return bool(NOTE_SUBSECTION_RE.match(text))


def _heading_starts_note_subsection(blocks: List[CanonicalBlock], index: int) -> bool:
    skipped_continuations = 0
    for nxt in blocks[index + 1 : min(index + 8, len(blocks))]:
        typ = nxt.get("type")
        if typ == HEADING:
            return False
        if typ in {LIST_ITEM, PARAGRAPH}:
            text = normalize_ws(nxt.get("text", ""))
            if not text:
                continue
            if _leading_note_marker(text) is not None:
                return True
            skipped_continuations += 1
            if skipped_continuations > 2:
                return False
    return False


def _heading_continues_note_section(blocks: List[CanonicalBlock], index: int) -> bool:
    skipped_continuations = 0
    for j in range(index + 1, min(index + 12, len(blocks))):
        nxt = blocks[j]
        typ = nxt.get("type")
        text = normalize_ws(nxt.get("text", ""))
        if typ in {LIST_ITEM, PARAGRAPH}:
            if not text:
                continue
            if _leading_note_marker(text) is not None:
                return True
            skipped_continuations += 1
            if skipped_continuations > 2:
                return False
        if typ == HEADING:
            return _looks_like_note_subsection(text, None, j) and _heading_starts_note_subsection(
                blocks, j
            )
    return False


def _block_starts_note_subsection(blocks: List[CanonicalBlock], index: int) -> bool:
    for nxt in blocks[index + 1 : min(index + 8, len(blocks))]:
        typ = nxt.get("type")
        if typ == HEADING:
            return False
        if typ not in {LIST_ITEM, PARAGRAPH}:
            continue
        text = normalize_ws(nxt.get("text", ""))
        if not text:
            continue
        return _leading_note_marker(text) is not None
    return False


def _reassign_preheading_reset_candidates(
    candidates: List[_NoteCandidate],
    new_scope: str,
    previous_scope: Optional[str],
    heading_index: int,
) -> None:
    if not previous_scope:
        return
    tail: List[_NoteCandidate] = []
    for candidate in reversed(candidates):
        if candidate.scope_key != previous_scope:
            break
        if candidate.block_index < 0 or heading_index - candidate.block_index > 6:
            break
        try:
            marker = int(candidate.marker or "")
        except ValueError:
            break
        if marker > 5:
            break
        tail.append(candidate)
    tail.reverse()
    if len(tail) < 2:
        return
    if [int(candidate.marker or "0") for candidate in tail] != list(range(1, len(tail) + 1)):
        return
    for candidate in tail:
        index = candidates.index(candidate)
        candidates[index] = replace(candidate, scope_key=new_scope)


def _ends_like_note_sentence(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped and stripped[-1] in "。！？；.!?;")


def _normalize_scope(text: str) -> str:
    text = normalize_ws(text)
    text = re.sub(r"\s+", " ", text)
    text = _normalize_scope_prefix(text)
    text = re.sub(r"[“”\"'‘’]", "", text)
    return text.strip()


def _normalize_scope_prefix(text: str) -> str:
    text = text.strip()
    m = re.match(r"^第([一二三四五六七八九十百\d]+)[章节]\s*(.+)$", text)
    if m:
        value = _chinese_or_digit_to_int(m.group(1))
        if value is not None:
            return f"{value} {_strip_scope_separator(m.group(2))}"
    m = re.match(r"^(\d{1,3})[\s.．、:：]+(.+)$", text)
    if m:
        return f"{int(m.group(1))} {_strip_scope_separator(m.group(2))}"
    m = re.match(r"^\s*([IVXLCDMivxlcdm]+)\s+(.+)$", text)
    if m:
        value = _roman_to_int(m.group(1))
        if value is not None:
            return f"{value} {_strip_scope_separator(m.group(2))}"
    return text


def _strip_scope_separator(text: str) -> str:
    return text.strip().lstrip(".．、:：").strip()


def _chinese_or_digit_to_int(text: str) -> Optional[int]:
    if text.isdigit():
        return int(text)
    return _chinese_to_int(text)


def _roman_to_int(text: str) -> Optional[int]:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(text.upper()):
        value = values.get(ch)
        if value is None:
            return None
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total if total > 0 else None


def _infer_block_scopes(blocks: List[CanonicalBlock]) -> Dict[str, str]:
    scopes: Dict[str, str] = {}
    current_scope: Optional[str] = None
    in_note_section = False
    for i, block in enumerate(blocks):
        text = normalize_ws(block.get("text", ""))
        typ = block.get("type")
        if typ == HEADING and _is_note_section_heading(block, blocks, i):
            in_note_section = True
            continue
        if typ == HEADING and _looks_like_content_heading(block):
            current_scope = _normalize_scope(text)
            in_note_section = False
        bid = _block_id(block)
        if bid and current_scope and not in_note_section:
            scopes[bid] = current_scope
    return scopes


def _looks_like_content_heading(block: CanonicalBlock) -> bool:
    attrs = block.get("attrs") or {}
    text = normalize_ws(block.get("text", ""))
    if not text:
        return False
    if attrs.get("role") == "toc_heading":
        return False
    if attrs.get("role") in {"chapter_title", "part_title"}:
        return True
    if PART_RE.match(text):
        return True
    if CHAPTER_HEADING_RE.match(text):
        return True
    return block.get("type") == HEADING and len(text) <= 80
