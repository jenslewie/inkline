"""Note resolution re-export hub.

Only the names in __all__ are stable public API. Private names
(_PageFootnoteStrategy, _NoteContext, _EndnoteSectionStrategy) are
exported for backward compatibility but should not be relied on by
new code; import them directly from their real modules instead:
  - resolver: _PageFootnoteStrategy
  - scopes: _NoteContext, _EndnoteSectionStrategy
"""

from __future__ import annotations

from .markers import recover_missing_note_refs
from .resolver import resolve_note_links

__all__ = [
    "recover_missing_note_refs",
    "resolve_note_links",
]


def __getattr__(name: str):
    if name == "_PageFootnoteStrategy":
        from .resolver import _PageFootnoteStrategy

        return _PageFootnoteStrategy
    if name == "_EndnoteSectionStrategy":
        from .scopes import _EndnoteSectionStrategy

        return _EndnoteSectionStrategy
    if name == "_NoteContext":
        from .scopes import _NoteContext

        return _NoteContext
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
