"""Regression tests for figure caption reconciliation and legend marking."""

from __future__ import annotations

from inkline.parsers.mineru.reconcile.figure import reconcile_figure_captions
from inkline.parsers.mineru.schema.block_types import (
    CAPTION,
    DISPLAY_BLOCK,
    FIGURE,
    HEADING,
    PARAGRAPH,
)


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


# ── Change 1 tests: _absorb_image_overlapping_text ──


def test_absorb_text_contained_in_figure_bbox() -> None:
    """PARAGRAPH block whose center falls inside FIGURE bbox should be absorbed."""
    figure = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 600])
    # text block center at (400, 350) — clearly inside figure bbox
    para = _block(PARAGRAPH, "图中文字", page=1, bbox=[300, 300, 500, 400])
    blocks = [figure, para]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    assert blocks[0]["type"] == FIGURE
    assert "图中文字" in blocks[0].get("attrs", {}).get("absorbed_text", "")


def test_absorb_text_overlapping_figure_bbox() -> None:
    """PARAGRAPH with >=50% area overlap inside figure bbox should be absorbed."""
    figure = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 600])
    # text block: 80% area overlap with figure bbox
    # intersection: [600, 500, 700, 550] = 100*50 = 5000
    # text area: [600, 500, 725, 550] = 125*50 = 6250
    # ratio: 5000/6250 = 0.80 >= 0.50
    para = _block(PARAGRAPH, "路线标注", page=1, bbox=[600, 500, 725, 550])
    blocks = [figure, para]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    assert blocks[0]["type"] == FIGURE


def test_absorb_text_overlapping_figure_bbox_area() -> None:
    """PARAGRAPH with >=50% area overlap inside figure bbox — using larger overlap."""
    figure = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 600])
    # text block mostly inside: 80% overlap
    # text: x=[500,620] y=[300,380] = 120*80=9600 area
    # intersection: x=[500,700] y=[300,380] = 200*80=6400 overlap
    # ratio: 6400/9600 = 0.667 >= 0.50
    para = _block(PARAGRAPH, "站点信息", page=1, bbox=[500, 300, 620, 380])
    blocks = [figure, para]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    assert blocks[0]["type"] == FIGURE
    assert "站点信息" in blocks[0].get("attrs", {}).get("absorbed_text", "")


def test_absorb_text_tightly_adjacent_with_ocr_match() -> None:
    """PARAGRAPH flush against image bottom edge with OCR text match should be absorbed."""
    figure = _block(
        FIGURE,
        "",
        page=1,
        bbox=[100, 100, 700, 600],
    )
    figure["attrs"] = {"ocr_text_in_image": "北京 上海 广州 深圳"}
    # text block center at y=603 — 3px from figure bottom edge (600)
    # text matches OCR content verbatim
    para = _block(PARAGRAPH, "北京 上海", page=1, bbox=[100, 600, 300, 610])
    blocks = [figure, para]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    assert blocks[0]["type"] == FIGURE


# ── Change 2 tests: relaxed fragment merging thresholds ──


def test_merge_figure_fragments_below() -> None:
    """Two FIGURE blocks with vertical gap up to 0.12*page_height should merge."""
    # page_height inferred ~1000, so gap up to 120 is acceptable
    fig1 = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 400])
    fig2 = _block(FIGURE, "", page=1, bbox=[100, 430, 700, 530])
    # horizontal overlap: 600 wide both, overlap = 600 >= min(600,600)*0.40 = 240
    # vertical gap: 430-400 = 30 <= 1000*0.12 = 120 ✓
    # fig2 height: 100 <= 1000*0.08 = 80? No, 100 > 80, but fig1 has no captions
    # So this won't merge via below_fragment without captions.
    # Add a caption to fig1 to enable below_fragment path
    fig1["attrs"] = {"captions": ["图1 地图"]}
    blocks = [fig1, fig2]

    reconcile_figure_captions(blocks)

    # Should merge: horizontal overlap OK, gap OK, fig1 has captions
    assert len(blocks) == 1
    assert blocks[0]["type"] == FIGURE


