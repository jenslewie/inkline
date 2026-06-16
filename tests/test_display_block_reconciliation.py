"""Regression tests for display block vs paragraph reconciliation: CJK numbered
promotion guards, display-run stop conditions, body-paragraph splitting, and
right-aligned terminal block detection."""

from __future__ import annotations

from inkline.parsers.mineru.reconcile.display_block.body_paragraph_split import (
    reconcile_display_block_body_paragraph_split,
)
from inkline.parsers.mineru.reconcile.display_block.cjk_numbered import (
    reconcile_cjk_numbered_display_blocks,
)
from inkline.parsers.mineru.reconcile.display_block.layout import reconcile_display_blocks
from inkline.parsers.mineru.reconcile.display_block.right_align import (
    reconcile_right_aligned_terminal_blocks,
)
from inkline.parsers.mineru.schema.block_types import DISPLAY_BLOCK, PARAGRAPH
from inkline.parsers.mineru.schema.models import LayoutStats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _layout(
    body_left: float = 120.0,
    body_right: float = 880.0,
    page_width: float = 1000.0,
    page_height: float = 1000.0,
) -> LayoutStats:
    return LayoutStats(
        body_left=body_left,
        body_right=body_right,
        page_width=page_width,
        page_height=page_height,
    )


def _block(
    type_: str,
    text: str,
    page: int = 1,
    bbox: list | None = None,
    block_id: str | None = None,
    attrs: dict | None = None,
) -> dict:
    """Create a test block in rendered-pixel coordinate space."""
    b: dict = {
        "block_id": block_id or f"b_{type_}_{abs(hash(text)) % 99999:05d}",
        "type": type_,
        "text": text,
    }
    if bbox:
        b["source"] = {"page": page, "bbox": bbox}
    else:
        # Default: body-width paragraph at body_left
        b["source"] = {"page": page, "bbox": [120, 400, 880, 440]}
    if attrs:
        b["attrs"] = attrs
    return b


DEFAULT_LAYOUT = _layout()


# ---------------------------------------------------------------------------
# Task 1: CJK numbered paragraph promotion — layout guards
# ---------------------------------------------------------------------------

class TestCJKNumberedPromotion:
    def test_cjk_numbered_body_paragraph_not_promoted(self) -> None:
        """A CJK numbered paragraph at body indent with body width should NOT
        be promoted to display_block, even if adjacent blocks are also
        CJK numbered."""
        # All three blocks are body-width paragraphs at body indent
        b1 = _block(PARAGRAPH, "一、这是正文段落的内容，非常长以至于明显是叙事性文本。",
                     page=1, bbox=[120, 200, 880, 240])
        b2 = _block(PARAGRAPH, "二、这是第二个正文段落的内容，同样非常长。",
                     page=1, bbox=[120, 260, 880, 300])
        b3 = _block(PARAGRAPH, "三、这是第三个正文段落。",
                     page=1, bbox=[120, 320, 880, 360])
        blocks = [b1, b2, b3]

        reconcile_cjk_numbered_display_blocks(blocks, DEFAULT_LAYOUT)

        # All three should remain as paragraph
        for b in blocks:
            assert b["type"] == PARAGRAPH

    def test_cjk_numbered_indented_block_promoted(self) -> None:
        """A CJK numbered paragraph that is indented past body_left with narrow
        width should be promoted to display_block."""
        # This block is indented + narrow → display layout
        prev = _block(PARAGRAPH, "前面的正文内容。",
                     page=1, bbox=[120, 200, 880, 240])
        cur = _block(PARAGRAPH, "一、条款内容",
                     page=1, bbox=[250, 260, 550, 290])
        next_ = _block(PARAGRAPH, "二、条款内容",
                      page=1, bbox=[250, 300, 550, 330])
        blocks = [prev, cur, next_]

        reconcile_cjk_numbered_display_blocks(blocks, DEFAULT_LAYOUT)

        # cur and next should be promoted
        assert cur["type"] == DISPLAY_BLOCK
        assert next_["type"] == DISPLAY_BLOCK

    def test_cjk_numbered_introduced_but_body_width_not_promoted(self) -> None:
        """A CJK numbered paragraph introduced by a colon but at body indent
        with body width should NOT be promoted."""
        intro = _block(PARAGRAPH, "下面分述如下：",
                      page=1, bbox=[120, 200, 880, 240])
        body = _block(PARAGRAPH, "一、这是正文段落的内容非常长，属于叙事性文本。",
                     page=1, bbox=[120, 260, 880, 300])
        blocks = [intro, body]

        reconcile_cjk_numbered_display_blocks(blocks, DEFAULT_LAYOUT)

        assert body["type"] == PARAGRAPH

    def test_cjk_numbered_introduced_with_display_layout_promoted(self) -> None:
        """A CJK numbered paragraph introduced by a colon that also has display
        layout (indented + narrow) should be promoted."""
        intro = _block(PARAGRAPH, "下面分述如下：",
                      page=1, bbox=[120, 200, 880, 240])
        display = _block(PARAGRAPH, "一、条款",
                        page=1, bbox=[250, 260, 520, 290])
        blocks = [intro, display]

        reconcile_cjk_numbered_display_blocks(blocks, DEFAULT_LAYOUT)

        assert display["type"] == DISPLAY_BLOCK


