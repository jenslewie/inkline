"""Bounded transport shape for NoteSystemReview."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

NOTE_SYSTEM_REVIEW_PROMPT_VERSION = "note-system-v1"


def build_note_system_review_request(
    *,
    pages: Sequence[int],
    observation_ids: Sequence[str],
    skeleton_entry_indexes: Sequence[int],
    page_asset_ids: Sequence[str],
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Describe one structural candidate without exposing unrelated document state."""

    return {
        "prompt_version": NOTE_SYSTEM_REVIEW_PROMPT_VERSION,
        "prompt": (
            "Review only the supplied candidate pages, assets, observations, and skeleton "
            "entries. Do not infer note targets, markers, sections, text order, or chronology. "
            "Return {'systems': [...]} only when the supplied evidence establishes a separate "
            "note system; otherwise return {'systems': []}."
        ),
        "pages": list(pages),
        "observation_ids": list(observation_ids),
        "skeleton_entry_indexes": list(skeleton_entry_indexes),
        "page_asset_ids": list(page_asset_ids),
        "observations": [dict(record) for record in observations],
    }