def test_merge_three_figure_fragments() -> None:
    """Three sequential FIGURE fragments should merge into one."""
    fig1 = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 300])
    fig1["attrs"] = {"captions": ["图2 路线"]}
    fig2 = _block(FIGURE, "", page=1, bbox=[100, 310, 700, 380])
    fig3 = _block(FIGURE, "", page=1, bbox=[100, 390, 700, 450])
    blocks = [fig1, fig2, fig3]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    assert blocks[0]["type"] == FIGURE


def test_embedding_text_and_caption_all_absorbed() -> None:
    """Figure with overlapping PARAGRAPH text + following CAPTION → both absorbed."""
    figure = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 500])
    # overlapping paragraph (center inside figure bbox)
    para = _block(PARAGRAPH, "图内文字", page=1, bbox=[300, 300, 500, 350])
    # caption below figure (use PARAGRAPH type like real-world MinerU output)
    caption = _block(PARAGRAPH, "图3 地铁线路图", page=1, bbox=[100, 510, 400, 540])
    blocks = [figure, para, caption]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    assert blocks[0]["type"] == FIGURE
    # The overlapping paragraph should be absorbed as overlapping text
    assert "图内文字" in blocks[0].get("attrs", {}).get("absorbed_text", "")
    # The caption should also be absorbed
    assert "图3 地铁线路图" in blocks[0].get("attrs", {}).get("captions", [])


def test_absorb_following_visual_legend_strip_with_interleaved_small_figure() -> None:
    """Map legend strips below a figure are visual fragments, not reading-flow captions."""
    figure = _block(FIGURE, "", page=1, bbox=[349, 110, 998, 832])
    figure["attrs"] = {"captions": ["法显与义净的求法路线"]}
    title = _block(CAPTION, "法显与义净的求法路线", page=1, bbox=[369, 846, 650, 862])
    route_a = _block(CAPTION, "— 法显路线 399—412年", page=1, bbox=[369, 865, 585, 881])
    scale = _block(FIGURE, "", page=1, bbox=[779, 865, 988, 904])
    scale["block_id"] = "b_scale"
    route_b = _block(CAPTION, "--- 义净路线 671—695年", page=1, bbox=[369, 884, 585, 900])
    blocks = [figure, title, route_a, scale, route_b]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    attrs = blocks[0]["attrs"]
    assert attrs["absorbed_block_ids"] == [
        title["block_id"],
        route_a["block_id"],
        route_b["block_id"],
    ]
    assert attrs["fragment_block_ids"] == [figure["block_id"], scale["block_id"]]
    assert attrs["embedded_text_absorb_reason"] == "following_visual_legend_strip"
    assert attrs["captions"] == []
    assert attrs["visual_legend_captions_absorbed"] == ["法显与义净的求法路线"]
    assert blocks[0]["source"]["bbox"] == [349, 110, 998, 904]


def test_absorb_overlapping_rows_in_following_visual_legend_strip() -> None:
    figure = _block(FIGURE, "", page=1, bbox=[112, 114, 998, 679])
    title = _block(HEADING, "欧亚大陆主要交通线", page=1, bbox=[146, 687, 480, 715])
    label = _block(CAPTION, "印度洋", page=1, bbox=[810, 689, 906, 710])
    route = _block(CAPTION, "---- 丝绸之路", page=1, bbox=[147, 725, 330, 748])
    site = _block(CAPTION, "□ 古代遗址", page=1, bbox=[164, 752, 330, 774])
    blocks = [figure, title, label, route, site]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    attrs = blocks[0]["attrs"]
    assert attrs["absorbed_block_ids"] == [
        title["block_id"],
        label["block_id"],
        route["block_id"],
        site["block_id"],
    ]
    assert blocks[0]["source"]["bbox"] == [112, 114, 998, 774]


