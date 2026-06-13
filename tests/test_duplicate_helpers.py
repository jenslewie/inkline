"""Prerequisite tests for duplicate helper functions.

These tests validate inline note run construction and raw marker fallback.
"""

from __future__ import annotations

from inkline.parsers.mineru.reconcile.notes.marker_inline import (
    _fallback_raw_marker as fallback_from_marker_inline,
)

# Import both implementations
from inkline.parsers.mineru.reconcile.notes.marker_inline import (
    _inline_note_run_from_ref as inline_run_from_marker_inline,
)

# ── _inline_note_run_from_ref ──


class TestInlineNoteRunFromRefOutput:
    """Test the merged _inline_note_run_from_ref output dicts."""

    def test_simple_marker_ref_produces_note_ref_with_raw_marker(self):
        ref = {"marker": "1", "source": "equation_inline", "confidence": "high"}
        result = inline_run_from_marker_inline(ref)
        assert result["type"] == "note_ref"
        assert result["marker"] == "1"
        assert "raw_marker" in result

    def test_star_marker_raw_marker(self):
        ref = {"marker": "*", "source": "page_sequence_gap"}
        result = inline_run_from_marker_inline(ref)
        # _fallback_raw_marker returns "*" for star markers regardless of source
        assert result.get("raw_marker") == "*"

    def test_equation_inline_source_raw_marker(self):
        ref = {"marker": "2", "source": "equation_inline"}
        result = inline_run_from_marker_inline(ref)
        assert result.get("raw_marker") == "^{2}"

    def test_key_iteration_only_copies_existing_keys(self):
        """The merged implementation copies only keys that exist in the ref."""
        ref = {"marker": "1", "source": "equation_inline"}
        result = inline_run_from_marker_inline(ref)
        # Should NOT have keys that weren't in the original ref
        assert "confidence" not in result
        # But should have the keys that were in ref
        assert "marker" in result
        assert "source" in result

    def test_all_keys_preserved_when_present(self):
        """When all keys are present, the result dict has those keys."""
        ref = {
            "marker": "1",
            "raw_marker": "^{1}",
            "source": "equation_inline",
            "confidence": "high",
            "target_block_id": "block_5",
            "target_note_id": "note_5",
            "note_strategy": "page_footnote",
            "resolution_confidence": "high",
            "source_page": 3,
            "recovery_reason": "gap",
        }
        result = inline_run_from_marker_inline(ref)
        for key in (
            "marker",
            "raw_marker",
            "source",
            "confidence",
            "target_block_id",
            "target_note_id",
            "note_strategy",
            "resolution_confidence",
            "source_page",
            "recovery_reason",
        ):
            assert result.get(key) == ref.get(key), f"Key {key} differs"


class TestInlineNoteRunWriteBackSideEffect:
    """Test the raw_marker write-back side effect in the merged _inline_note_run_from_ref.

    The merged implementation (now in marker_inline.py) preserves the
    resolver.py write-back side effect: ref.setdefault("raw_marker", raw_marker).
    This side effect is critical because resolver.py callers rely on
    raw_marker being populated in the ref dict after calling _inline_note_run_from_ref.
    """

    def test_writes_back_raw_marker_to_ref(self):
        ref = {"marker": "1", "source": "equation_inline"}
        result = inline_run_from_marker_inline(ref)
        # The original ref dict should now have raw_marker
        assert "raw_marker" in ref
        assert ref["raw_marker"] == "^{1}"
        # The result should also have raw_marker
        assert result["raw_marker"] == "^{1}"

    def test_does_not_overwrite_existing_raw_marker(self):
        ref = {"marker": "1", "source": "equation_inline", "raw_marker": "custom"}
        result = inline_run_from_marker_inline(ref)
        # ref.setdefault doesn't overwrite existing keys
        assert ref["raw_marker"] == "custom"
        # The result dict should keep the original raw_marker from the ref
        assert result["raw_marker"] == "custom"

    def test_write_back_star_marker(self):
        ref = {"marker": "*", "source": "equation_inline"}
        result = inline_run_from_marker_inline(ref)
        # _fallback_raw_marker returns "*" for star markers
        assert ref.get("raw_marker") == "*"
        assert result.get("raw_marker") == "*"

    def test_no_write_back_for_non_equation_source_without_exact_position(self):
        ref = {"marker": "1", "source": "page_sequence_gap"}
        result = inline_run_from_marker_inline(ref)
        # _fallback_raw_marker returns None for non-equation, non-exact sources
        assert ref.get("raw_marker") is None
        assert result.get("raw_marker") is None


class TestFallbackRawMarker:
    """Test the merged _fallback_raw_marker logic.

    After the merge, both marker_inline and resolver use the same
    _fallback_raw_marker.  It returns "*" for star markers, "^{marker}"
    only for equation sources, and None otherwise.
    """

    def test_star_marker_returns_star(self):
        assert fallback_from_marker_inline({"marker": "*"}) == "*"

    def test_numeric_marker_equation_source_produces_caret(self):
        assert fallback_from_marker_inline({"marker": "1", "source": "equation_inline"}) == "^{1}"
        assert fallback_from_marker_inline({"marker": "42", "source": "trailing_text"}) == "^{42}"

    def test_numeric_marker_requires_equation_source_or_exact_position(self):
        assert fallback_from_marker_inline({"marker": "1", "source": "equation_inline"}) == "^{1}"
        assert fallback_from_marker_inline({"marker": "1", "source": "page_sequence_gap"}) is None

    def test_numeric_marker_exact_position_produces_caret(self):
        assert fallback_from_marker_inline({"marker": "1", "source": "qwen_marker_locator"}) is None

    def test_empty_marker_returns_none(self):
        assert fallback_from_marker_inline({"marker": ""}) is None
