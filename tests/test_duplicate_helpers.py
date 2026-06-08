"""Prerequisite tests for duplicate helper functions.

These tests validate that the two implementations of
_inline_note_run_from_ref and _ref_requires_inline_run produce
compatible output, and specifically test the raw_marker write-back
side effect in the resolver.py version.
"""

from __future__ import annotations

import copy

import pytest

# Import both implementations
from mineru_normalizer.reconcile.notes.marker_inline import (
    _inline_note_run_from_ref as inline_run_from_marker_inline,
    _ref_requires_inline_run as requires_from_marker_inline,
    _default_raw_marker,
)
from mineru_normalizer.reconcile.notes.resolver import (
    _inline_note_run_from_ref as inline_run_from_resolver,
    _ref_requires_inline_run as requires_from_resolver,
    _fallback_raw_marker,
)


# ── _ref_requires_inline_run ──

class TestRefRequiresInlineRunIdentical:
    """Both implementations of _ref_requires_inline_run are identical."""

    @pytest.mark.parametrize(
        "ref",
        [
            {"source": "equation_inline"},
            {"source": "equation_interline"},
            {"source": "trailing_text"},
            {"source": "qwen_marker_locator"},
            {"source": "page_sequence_gap"},
            {"inline_position": "exact"},
            {"inline_position": "approximate"},
            {},
            {"source": "recovered_text", "inline_position": "exact"},
        ],
    )
    def test_both_return_same_result(self, ref):
        assert requires_from_marker_inline(ref) == requires_from_resolver(ref)


# ── _inline_note_run_from_ref ──

class TestInlineNoteRunFromRefOutput:
    """Compare the output dicts from both implementations."""

    def test_simple_marker_ref_produces_same_keys(self):
        ref = {"marker": "1", "source": "equation_inline", "confidence": "high"}
        inline_result = inline_run_from_marker_inline(ref)
        resolver_result = inline_run_from_resolver(ref)
        # Both should produce a note_ref dict with type marker and raw_marker
        assert inline_result["type"] == "note_ref"
        assert resolver_result["type"] == "note_ref"
        # Both should include the marker
        assert inline_result["marker"] == "1"
        assert resolver_result["marker"] == "1"
        # Both should produce a raw_marker (equation_inline source)
        assert "raw_marker" in inline_result
        assert "raw_marker" in resolver_result

    def test_star_marker_no_raw_marker_in_input(self):
        ref = {"marker": "*", "source": "page_sequence_gap"}
        inline_result = inline_run_from_marker_inline(ref)
        resolver_result = inline_run_from_resolver(ref)
        # Both produce "*" for star markers — _fallback_raw_marker checks
        # startswith("*") before checking source, so "*" is always returned
        assert inline_result.get("raw_marker") == "*"
        assert resolver_result.get("raw_marker") == "*"

    def test_equation_inline_source_raw_marker(self):
        ref = {"marker": "2", "source": "equation_inline"}
        inline_result = inline_run_from_marker_inline(ref)
        resolver_result = inline_run_from_resolver(ref)
        # Both produce ^{2} for numeric markers from equation_inline
        assert inline_result.get("raw_marker") == "^{2}"
        assert resolver_result.get("raw_marker") == "^{2}"

    def test_exact_inline_position_raw_marker(self):
        ref = {"marker": "3", "inline_position": "exact"}
        inline_result = inline_run_from_marker_inline(ref)
        resolver_result = inline_run_from_resolver(ref)
        # marker_inline always produces ^{3} for numeric markers
        assert inline_result.get("raw_marker") == "^{3}"
        # resolver produces ^{3} when inline_position is "exact"
        assert resolver_result.get("raw_marker") == "^{3}"

    def test_resolver_key_iteration_only_copies_existing_keys(self):
        """Resolver's implementation copies only keys that exist in the ref."""
        ref = {"marker": "1", "source": "equation_inline"}
        resolver_result = inline_run_from_resolver(ref)
        # resolver should NOT have keys that weren't in the original ref
        assert "confidence" not in resolver_result
        assert "inline_offset" not in resolver_result
        # But it should have the keys that were in ref
        assert "marker" in resolver_result
        assert "source" in resolver_result

    def test_marker_inline_dict_comprehension_copies_whitelist_keys(self):
        """marker_inline copies all whitelist keys, even if absent from ref."""
        ref = {"marker": "1", "source": "equation_inline"}
        inline_result = inline_run_from_marker_inline(ref)
        # marker_inline uses dict comprehension filtering by whitelist
        # Keys not in ref won't appear in the comprehension result
        # (because ref.items() won't include them)
        assert "confidence" not in inline_result
        assert "inline_offset" not in inline_result

    def test_all_keys_preserved_when_present(self):
        """When all keys are present, both produce dicts with those keys."""
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
        inline_result = inline_run_from_marker_inline(ref)
        resolver_result = inline_run_from_resolver(ref)
        # Both should preserve all these keys
        for key in (
            "marker", "raw_marker", "source", "confidence",
            "inline_position", "inline_offset", "target_block_id",
            "target_note_id", "note_strategy", "resolution_confidence",
            "position", "source_page", "recovery_reason",
            "inline_position_source", "inline_position_confidence",
        ):
            assert inline_result.get(key) == resolver_result.get(key), f"Key {key} differs"