def test_long_caption_and_body_tail_are_not_visual_legend_strip() -> None:
    figure = _block(FIGURE, "", page=1, bbox=[107, 113, 876, 486])
    title = _block(HEADING, "喀喇昆仑公路上的佛教石刻", page=1, bbox=[107, 500, 410, 524])
    caption_body = _block(
        PARAGRAPH,
        "图中石刻坐落于巴基斯坦吉尔吉特－巴尔蒂斯坦省霍独尔镇附近的大石堆中，"
        "位于印度河上游北岸。这是喀喇昆仑公路上的晚期图像之一，年代六到八世纪。",
        page=1,
        bbox=[107, 528, 876, 592],
    )
    body_tail = _block(PARAGRAPH, "间范围，即一到八世纪之间。", page=1, bbox=[107, 600, 520, 624])
    blocks = [figure, title, caption_body, body_tail]

    reconcile_figure_captions(blocks)

    attrs = blocks[0].get("attrs") or {}
    assert attrs.get("embedded_text_absorb_reason") != "following_visual_legend_strip"
    assert "absorbed_block_ids" not in attrs
    assert attrs["captions"] == [
        "喀喇昆仑公路上的佛教石刻\n"
        "图中石刻坐落于巴基斯坦吉尔吉特－巴尔蒂斯坦省霍独尔镇附近的大石堆中，"
        "位于印度河上游北岸。这是喀喇昆仑公路上的晚期图像之一，年代六到八世纪。"
    ]
    assert blocks[0]["type"] == FIGURE
    assert blocks[1]["type"] == PARAGRAPH
    assert blocks[1]["text"] == "间范围，即一到八世纪之间。"


def test_single_following_caption_still_renders_as_caption() -> None:
    figure = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 500])
    caption = _block(PARAGRAPH, "普通图片说明", page=1, bbox=[120, 510, 680, 540])
    blocks = [figure, caption]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    assert blocks[0]["attrs"]["captions"] == ["普通图片说明"]
    assert "absorbed_block_ids" not in blocks[0]["attrs"]


# ── Negative tests ──


def test_do_not_absorb_body_text_after_figure() -> None:
    """Full-width PARAGRAPH at body left margin below a large figure → NOT absorbed."""
    figure = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 500])
    # body text: left edge ~80 (< page_width*0.12=120), width ~800 (> page_width*0.50=500)
    body = _block(PARAGRAPH, "这是一段正文内容，不应该被吸收。", page=1, bbox=[80, 510, 880, 560])
    blocks = [figure, body]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 2
    assert blocks[0]["type"] == FIGURE
    assert blocks[1]["type"] == PARAGRAPH


def test_distant_text_not_absorbed() -> None:
    """PARAGRAPH far from figure bbox (>50px gap, no overlap) → NOT absorbed."""
    figure = _block(FIGURE, "", page=1, bbox=[100, 100, 500, 400])
    # text far below and no overlap
    para = _block(PARAGRAPH, "远处文字", page=1, bbox=[100, 500, 950, 550])
    blocks = [figure, para]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 2


def test_body_paragraph_after_large_float_still_rejected() -> None:
    """Large figure + full-width body paragraph → body paragraph correctly rejected
    by body-text guard in caption detection."""
    figure = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 500])
    # This body paragraph is below the figure but looks like caption position.
    # However its left edge < 120 and width > 500 → should be rejected.
    body = _block(
        PARAGRAPH, "根据上图可以看出，整体趋势是向上的。", page=1, bbox=[80, 510, 900, 560]
    )
    blocks = [figure, body]

    reconcile_figure_captions(blocks)

    # The body paragraph should NOT be absorbed as a caption
    assert len(blocks) == 2
    assert blocks[1]["type"] == PARAGRAPH


def test_heading_title_and_body_width_paragraph_merge_as_caption() -> None:
    """A short caption title followed by a wide aligned paragraph belongs to the figure."""
    figure = _block(FIGURE, "", page=1, bbox=[81, 227, 848, 457])
    title = _block(HEADING, "高昌故城遗址", page=1, bbox=[81, 469, 201, 486])
    body = _block(
        PARAGRAPH,
        "吐鲁番附近高昌故城夯土墙是中国境内为数不多的地上古迹之一。"
        "游客可以看到当地人在地下挖土造屋，并用挖出的土垒起高墙。（作者摄）",
        page=1,
        bbox=[81, 490, 850, 550],
    )
    blocks = [figure, title, body]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 1
    attrs = blocks[0]["attrs"]
    assert attrs["captions"] == [
        "高昌故城遗址\n"
        "吐鲁番附近高昌故城夯土墙是中国境内为数不多的地上古迹之一。"
        "游客可以看到当地人在地下挖土造屋，并用挖出的土垒起高墙。（作者摄）"
    ]
    assert attrs["caption_block_ids"] == [title["block_id"], body["block_id"]]
    assert blocks[0]["source"]["bbox"] == [81, 227, 850, 550]


