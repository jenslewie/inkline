"""Unit tests for EPUB table rendering (_table_html, _apply_cell_alignments)."""

from __future__ import annotations

from inkline.epub._render import _apply_cell_alignments, _table_html


def test_apply_cell_alignments_none() -> None:
    """None cell_alignments returns HTML unchanged."""
    html = "<table><tr><td>A</td></tr></table>"
    result = _apply_cell_alignments(html, None)
    assert result == html


def test_apply_cell_alignments_empty() -> None:
    """Empty cell_alignments dict returns HTML unchanged."""
    html = "<table><tr><td>A</td></tr></table>"
    result = _apply_cell_alignments(html, {})
    assert result == html


def test_apply_cell_alignments_default() -> None:
    """Default alignment is applied to all cells."""
    html = "<table><tr><td>A</td><td>B</td></tr></table>"
    result = _apply_cell_alignments(html, {"default": "center"})
    assert 'class="td-align-center"' in result
    assert result.count("td-align-center") == 2


def test_apply_cell_alignments_row() -> None:
    """Row-level alignment applies to all cells in that row."""
    html = "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>"
    result = _apply_cell_alignments(html, {"rows": [[0, "right"]]})
    # Row 0 cells get right alignment
    assert "td-align-right" in result
    # Row 1 cells have no alignment (no default)
    assert "td-align" not in result[result.index("C"):]


def test_apply_cell_alignments_cell() -> None:
    """Specific cell alignment overrides default."""
    html = "<table><tr><td>A</td><td>B</td></tr></table>"
    result = _apply_cell_alignments(html, {"default": "center", "cells": [[0, 1, "right"]]})
    assert result.count("td-align-center") == 1  # A
    assert result.count("td-align-right") == 1  # B


def test_apply_cell_alignments_with_th() -> None:
    """Alignment classes work on <th> elements too."""
    html = "<table><tr><th>H1</th><th>H2</th></tr><tr><td>A</td><td>B</td></tr></table>"
    result = _apply_cell_alignments(html, {"default": "center"})
    assert result.count("td-align-center") == 4


def test_apply_cell_alignments_existing_class() -> None:
    """When a <td> already has a class, the alignment class is appended."""
    html = '<table><tr><td class="existing">A</td></tr></table>'
    result = _apply_cell_alignments(html, {"default": "center"})
    assert 'class="existing td-align-center"' in result


def test_apply_cell_alignments_row_and_cell() -> None:
    """Row and cell alignments compose: cell overrides row, row overrides default."""
    html = "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>"
    result = _apply_cell_alignments(
        html,
        {
            "default": "left",
            "rows": [[0, "center"]],
            "cells": [[0, 0, "right"]],
        },
    )
    # A = cell override right
    assert result.count("td-align-right") == 1
    # B = row override center
    assert result.count("td-align-center") == 1
    # C, D = default left
    assert result.count("td-align-left") == 2


def test_apply_cell_alignments_multi_row_default() -> None:
    """Default alignment across multiple rows."""
    html = (
        "<table>"
        "<tr><td>1</td><td>2</td></tr>"
        "<tr><td>3</td><td>4</td></tr>"
        "<tr><td>5</td><td>6</td></tr>"
        "</table>"
    )
    result = _apply_cell_alignments(html, {"default": "center"})
    assert result.count("td-align-center") == 6


def test_apply_cell_alignments_no_default_no_rows_no_cells() -> None:
    """Empty alignment options do not add classes."""
    html = "<table><tr><td>A</td></tr></table>"
    result = _apply_cell_alignments(html, {"default": ""})
    assert "td-align" not in result


def test_apply_cell_alignments_whitespace_in_tag() -> None:
    """Handles <td> with whitespace/attributes before closing >."""
    html = '<table><tr><td  id="x">A</td></tr></table>'
    result = _apply_cell_alignments(html, {"default": "center"})
    assert "td-align-center" in result


def test_apply_cell_alignments_whitelist_ignores_invalid() -> None:
    """Only left/center/right are accepted; invalid values are ignored."""
    html = "<table><tr><td>A</td></tr></table>"
    # An alignment value with XSS-like content should not produce any class
    result = _apply_cell_alignments(html, {"default": 'center" onclick="x'})
    assert "td-align" not in result
    assert "onclick" not in result
    # Arbitrary string also ignored
    result2 = _apply_cell_alignments(html, {"default": "justify"})
    assert "td-align" not in result2


def test_apply_cell_alignments_single_quote_class() -> None:
    """When class attribute uses single quotes, alignment is merged correctly."""
    html = "<table><tr><td class='existing'>A</td></tr></table>"
    result = _apply_cell_alignments(html, {"default": "center"})
    assert "class='existing td-align-center'" in result
    # No duplicate class attribute
    assert result.count("class=") == 1


def test_table_html_fallback_applies_alignments() -> None:
    """Text-fallback table path also applies cell_alignments."""
    block = {
        "text": "A | B\nC | D",
        "attrs": {"cell_alignments": {"default": "center"}},
    }
    result = _table_html(block)
    # Uses text fallback -> <td> elements should get alignment class
    assert result is not None
    assert "td-align-center" in result
    # Verify all four cells got the class
    assert result.count("td-align-center") == 4