class TestResolverWriteBackSideEffect:
    """Test the raw_marker write-back side effect in resolver.py's version.

    The resolver.py implementation writes back raw_marker to the original
    ref dict via ref.setdefault("raw_marker", raw_marker). This side effect
    is critical because resolver.py callers rely on raw_marker being
    populated in the ref dict after calling _inline_note_run_from_ref.
    """

    def test_resolver_writes_back_raw_marker_to_ref(self):
        ref = {"marker": "1", "source": "equation_inline"}
        result = inline_run_from_resolver(ref)
        # The original ref dict should now have raw_marker
        assert "raw_marker" in ref
        assert ref["raw_marker"] == "^{1}"
        # The result should also have raw_marker
        assert result["raw_marker"] == "^{1}"

    def test_resolver_does_not_overwrite_existing_raw_marker(self):
        ref = {"marker": "1", "source": "equation_inline", "raw_marker": "custom"}
        result = inline_run_from_resolver(ref)
        # ref.setdefault doesn't overwrite existing keys
        assert ref["raw_marker"] == "custom"
        # The result dict should keep the original raw_marker from the ref
        assert result["raw_marker"] == "custom"

    def test_resolver_write_back_star_marker(self):
        ref = {"marker": "*", "source": "equation_inline"}
        result = inline_run_from_resolver(ref)
        # _fallback_raw_marker returns "*" for star markers
        assert ref.get("raw_marker") == "*"
        assert result.get("raw_marker") == "*"

    def test_resolver_no_write_back_for_non_equation_source_without_exact_position(self):
        ref = {"marker": "1", "source": "page_sequence_gap"}
        result = inline_run_from_resolver(ref)
        # _fallback_raw_marker returns None for non-equation, non-exact sources
        assert ref.get("raw_marker") is None
        assert result.get("raw_marker") is None

    def test_marker_inline_does_not_write_back(self):
        """marker_inline's implementation does NOT write back to the ref dict."""
        ref = {"marker": "1", "source": "equation_inline"}
        original_ref = copy.deepcopy(ref)
        result = inline_run_from_marker_inline(ref)
        # The original ref dict should be unchanged
        assert ref == original_ref
        # The result should still have raw_marker
        assert result.get("raw_marker") == "^{1}"


class TestFallbackVsDefaultRawMarker:
    """Compare the raw_marker fallback logic from both implementations.

    _default_raw_marker (marker_inline) always produces ^{marker} for
    numeric markers and returns the marker itself for star markers.

    _fallback_raw_marker (resolver) is more selective: it only produces
    ^{marker} when source is equation_inline/interline/trailing_text
    or inline_position is "exact". Otherwise returns None.
    """

    def test_star_marker_both_return_star(self):
        assert _default_raw_marker("*") == "*"
        # _fallback_raw_marker takes a ref dict, not just a marker string
        assert _fallback_raw_marker({"marker": "*"}) == "*"

    def test_numeric_marker_default_always_produces_caret(self):
        assert _default_raw_marker("1") == "^{1}"
        assert _default_raw_marker("42") == "^{42}"

    def test_numeric_marker_fallback_requires_equation_source(self):
        assert _fallback_raw_marker({"marker": "1", "source": "equation_inline"}) == "^{1}"
        assert _fallback_raw_marker({"marker": "1", "source": "trailing_text"}) == "^{1}"
        assert _fallback_raw_marker({"marker": "1", "source": "page_sequence_gap"}) is None

    def test_numeric_marker_fallback_requires_exact_position(self):
        assert _fallback_raw_marker({"marker": "1", "inline_position": "exact"}) == "^{1}"
        assert _fallback_raw_marker({"marker": "1", "inline_position": "approximate"}) is None

    def test_empty_marker_both_return_empty_or_none(self):
        assert _default_raw_marker("") == ""
        assert _fallback_raw_marker({"marker": ""}) is None