def test_right_side_heading_and_display_block_merge_as_caption() -> None:
    figure = _block(FIGURE, "", page=71, bbox=[133, 118, 532, 518])
    title = _block(HEADING, "东西方相会于佉卢文书", page=71, bbox=[562, 337, 765, 354])
    body = _block(
        DISPLAY_BLOCK,
        "这件尼雅出土的木制文书完好无损，上下两片合在一起，用绳子穿过沟槽绑好后再用泥封住。"
        "左边印章上是汉字；右边印章上是西方人样貌的头像，很可能是希腊罗马的某神，"
        "这种图像常见于健陀罗印章。这份双木板文书记录了一桩进行奴隶、牲畜、土地等交易的情况，"
        "其中还给出了记录交易的官员姓名。",
        page=71,
        bbox=[560, 358, 901, 520],
    )
    body["attrs"] = {
        "layout_role": "inline_display_block",
        "classification_evidence": ["geometry_right_aligned_group"],
    }
    body_after = _block(
        PARAGRAPH,
        "这些命令都来自楼兰王，写给相当于刺史的当地最高长官cozbo。",
        page=71,
        bbox=[127, 553, 899, 602],
    )
    blocks = [figure, title, body, body_after]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 2
    attrs = blocks[0]["attrs"]
    assert attrs["captions"] == [
        "东西方相会于佉卢文书\n"
        "这件尼雅出土的木制文书完好无损，上下两片合在一起，用绳子穿过沟槽绑好后再用泥封住。"
        "左边印章上是汉字；右边印章上是西方人样貌的头像，很可能是希腊罗马的某神，"
        "这种图像常见于健陀罗印章。这份双木板文书记录了一桩进行奴隶、牲畜、土地等交易的情况，"
        "其中还给出了记录交易的官员姓名。"
    ]
    assert attrs["caption_block_ids"] == [title["block_id"], body["block_id"]]
    assert blocks[1] is body_after


def test_heading_caption_title_does_not_absorb_unaligned_body_paragraph() -> None:
    """A body paragraph after a caption-like heading still needs continuation geometry."""
    figure = _block(FIGURE, "", page=1, bbox=[81, 227, 848, 457])
    title = _block(HEADING, "高昌故城遗址", page=1, bbox=[81, 469, 201, 486])
    body = _block(
        PARAGRAPH,
        "这是正文内容，不应该仅因为前面有一个短标题就被合并进图片说明。",
        page=1,
        bbox=[160, 490, 930, 550],
    )
    blocks = [figure, title, body]

    reconcile_figure_captions(blocks)

    assert len(blocks) == 3
    assert blocks[0]["type"] == FIGURE
    assert blocks[1]["type"] == HEADING
    assert blocks[2]["type"] == PARAGRAPH


def test_stacked_independent_figures_not_merged() -> None:
    """Two same-width independent stacked figures should NOT merge, even when
    the top figure already has captions. The lower figure must be small relative
    to the top figure (≤35% of its height) to qualify as a fragment."""
    fig_top = _block(FIGURE, "", page=1, bbox=[100, 100, 700, 300])
    fig_top["attrs"] = {"captions": ["图1 地图"]}
    # Lower figure is large: height 170, which is > 300*0.35=105
    fig_bottom = _block(FIGURE, "", page=1, bbox=[100, 390, 700, 560])
    blocks = [fig_top, fig_bottom]

    reconcile_figure_captions(blocks)

    # Should remain as two independent figures
    assert len(blocks) == 2
    assert blocks[0]["type"] == FIGURE
    assert blocks[1]["type"] == FIGURE
