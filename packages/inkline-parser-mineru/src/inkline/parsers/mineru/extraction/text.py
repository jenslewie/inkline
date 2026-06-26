"""Text extraction and normalization. Extracts text, inline runs, and note references from raw MinerU blocks. Provides normalize_ws, chinese_len, extract_list_item_text, strip_trailing_text_note, and other text utilities used across the pipeline."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from ..schema.models import NoteRef, RawBlock
from ..schema.patterns import (
    ATTR_RE,
    CHINESE_RE,
    EQUATION_NOTE_RE,
    NOTE_MARKER_RE,
    PAGE_NUM_RE,
    TRAILING_NOTE_RE,
)

_LATEX_GREEK = {
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\theta": "θ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\pi": "π",
    r"\rho": "ρ",
    r"\sigma": "σ",
    r"\tau": "τ",
    r"\phi": "φ",
    r"\chi": "χ",
    r"\psi": "ψ",
    r"\omega": "ω",
}

__all__ = [
    "block_text",
    "chinese_len",
    "extract_caption_list",
    "extract_list_item_text",
    "extract_text_and_notes",
    "extract_text_notes_and_runs",
    "merge_inline_runs",
    "normalize_note_marker",
    "normalize_toc_number",
    "normalize_ws",
    "strip_trailing_text_note",
]


def normalize_ws(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([，。；：？！、）】》])", r"\1", text)
    text = re.sub(r"([（【《])\s+", r"\1", text)
    return text.strip()


def _normalize_extracted_text(text: str) -> str:
    return normalize_ws(_collapse_mineru_prose_wraps(text))


def _collapse_mineru_prose_wraps(text: str) -> str:
    if "\n" not in text:
        return text
    lines = text.split("\n")
    out: List[str] = []
    for line in lines:
        current = line.strip()
        if not out:
            out.append(current)
            continue
        if _is_mineru_prose_wrap(out[-1], current):
            out[-1] = f"{out[-1]}{current}"
        else:
            out.append(current)
    return "\n".join(out)


def _is_mineru_prose_wrap(prev_line: str, next_line: str) -> bool:
    prev = prev_line.strip()
    nxt = next_line.strip()
    if not prev or not nxt:
        return False
    if len(re.sub(r"\s+", "", prev)) < 20 or len(re.sub(r"\s+", "", nxt)) < 20:
        return False
    if prev[-1] in "。？！；：:”’）】》":
        return False
    if re.match(r"^[0-9A-Za-z（(【《一二三四五六七八九十]+[、.．)]", nxt):
        return False
    return bool(CHINESE_RE.search(prev[-1]) and CHINESE_RE.search(nxt[0]))


def chinese_len(text: str) -> int:
    return len(CHINESE_RE.findall(text or ""))


def _equation_to_marker(s: str) -> str:
    text = str(s or "").strip()
    m = EQUATION_NOTE_RE.fullmatch(text)
    if m:
        return normalize_note_marker(m.group(1))
    return normalize_note_marker(text)


def _equation_text(s: str) -> str:
    text = str(s or "").strip()
    return _LATEX_GREEK.get(text, text)


def normalize_note_marker(s: str) -> str:
    s = str(s).strip()
    s = s.strip("{}^ ")
    sup_map = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
    return s.translate(sup_map)


def extract_text_and_notes(obj: Any) -> Tuple[str, List[NoteRef]]:
    text, notes, _runs = extract_text_notes_and_runs(obj)
    return text, notes


def extract_text_notes_and_runs(obj: Any) -> Tuple[str, List[NoteRef], List[Dict[str, Any]]]:
    """Extract readable text and equation_inline note refs from MinerU content."""
    parts: List[str] = []
    notes: List[NoteRef] = []
    runs: List[Dict[str, Any]] = []

    def append_text(text: str) -> None:
        if not text:
            return
        parts.append(text)
        if runs and runs[-1].get("type") == "text":
            runs[-1]["text"] = str(runs[-1].get("text", "")) + text
        else:
            runs.append({"type": "text", "text": text})

    def rec(x: Any) -> None:
        if isinstance(x, dict):
            typ = x.get("type")
            if typ == "text":
                append_text(str(x.get("content", "")))
            elif typ in {"equation_inline", "equation_interline"}:
                raw_marker = str(x.get("content", ""))
                marker = _equation_to_marker(raw_marker)
                if marker and NOTE_MARKER_RE.fullmatch(marker):
                    notes.append(NoteRef(marker=marker, source=typ, raw_marker=raw_marker))
                    runs.append(
                        {
                            "type": "note_ref",
                            "marker": marker,
                            "raw_marker": raw_marker,
                            "source": typ,
                        }
                    )
                else:
                    append_text(_equation_text(raw_marker))
            else:
                # Avoid adding asset paths/html while traversing image/table content.
                for k, v in x.items():
                    if k in {"image_source", "html", "table_type", "table_nest_level", "path"}:
                        continue
                    rec(v)
        elif isinstance(x, list):
            for y in x:
                rec(y)

    rec(obj)
    for run in runs:
        if run.get("type") == "text":
            run["text"] = _normalize_extracted_text(str(run.get("text", "")))
    return _normalize_extracted_text("".join(parts)), notes, runs


def extract_list_item_text(item: Dict[str, Any]) -> Tuple[str, List[NoteRef]]:
    return extract_text_and_notes(item.get("item_content", item))


def extract_caption_list(items: Sequence[Any]) -> List[str]:
    out = []
    for x in items or []:
        t, _ = extract_text_and_notes(x)
        if t:
            out.append(t)
    return out


def strip_trailing_text_note(text: str) -> Tuple[str, List[NoteRef]]:
    """Pull final * / ** / numeric note from visible text, but avoid page numbers."""
    text = normalize_ws(text)
    if not text or PAGE_NUM_RE.match(text):
        return text, []
    # Do not strip from attribution year lines like "1592年".
    if ATTR_RE.match(text):
        return text, []
    m = TRAILING_NOTE_RE.match(text)
    if not m:
        return text, []
    note = normalize_note_marker(m.group("note"))
    body = normalize_ws(m.group("body"))
    # Conservative: numeric notes generally follow CJK punctuation/quotes.
    if note.isdigit() and (not body or body[-1] not in "。？！；”’）】》."):
        return text, []
    # Avoid stripping normal dates/numbers accidentally.
    if note.isdigit() and len(note) > 2:
        return text, []
    return body, [NoteRef(marker=note, source="trailing_text", raw_marker=m.group("note").strip())]


def block_text(block: RawBlock, clean: bool = True) -> str:
    if not clean:
        return block.text
    t, _ = strip_trailing_text_note(block.text)
    return t


def merge_inline_runs(blocks: Sequence[RawBlock], separator: str = "\n") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if index and separator:
            _append_inline_text(out, separator)
        for run in _inline_runs_for_raw_block(block):
            if run.get("type") == "text":
                _append_inline_text(out, str(run.get("text", "")))
            else:
                out.append(dict(run))
    return out


def _inline_runs_for_raw_block(block: RawBlock) -> List[Dict[str, Any]]:
    text, extra = strip_trailing_text_note(block.text)
    runs: List[Dict[str, Any]] = (
        [dict(run) for run in block.inline_runs]
        if block.inline_runs
        else [{"type": "text", "text": text}]
    )
    if extra and not any(run.get("type") == "note_ref" for run in runs):
        runs = [{"type": "text", "text": text}]
        for ref in extra:
            runs.append(_inline_run_from_note_ref(ref, block.page))
    for run in runs:
        if run.get("type") == "note_ref":
            run.setdefault("source_page", block.page)
    return runs


def _inline_run_from_note_ref(ref: NoteRef, page: int) -> Dict[str, Any]:
    raw_marker = ref.raw_marker or ref.marker
    return {
        "type": "note_ref",
        "marker": ref.marker,
        "raw_marker": raw_marker,
        "source": ref.source,
        "source_page": page,
    }


def _append_inline_text(runs: List[Dict[str, Any]], text: str) -> None:
    if not text:
        return
    if runs and runs[-1].get("type") == "text":
        runs[-1]["text"] = str(runs[-1].get("text", "")) + text
    else:
        runs.append({"type": "text", "text": text})


def normalize_toc_number(s: str) -> str:
    # Common OCR confusions in this book: I->1, II->11, io->10, i6->16, 3。->30.
    # Keep explicit line breaks inside multi-line headings such as
    # "IO\n朝鲜水师的反击".  Earlier versions used \s+ in the replacement
    # and accidentally collapsed the chapter number/title newline.
    s = s.strip()
    s = re.sub(r"^I(?=\d)", "1", s)
    s = re.sub(r"^II(?=[ \t\r\n]+)", "11", s)
    s = re.sub(r"^2I(?=[ \t\r\n]+)", "21", s)
    s = re.sub(r"^I(?=[ \t\r\n]+)", "1", s)
    s = re.sub(r"^io(?=[ \t\r\n]+)", "10", s, flags=re.I)
    s = re.sub(r"^i6(?=[ \t\r\n]+)", "16", s, flags=re.I)
    s = re.sub(r"^3[。.](?=[ \t\r\n]*)", "30", s)
    s = re.sub(r"僵[ \t]+局", "僵局", s)
    return s
