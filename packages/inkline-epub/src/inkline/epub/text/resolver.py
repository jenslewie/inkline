from __future__ import annotations

from typing import Any

from inkline.canonical import strip_footnote_marker
from inkline.epub.text.model import (
    DisplayBlockView,
    FootnoteView,
    HeadingView,
    InlinePart,
    InlineText,
    ListView,
    NoteRef,
    TextSegment,
)


def resolve_inline_text(
    block: dict[str, Any],
    footnote_counter: dict[int, int] | None = None,
) -> InlineText:
    """Resolve canonical text/runs into renderable inline parts.

    The resolver owns chapter-local footnote numbering because it depends on
    canonical note targets and caller-owned chapter state.
    """
    if footnote_counter is None:
        footnote_counter = {}

    raw_runs = (block.get("attrs") or {}).get("inline_runs")
    if raw_runs and isinstance(raw_runs, list):
        return _inline_text_from_runs(block, raw_runs, footnote_counter=footnote_counter)

    text = block.get("text", "")
    if not text:
        return InlineText(parts=[])
    return InlineText(parts=[TextSegment(text=str(text))])


def resolve_display_block_view(
    block: dict[str, Any],
    footnote_counter: dict[int, int] | None = None,
) -> DisplayBlockView:
    attrs = block.get("attrs") or {}
    classes = ["display-block"]
    layout_role = attrs.get("layout_role")
    if layout_role in {"standalone_display_page", "standalone_display_group"}:
        classes.append("display-block-standalone")
    raw_style_hints = attrs.get("style_hints")
    style_hints = raw_style_hints if isinstance(raw_style_hints, dict) else {}
    if (
        layout_role == "flush_right_terminal_block"
        or attrs.get("alignment") == "right"
        or style_hints.get("text_align") == "right"
    ):
        classes.append("display-block-signature")

    inline_text = resolve_inline_text(block, footnote_counter)
    return DisplayBlockView(classes=classes, paragraphs=_split_inline_text_lines(inline_text))


def resolve_heading_view(block: dict[str, Any]) -> HeadingView:
    level = min(max(int(block.get("level", 1)), 2), 6)
    return HeadingView(level=level, text=block.get("text", ""))


def resolve_chapter_title_view(block: dict[str, Any]) -> HeadingView:
    return HeadingView(level=int(block.get("level", 1)), text=block.get("text", ""))


def resolve_list_view(
    blocks: list[dict[str, Any]],
    start: int,
    footnote_counter: dict[int, int] | None = None,
) -> ListView:
    items: list[InlineText] = []
    cursor = start
    while cursor < len(blocks) and blocks[cursor]["type"] == "list_item":
        items.append(resolve_inline_text(blocks[cursor], footnote_counter))
        cursor += 1
    return ListView(items=items)


def resolve_footnote_view(block: dict[str, Any]) -> FootnoteView:
    attrs = block.get("attrs") or {}
    raw_note_id = attrs.get("note_id") or block.get("block_id")
    note_id = str(raw_note_id) if raw_note_id else None
    return FootnoteView(note_id=note_id, text=strip_footnote_marker(block.get("text", ""), attrs))


def _inline_text_from_runs(
    block: dict[str, Any],
    runs: list[dict[str, Any]],
    *,
    footnote_counter: dict[int, int],
) -> InlineText:
    parts: list[TextSegment | NoteRef] = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        if run.get("type") == "text":
            parts.append(TextSegment(text=str(run.get("text", ""))))
            continue
        if run.get("type") != "note_ref":
            continue
        marker = str(run.get("marker") or "")
        if not marker:
            continue
        target = run.get("target_note_id")
        if target is not None:
            local_num = footnote_counter.get(target)
            if local_num is None:
                local_num = len(footnote_counter) + 1
                footnote_counter[target] = local_num
            display_marker = str(local_num)
        else:
            display_marker = marker

        ref_id = f"{block.get('block_id') or 'ref'}_note_ref_{index}"
        parts.append(NoteRef(marker=display_marker, target=target, ref_id=ref_id))
    return InlineText(parts=parts)


def _split_inline_text_lines(text: InlineText) -> list[InlineText]:
    lines: list[list[InlinePart]] = [[]]
    for part in text.parts:
        if isinstance(part, TextSegment):
            segments = part.text.split("\n")
            for index, segment in enumerate(segments):
                if index:
                    lines.append([])
                if segment:
                    lines[-1].append(TextSegment(text=segment))
            continue
        lines[-1].append(part)
    trimmed_lines = [_trim_inline_text_line(line) for line in lines]
    return [InlineText(parts=line) for line in trimmed_lines if _inline_text_has_content(line)]


def _inline_text_has_content(parts: list[InlinePart]) -> bool:
    for part in parts:
        if isinstance(part, NoteRef):
            return True
        if part.text.strip():
            return True
    return False


def _trim_inline_text_line(parts: list[InlinePart]) -> list[InlinePart]:
    trimmed = list(parts)
    if trimmed and isinstance(trimmed[0], TextSegment):
        trimmed[0] = TextSegment(text=trimmed[0].text.lstrip())
    if trimmed and isinstance(trimmed[-1], TextSegment):
        trimmed[-1] = TextSegment(text=trimmed[-1].text.rstrip())
    return [
        part
        for part in trimmed
        if not isinstance(part, TextSegment) or part.text
    ]
