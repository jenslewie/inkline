"""Display block body-paragraph split. Splits display blocks that have absorbed
body prose lines, demoting the prose tail back to paragraph type."""

from __future__ import annotations

from typing import Any, Dict, List

from ...analysis.layout import LayoutStats
from ...schema.block_types import DISPLAY_BLOCK, PARAGRAPH
from ..block_access import block_bbox as _bbox
from ..notes.keys import note_ref_key as _note_ref_key


def reconcile_display_block_body_paragraph_split(
    blocks: List[Dict[str, Any]], layout: LayoutStats
) -> None:
    """Demote body-paragraph tails from display blocks back to paragraphs.

    When a display-run merge absorbs body prose, the resulting display block
    may contain wide body-width lines that should be separate paragraphs.
    This pass scans each display block and splits the text at the first
    body-width prose line, keeping only the display-prefix as display_block.
    """
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        if cur.get("type") != DISPLAY_BLOCK:
            i += 1
            continue
        text = str(cur.get("text", "")).strip()
        if "\n" not in text:
            i += 1
            continue

        split_point = _find_body_split_point(cur, text, layout)
        if split_point is None:
            i += 1
            continue

        display_text = text[:split_point].strip()
        body_text = text[split_point:].strip()
        if not display_text or not body_text:
            i += 1
            continue

        # Check that the body section actually looks like prose
        body_lines = [ln.strip() for ln in body_text.split("\n") if ln.strip()]
        if len(body_lines) < 1:
            i += 1
            continue
        # The body section should have at least one long line
        if all(len(ln) <= 60 for ln in body_lines):
            i += 1
            continue

        # Partition inline metadata before modifying the block
        display_block_runs, body_runs = _split_inline_runs_at_offset(
            (cur.get("attrs") or {}).get("inline_runs"), split_point
        )
        display_block_refs, body_refs = _split_note_refs_by_runs(
            (cur.get("attrs") or {}).get("note_refs"),
            display_block_runs,
            body_runs,
        )

        cur["text"] = display_text
        attrs = cur.setdefault("attrs", {})
        ev = attrs.setdefault("classification_evidence", [])
        if "split_body_paragraph_from_display_block" not in ev:
            ev.append("split_body_paragraph_from_display_block")
        if display_block_runs:
            attrs["inline_runs"] = display_block_runs
        else:
            attrs.pop("inline_runs", None)
        if display_block_refs is not None:
            attrs["note_refs"] = display_block_refs
        else:
            attrs.pop("note_refs", None)

        import copy

        new_para = copy.deepcopy(cur)
        new_para["block_id"] = f"{cur.get('block_id')}_body"
        new_para["type"] = PARAGRAPH
        new_para["text"] = body_text
        new_para.pop("level", None)
        # Keep source (approximate bbox is better than null)
        nattrs = new_para.setdefault("attrs", {})
        for k in [
            "role",
            "content_form",
            "content_form_confidence",
            "content_form_scores",
            "classification_evidence",
            "quote_text",
            "attribution",
            "layout_role",
            "line_count",
            "has_attribution_line",
            "line_layouts",
            "raw_types",
        ]:
            nattrs.pop(k, None)
        nattrs.pop("merged_from", None)
        nattrs.pop("merge_evidence", None)
        nattrs.pop("merge_origin", None)
        if body_runs:
            nattrs["inline_runs"] = body_runs
        else:
            nattrs.pop("inline_runs", None)
        if body_refs is not None:
            nattrs["note_refs"] = body_refs
        else:
            nattrs.pop("note_refs", None)
        nattrs["split_from_display_block_id"] = cur.get("block_id")
        blocks.insert(i + 1, new_para)
        i += 2


def _find_body_split_point(
    block: Dict[str, Any], text: str, layout: LayoutStats
) -> int | None:
    """Find the character offset where body prose begins within a display block.

    Scans lines from the start.  Returns the offset of the first line whose
    length and block-level bbox confirm body-width prose, but only if it is
    preceded by at least one shorter display-like line.

    Only splits when the block-level bbox confirms body-width positioning
    (at body indent with >= 88% body width).  Indented/narrow display blocks
    are never split — text-length alone is not layout evidence.
    """
    lines = text.split("\n")
    first_body_idx = None
    bb = _bbox(block)
    block_at_body = bb and (
        float(bb[0]) <= layout.body_left + max(48.0, layout.body_width * 0.06)
        and (float(bb[2]) - float(bb[0])) >= layout.body_width * 0.88
    )
    if not block_at_body:
        return None

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) > 80 and idx > 0:
            first_body_idx = idx
            break

    if first_body_idx is None:
        return None
    offset = 0
    for i in range(first_body_idx):
        offset += len(lines[i]) + 1
    return offset


def _split_inline_runs_at_offset(
    runs: Any, split_offset: int
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split inline runs at a character offset in the block text."""
    if not isinstance(runs, list):
        return [], []
    text_char_offset = 0
    split_run_index = -1
    split_char_index = 0
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or run.get("type") != "text":
            continue
        text = str(run.get("text", ""))
        next_offset = text_char_offset + len(text)
        if text_char_offset <= split_offset <= next_offset:
            split_run_index = index
            split_char_index = split_offset - text_char_offset
            break
        text_char_offset = next_offset

    if split_run_index < 0:
        return [], []

    display_runs: List[Dict[str, Any]] = []
    body_runs: List[Dict[str, Any]] = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        copied = dict(run)
        if index < split_run_index:
            display_runs.append(copied)
        elif index > split_run_index:
            body_runs.append(copied)
        else:
            text = str(copied.get("text", ""))
            before = text[:split_char_index].rstrip()
            after = text[split_char_index:].lstrip()
            if before:
                display_runs.append({"type": "text", "text": before})
            if after:
                body_runs.append({"type": "text", "text": after})
    return display_runs, body_runs


def _split_note_refs_by_runs(
    refs: Any,
    display_block_runs: List[Dict[str, Any]],
    body_runs: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]] | None, List[Dict[str, Any]] | None]:
    """Partition note refs to match the side they belong to.

    Modelled on overflow_tail_split._split_note_refs_by_runs.
    """
    if not isinstance(refs, list):
        return None, None
    buckets: Dict[tuple[str, str, int | None], List[Dict[str, Any]]] = {}
    for ref in refs:
        if isinstance(ref, dict):
            buckets.setdefault(_note_ref_key(ref), []).append(ref)
    return _refs_for_runs(display_block_runs, buckets), _refs_for_runs(body_runs, buckets)


def _refs_for_runs(
    runs: List[Dict[str, Any]],
    buckets: Dict[tuple[str, str, int | None], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for run in runs:
        if run.get("type") != "note_ref":
            continue
        matches = buckets.get(_note_ref_key(run)) or []
        if matches:
            out.append(matches.pop(0))
    return out