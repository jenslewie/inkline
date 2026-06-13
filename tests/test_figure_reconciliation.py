"""Regression tests for figure caption reconciliation and legend marking."""

from __future__ import annotations

from inkline.parsers.mineru.reconcile.figure import reconcile_figure_captions
from inkline.parsers.mineru.schema.block_types import CAPTION, FIGURE, PARAGRAPH


def _block(type_: str, text: str, page: int = 1, bbox: tuple | None = None) -> dict:
    """Create a test block. Default bboxes use RENDERED-pixel coordinates (>650 wide, >750 tall)
    so PageGeometry.from_canonical_blocks correctly infers page_width=1000."""
    b: dict = {"type": type_, "text": text, "block_id": f"b_{type_}_{text[:4]}"}
    if bbox:
        b["source"] = {"page": page, "bbox": list(bbox)}
    else:
        if type_ == FIGURE:
            b["source"] = {"page": page, "bbox": [100, 100, 500, 450]}
        elif type_ == CAPTION:
            b["source"] = {"page": page, "bbox": [100, 460, 500, 500]}
        else:
            b["source"] = {"page": page, "bbox": [100, 460, 950, 500]}
    return b


def test_paragraph_caption_merged_into_figure() -> None:
    """A PARAGRAPH-type caption block (e.g. '图1 ...') following a figure
    should be merged into the figure via _accept_paragraph, because
    CAPTION_TEXT_TYPES includes PARAGRAPH.

    This is the core regression: after the original P1 fix removed PARAGRAPH
    from CAPTION_TEXT_TYPES, such blocks were rejected. Restoring PARAGRAPH
    ensures they are absorbed again.
    """
    # RENDERED coordinate space: ensure max coords exceed 650w / 750h thresholds
    # so PageGeometry correctly infers page_width=1000.
    figure = _block(FIGURE, "", page=1, bbox=[100, 100, 500, 800])
    caption_para = _block(PARAGRAPH, "图1 实验流程示意图", page=1, bbox=[100, 810, 500, 850])
    blocks = [figure, caption_para]

    reconcile_figure_captions(blocks)

    # The paragraph caption should be absorbed into the figure
    assert len(blocks) == 1
    assert blocks[0]["type"] == FIGURE
    assert "图1 实验流程示意图" in blocks[0].get("attrs", {}).get("captions", [])


def test_isolated_paragraph_not_labeled_legend() -> None:
    """An isolated body paragraph must NOT get caption_role=legend —
    the legend-marking loop only targets CAPTION-typed blocks."""
    body = _block(PARAGRAPH, "这是一段普通正文。", page=1)
    blocks = [body]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    assert blocks[0]["type"] == PARAGRAPH
    assert (blocks[0].get("attrs") or {}).get("caption_role") != "legend"


def test_isolated_caption_labeled_legend() -> None:
    """A CAPTION block not adjacent to any figure should get caption_role=legend."""
    caption = _block(CAPTION, "表1 统计数据", page=1)
    blocks = [caption]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    assert blocks[0]["attrs"]["caption_role"] == "legend"


def test_caption_between_figures_not_labeled_legend() -> None:
    """A CAPTION block sandwiched between two figures should NOT get caption_role=legend."""
    fig1 = _block(FIGURE, "", page=1, bbox=[50, 50, 350, 200])
    caption = _block(CAPTION, "图1 流程图", page=1, bbox=[50, 210, 350, 240])
    fig2 = _block(FIGURE, "", page=1, bbox=[50, 250, 350, 400])
    blocks = [fig1, caption, fig2]

    reconcile_figure_captions(blocks)

    for b in blocks:
        if b["type"] == CAPTION:
            assert (b.get("attrs") or {}).get("caption_role") != "legend"


def test_html_table_to_text_preserves_entities_and_br() -> None:
    """HTML entities and <br> tags must be decoded / spaced correctly."""
    from inkline.parsers.mineru.normalize.builders import _html_table_to_text

    html = "<tr><td>A&amp;B</td><td>C<br>D</td></tr>"
    text = _html_table_to_text(html)
    assert text == "A&B\tC D"
