"""Prerequisite tests for duplicate helper functions.

These tests validate that the two implementations of
_inline_note_run_from_ref and _ref_requires_inline_run produce
compatible output, and specifically test the raw_marker write-back
side effect in the resolver.py version.
"""

from __future__ import annotations

import pytest

# Import both implementations
from mineru_normalizer.reconcile.notes.marker_inline import (
    _inline_note_run_from_ref as inline_run_from_marker_inline,
    _ref_requires_inline_run as requires_from_marker_inline,
    _fallback_raw_marker as fallback_from_marker_inline,
)


# ── _ref_requires_inline_run ──

class TestRefRequiresInlineRun:
    """Test the merged _ref_requires_inline_run."""

    @pytest.mark.parametrize(
        "ref,expected",
        [
            ({"source": "equation_inline"}, True),
            ({"source": "equation_interline"}, True),
            ({"source": "trailing_text"}, True),
            ({"source": "qwen_marker_locator"}, False),
            ({"source": "page_sequence_gap"}, False),
            ({"inline_position": "exact"}, True),
            ({"inline_position": "approximate"}, False),
            ({}, False),
            ({"source": "recovered_text", "inline_position": "exact"}, True),
        ],
    )
    def test_returns_correct_result(self, ref, expected):
        assert requires_from_marker_inline(ref) == expected


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

    def test_exact_inline_position_raw_marker(self):
        ref = {"marker": "3", "inline_position": "exact"}
        result = inline_run_from_marker_inline(ref)
        assert result.get("raw_marker") == "^{3}"

    def test_key_iteration_only_copies_existing_keys(self):
        """The merged implementation copies only keys that exist in the ref."""
        ref = {"marker": "1", "source": "equation_inline"}
        result = inline_run_from_marker_inline(ref)
        # Should NOT have keys that weren't in the original ref
        assert "confidence" not in result
        assert "inline_offset" not in result
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
            "inline_position": "exact",
            "inline_offset": 42,
            "target_block_id": "block_5",
            "target_note_id": "note_5",
            "note_strategy": "page_footnote",
            "resolution_confidence": "high",
            "position": "after_text",
            "source_page": 3,
            "recovery_reason": "gap",
            "inline_position_source": "qwen",
            "inline_position_confidence": "high",
        }
        result = inline_run_from_marker_inline(ref)
        for key in (
            "marker", "raw_marker", "source", "confidence",
            "inline_position", "inline_offset", "target_block_id",
            "target_note_id", "note_strategy", "resolution_confidence",
            "position", "source_page", "recovery_reason",
            "inline_position_source", "inline_position_confidence",
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
    only for equation sources or exact inline_position, and None otherwise.
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
        assert fallback_from_marker_inline({"marker": "1", "inline_position": "exact"}) == "^{1}"
        assert fallback_from_marker_inline({"marker": "1", "inline_position": "approximate"}) is None

    def test_empty_marker_returns_none(self):
        assert fallback_from_marker_inline({"marker": ""}) is None