# ---------------------------------------------------------------------------
# Task 2: Display run stop conditions for body-text paragraphs
# ---------------------------------------------------------------------------

class TestDisplayRunStopConditions:
    def test_body_paragraph_not_absorbed_into_display(self) -> None:
        """A body-width paragraph at body indent should NOT be absorbed into
        a preceding display block during same-page continuation."""
        display = _block(DISPLAY_BLOCK, "这是一段引文内容。",
                        page=1, bbox=[250, 200, 520, 240])
        body = _block(PARAGRAPH, "这是正文叙事段落，宽度接近正文宽度。",
                     page=1, bbox=[120, 260, 880, 300])
        blocks = [display, body]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert body["type"] == PARAGRAPH
        assert len(blocks) == 2

    def test_display_continuation_aligned_narrow_absorbed(self) -> None:
        """A narrow, indented paragraph aligned with the display block should
        be absorbed as continuation."""
        display = _block(DISPLAY_BLOCK, "引文第一行。",
                        page=1, bbox=[250, 200, 520, 240])
        cont = _block(PARAGRAPH, "引文第二行。",
                     page=1, bbox=[250, 260, 510, 290])
        blocks = [display, cont]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        # Should be merged into one display block
        assert len(blocks) == 1
        assert blocks[0]["type"] == DISPLAY_BLOCK


# ---------------------------------------------------------------------------
# Task 3: Body-paragraph splitting from display blocks
# ---------------------------------------------------------------------------

class TestBodyParagraphSplit:
    def test_wide_prose_split_from_display_block(self) -> None:
        """A display_block whose first lines are display-like but later lines
        are long body prose should be split: display prefix stays, body tail
        becomes paragraph."""
        layout = _layout()
        # First line short (display), second line is long body prose (>80 chars)
        long_line = (
            "这是一段非常长的正文叙事段落它显然属于正文而非引文内容"
            "长度远超display阈值这段文字现在有超过八十字以确保被正确"
            "识别为正文叙事行而不是展示行因为展示行通常都比较短。"
        )
        block = _block(
            DISPLAY_BLOCK,
            f"引文开头\n{long_line}",
            page=1,
            bbox=[120, 200, 880, 300],
        )
        blocks = [block]

        reconcile_display_block_body_paragraph_split(blocks, layout)

        # Should split into display + paragraph
        assert len(blocks) == 2
        assert blocks[0]["type"] == DISPLAY_BLOCK
        assert blocks[1]["type"] == PARAGRAPH
        assert "引文开头" in blocks[0]["text"]
        assert "正文而非引文" in blocks[1]["text"]

    def test_short_display_lines_not_split(self) -> None:
        """A display block with only short lines should NOT be split."""
        block = _block(
            DISPLAY_BLOCK,
            "第一条\n第二条\n第三条",
            page=1,
            bbox=[250, 200, 520, 300],
        )
        blocks = [block]

        reconcile_display_block_body_paragraph_split(blocks, DEFAULT_LAYOUT)

        assert len(blocks) == 1
        assert blocks[0]["type"] == DISPLAY_BLOCK


