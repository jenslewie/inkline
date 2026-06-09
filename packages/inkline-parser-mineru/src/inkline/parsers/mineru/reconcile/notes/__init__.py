"""Note resolution re-export hub.

Only the names in __all__ are stable public API. Private names
(_PageFootnoteStrategy, _NoteContext, _EndnoteSectionStrategy) are
exported for backward compatibility but should not be relied on by
new code; import them directly from their real modules instead:
  - resolver: _PageFootnoteStrategy
  - scopes: _NoteContext, _EndnoteSectionStrategy
"""

from __future__ import annotations

__all__ = [
    "resolve_note_links",
    "recover_missing_note_refs",
]


def __getattr__(name: str):
    if name == "resolve_note_links":
        from .resolver import resolve_note_links

        return resolve_note_links
    if name == "_PageFootnoteStrategy":
        from .resolver import _PageFootnoteStrategy

        return _PageFootnoteStrategy
    if name == "_EndnoteSectionStrategy":
        from .scopes import _EndnoteSectionStrategy

        return _EndnoteSectionStrategy
    if name == "_NoteContext":
        from .scopes import _NoteContext

        return _NoteContext
    if name == "recover_missing_note_refs":
        from .markers import recover_missing_note_refs

        return recover_missing_note_refs
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")