# ---------------------------------------------------------------------------
# Task 4: Right-aligned terminal block detection
# ---------------------------------------------------------------------------

class TestRightAlignedTerminal:
    def test_right_aligned_date_promoted(self) -> None:
        """A short right-aligned date block near page bottom should be promoted
        to display_block with alignment="right"."""
        # Page-bottom body paragraph
        body = _block(PARAGRAPH, "正文内容到此结束。",
                     page=1, bbox=[120, 700, 880, 740])
        # Right-aligned date near page bottom
        date = _block(PARAGRAPH, "万历二十一年",
                     page=1, bbox=[600, 820, 880, 850])
        # Need a large bbox to trigger near-page-bottom detection
        date2 = _block(PARAGRAPH, "万历二十一年",
                       page=1, bbox=[600, 850, 880, 900])
        blocks = [body, date, date2]

        reconcile_right_aligned_terminal_blocks(blocks, DEFAULT_LAYOUT)

        # At least one right-aligned block should be promoted
        promoted = [b for b in blocks if b["type"] == DISPLAY_BLOCK]
        assert len(promoted) >= 1
        for p in promoted:
            attrs = p.get("attrs", {})
            assert attrs.get("alignment") == "right"
            assert attrs.get("style_hints", {}).get("text_align") == "right"

    def test_body_paragraph_not_right_aligned_promoted(self) -> None:
        """A normal body-width paragraph should NOT be promoted as
        right-aligned terminal block."""
        body = _block(PARAGRAPH, "这是一段正常的正文叙事内容，宽度接近正文宽度。",
                     page=1, bbox=[120, 700, 880, 740])
        blocks = [body]

        reconcile_right_aligned_terminal_blocks(blocks, DEFAULT_LAYOUT)

        assert blocks[0]["type"] == PARAGRAPH

    def test_right_aligned_with_gap_from_prev(self) -> None:
        """A right-aligned block with significant gap from previous block
        should be promoted even if not near page bottom."""
        layout = _layout()
        body = _block(PARAGRAPH, "正文内容。",
                     page=1, bbox=[120, 400, 880, 450])
        # Right-aligned, not near page bottom, but large gap
        date = _block(PARAGRAPH, "一九九三年",
                     page=1, bbox=[620, 700, 880, 730])
        # Need a page-height marker so page_heights has data
        marker = _block(PARAGRAPH, "", page=1, bbox=[0, 0, 1000, 1000])
        blocks = [marker, body, date]

        reconcile_right_aligned_terminal_blocks(blocks, layout)

        date_result = [b for b in blocks if b.get("text") == "一九九三年"]
        if date_result:
            assert date_result[0]["type"] == DISPLAY_BLOCK
            assert date_result[0].get("attrs", {}).get("alignment") == "right"


# ---------------------------------------------------------------------------
# Integration: real display block not incorrectly split
# ---------------------------------------------------------------------------

class TestDisplayBlockPreservation:
    def test_real_display_quote_not_split(self) -> None:
        """A genuine display quote with multiple short lines should not be
        incorrectly split by the body-paragraph splitter."""
        layout = _layout()
        quote = _block(
            DISPLAY_BLOCK,
            "「君子之交淡如水」\n「小人之交甘若醴」",
            page=1,
            bbox=[250, 200, 520, 300],
        )
        blocks = [quote]

        reconcile_display_block_body_paragraph_split(blocks, layout)

        assert len(blocks) == 1
        assert blocks[0]["type"] == DISPLAY_BLOCK

    def test_cross_page_display_not_broken(self) -> None:
        """A display block that spans pages should not be incorrectly split."""
        layout = _layout()
        display = _block(
            DISPLAY_BLOCK,
            "第一条内容\n第二条内容",
            page=1,
            bbox=[250, 200, 520, 300],
            attrs={"source": {"pages": [1, 2]},
                   "layout_role": "inline_display_block"},
        )
        blocks = [display]

        reconcile_display_block_body_paragraph_split(blocks, layout)

        # Should remain intact (short lines, no body prose)
        assert blocks[0]["type"] == DISPLAY_BLOCK
