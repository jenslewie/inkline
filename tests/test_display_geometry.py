from __future__ import annotations

from inkline.parsers.mineru.normalize.display_geometry import (
    PageLayoutProfile,
    collect_geometry_display_group,
    display_attrs_for_group,
)
from inkline.parsers.mineru.normalize.normal_flow import process_normal_flow
from inkline.parsers.mineru.normalize.page_handlers import group_sparse_display_page
from inkline.parsers.mineru.normalize.raw_display_blocks import should_start_display_block
from inkline.parsers.mineru.schema.block_types import DISPLAY_BLOCK, LIST_ITEM, PARAGRAPH
from inkline.parsers.mineru.schema.models import IdFactory, LayoutStats, RawBlock


def _raw(
    text: str,
    bbox: list[float],
    *,
    page: int = 1,
    index: int = 0,
    raw_type: str = "paragraph",
) -> RawBlock:
    return RawBlock(page=page, index=index, raw_type=raw_type, text=text, bbox=bbox, raw={})


def _layout() -> LayoutStats:
    return LayoutStats(page_width=1000, page_height=1000, body_left=120, body_right=880)


def test_page_layout_profile_prefers_page_local_body_column() -> None:
    blocks = [
        _raw("正文段落" * 20, [90, 100, 820, 150], index=1),
        _raw("另一段正文" * 20, [92, 170, 822, 220], index=2),
        _raw("短行展示", [240, 260, 420, 285], index=3),
    ]

    profile = PageLayoutProfile.from_blocks(blocks, _layout(), page=1)

    assert profile.body_x0 == 91
    assert profile.body_x1 == 821


def test_page_layout_profile_scales_pdf_layout_to_content_bbox_space() -> None:
    layout = LayoutStats(
        page_width=1418,
        page_height=2092,
        body_left=184.34,
        body_right=1247.84,
    )
    blocks = [
        _raw("短尾行。", [100, 103, 580, 125], index=1),
        _raw("正文续页段落" * 20, [99, 163, 874, 317], index=2),
    ]

    profile = PageLayoutProfile.from_blocks(blocks, layout, page=1)

    assert 129 <= profile.body_x0 <= 131
    assert 879 <= profile.body_x1 <= 881
    assert profile.is_body_like(blocks[1])
    assert not profile.is_body_like(blocks[0])


def test_sparse_display_page_rejects_scaled_body_flow_continuation() -> None:
    layout = LayoutStats(
        page_width=1418,
        page_height=2092,
        body_left=184.34,
        body_right=1247.84,
    )
    blocks = [
        _raw("拉玛干北道，而这正是我们下一章的主题。", [100, 103, 580, 125], index=1),
        _raw(
            "笔者之前发表过两篇关于尼雅的文章：" + "正文注释内容" * 20,
            [99, 163, 874, 317],
            index=2,
        ),
    ]

    assert group_sparse_display_page(blocks, prev_major_type=None, layout=layout) is None


def test_sparse_display_page_keeps_scaled_short_line_group() -> None:
    layout = LayoutStats(
        page_width=1418,
        page_height=2092,
        body_left=184.34,
        body_right=1247.84,
    )
    blocks = [
        _raw("第一展示短行", [230, 180, 540, 205], index=1),
        _raw("第二展示短行", [230, 218, 536, 243], index=2),
    ]

    groups = group_sparse_display_page(blocks, prev_major_type=None, layout=layout)

    assert groups is not None
    assert [[block.index for block in group] for group in groups] == [[1, 2]]


def test_collects_short_line_group_from_geometry() -> None:
    blocks = [
        _raw("正文段落" * 20, [120, 100, 880, 150], index=1),
        _raw("第一展示行", [250, 220, 470, 245], index=2),
        _raw("第二展示行", [250, 252, 468, 276], index=3),
        _raw("正文恢复" * 20, [120, 330, 880, 380], index=4),
    ]

    group = collect_geometry_display_group(blocks, 1, _layout())

    assert group is not None
    assert group.layout_form == "short_line_group"
    assert [block.text for block in group.blocks] == ["第一展示行", "第二展示行"]


def test_right_aligned_group_uses_x1_stability() -> None:
    blocks = [
        _raw("正文段落" * 20, [120, 100, 880, 150], index=1),
        _raw("某年某月", [650, 260, 880, 285], index=2),
        _raw("于长安", [720, 292, 880, 315], index=3),
        _raw("正文恢复" * 20, [120, 370, 880, 420], index=4),
    ]

    group = collect_geometry_display_group(blocks, 1, _layout())
    attrs = display_attrs_for_group(group.blocks if group else [], blocks, _layout())

    assert group is not None
    assert group.alignment == "right"
    assert attrs["alignment"] == "right"
    assert attrs["style_hints"] == {"text_align": "right"}


def test_geometry_group_attrs_are_evidence_only_for_existing_groups() -> None:
    blocks = [
        _raw("正文段落" * 20, [120, 100, 880, 150], index=1),
        _raw("第一展示行", [250, 220, 470, 245], index=2),
        _raw("第二展示行", [250, 252, 468, 276], index=3),
        _raw("正文恢复" * 20, [120, 330, 880, 380], index=4),
    ]

    group = collect_geometry_display_group(blocks, 1, _layout())
    assert group is not None

    attrs = display_attrs_for_group(group.blocks, blocks, _layout())

    assert attrs["layout_form"] == "short_line_group"
    assert attrs["classification_evidence"] == ["geometry_short_line_group"]


def test_body_flow_after_figure_does_not_start_display_block() -> None:
    blocks = [
        _raw("", [133, 118, 901, 520], index=1, raw_type="image"),
        _raw(
            "这些命令都来自楼兰王，写给相当于刺史的当地最高长官cozbo。",
            [127, 553, 899, 602],
            index=2,
        ),
        _raw(
            "这件楔形木板文书是发给Tamjaka的，他是Cadhota的cozbo。",
            [126, 611, 899, 719],
            index=3,
        ),
    ]

    assert not should_start_display_block(blocks, 1, "", _layout())


def test_indented_group_after_figure_can_still_start_display_block() -> None:
    blocks = [
        _raw("正文段落" * 20, [120, 80, 880, 130], index=0),
        _raw("", [133, 160, 901, 520], index=1, raw_type="image"),
        _raw(
            "缩进展示段落第一行内容比较长但仍然不回到正文左边界。",
            [170, 553, 820, 602],
            index=2,
        ),
        _raw(
            "缩进展示段落第二行内容保持同一视觉左边界。",
            [169, 611, 818, 660],
            index=3,
        ),
        _raw("正文恢复" * 20, [120, 720, 880, 770], index=4),
    ]

    assert should_start_display_block(blocks, 2, "引文如下：", _layout())


def test_colon_intro_body_lane_long_paragraph_does_not_start_display_block() -> None:
    blocks = [
        _raw(
            "张议潮变文讲述了856年他的军队与吐蕃的几场战斗，先是渲染气氛：",
            [120, 540, 880, 585],
            index=1,
        ),
        _raw(
            "贼等不虞汉兵忽到，都无准备之心。我军遂列乌云之阵，四面急攻。"
            "蕃贼獐狂，星分南北；汉军得势，押背便追。不过五十里之间，然后说书人指着画中军队的图说。 ",
            [165, 600, 875, 655],
            index=2,
        ),
    ]

    assert not should_start_display_block(blocks, 1, blocks[0].text, _layout())


def test_colon_intro_does_not_override_single_block_geometry() -> None:
    blocks = [
        _raw("前文说明：", [120, 120, 880, 160], index=1),
        _raw("单个普通段落没有形成几何分组。", [145, 180, 850, 220], index=2),
        _raw("正文恢复" * 20, [120, 250, 880, 300], index=3),
    ]

    assert collect_geometry_display_group(blocks, 1, _layout()) is None
    assert not should_start_display_block(blocks, 1, blocks[0].text, _layout())


def test_page_bottom_set_off_uses_content_coordinate_body_lane() -> None:
    layout = LayoutStats(
        page_width=1418,
        page_height=2092,
        body_left=184.34,
        body_right=1247.84,
    )
    blocks = [
        _raw("正文段落" * 24, [100, 690, 875, 748], index=1),
        _raw("页底另起的展示段落。", [235, 790, 640, 820], index=2),
        _raw("1 页底脚注内容。", [100, 858, 875, 930], index=3, raw_type="page_footnote"),
    ]

    assert should_start_display_block(blocks, 1, blocks[0].text, layout)


def test_tight_body_flow_intro_does_not_start_following_display_group() -> None:
    blocks = [
        _raw("正文段落" * 30, [118, 401, 893, 568], index=1),
        _raw(
            "正文流中的缩进引导句保持普通字号和紧密段距。",
            [164, 576, 817, 596],
            index=2,
        ),
        _raw(
            "第一行真正的展示文本明显与引导句拉开距离。",
            [165, 635, 891, 660],
            index=3,
        ),
        _raw(
            "第二行展示文本保持同一视觉左边界。",
            [165, 668, 889, 692],
            index=4,
        ),
    ]

    assert collect_geometry_display_group(blocks, 1, _layout()) is None

    group = collect_geometry_display_group(blocks, 2, _layout())

    assert group is not None
    assert [block.index for block in group.blocks] == [3, 4]


def test_normal_flow_keeps_tight_body_intro_before_display_as_paragraph() -> None:
    blocks = [
        _raw("正文段落" * 30, [118, 401, 893, 568], index=1),
        _raw(
            "正文流中的缩进引导句保持普通字号和紧密段距。",
            [164, 576, 817, 596],
            index=2,
        ),
        _raw(
            "第一行真正的展示文本明显与引导句拉开距离。",
            [165, 635, 891, 660],
            index=3,
        ),
        _raw(
            "第二行展示文本保持同一视觉左边界。",
            [165, 668, 889, 692],
            index=4,
        ),
    ]

    out, _prev, _in_toc = process_normal_flow(IdFactory(), blocks, _layout(), None, False)

    assert [block["type"] for block in out] == [PARAGRAPH, PARAGRAPH, DISPLAY_BLOCK]
    assert out[1]["text"] == "正文流中的缩进引导句保持普通字号和紧密段距。"
    assert (
        out[2]["text"]
        == "第一行真正的展示文本明显与引导句拉开距离。\n第二行展示文本保持同一视觉左边界。"
    )


def test_normal_flow_keeps_short_tight_intro_before_display_as_paragraph() -> None:
    blocks = [
        _raw(
            "尽管玄奘肯定从一开始就打定主意要直接去见唐朝在西域的最主要对手西突厥可汗，"
            "在慧立的讲述中玄奘变成了忠诚的唐朝子民。",
            [118, 149, 889, 227],
            index=1,
        ),
        _raw(
            "无论玄奘出境时的情况如何，他的经历跟北道上的普通旅人有着显著差别。"
            "从瓜州到高昌的那一段路，玄奘是一个人走的。",
            [117, 236, 889, 401],
            index=2,
        ),
        _raw(
            "正如慧立所讲，玄奘一离开唐境，运势就变了。在丝路北道上，"
            "伊吾之后的绿洲便是高昌，当时是高昌国的国都。高昌国王麴文泰派人去迎接玄奘。",
            [116, 410, 889, 603],
            index=3,
        ),
        _raw("高昌王想劝他留下：", [164, 612, 374, 632], index=4),
        _raw(
            "自承法师名，身心欢喜，手舞足蹈，拟师至止，受弟子供养以终身。"
            "令一国人皆为师弟子，望师讲授，僧徒虽少，亦有数千，并使执经充师听众。",
            [163, 662, 886, 740],
            index=5,
        ),
        _raw(
            "玄奘不同意，二人便开始争吵。高昌王威胁要把玄奘遣送回国。玄奘",
            [163, 769, 886, 789],
            index=6,
        ),
    ]

    out, _prev, _in_toc = process_normal_flow(IdFactory(), blocks, _layout(), None, False)

    assert [block["type"] for block in out] == [
        PARAGRAPH,
        PARAGRAPH,
        PARAGRAPH,
        PARAGRAPH,
        DISPLAY_BLOCK,
        PARAGRAPH,
    ]
    assert out[3]["text"] == "高昌王想劝他留下："
    assert out[4]["text"].startswith("自承法师名")
    assert out[5]["text"].startswith("玄奘不同意")


def test_wide_set_off_blocks_around_narrow_bridge_are_collected_separately() -> None:
    layout = LayoutStats(page_width=1418, page_height=2092, body_left=184.34, body_right=1247.84)
    blocks = [
        _raw("页眉", [158, 63, 267, 78], index=7, raw_type="page_header"),
        _raw("页码", [110, 64, 140, 77], index=6, raw_type="page_number"),
        _raw("宽的页顶展示段落。", [153, 127, 874, 204], index=0),
        _raw("窄的桥接段。", [153, 242, 488, 263], index=1),
        _raw("宽的后续展示段落。", [153, 301, 864, 350], index=2),
        _raw("正文恢复到页面正文栏内。" * 6, [106, 387, 875, 437], index=3),
        _raw("后续正文继续建立页面正文栏。" * 6, [105, 445, 875, 582], index=4),
    ]

    first_group = collect_geometry_display_group(blocks, 2, layout)
    bridge_group = collect_geometry_display_group(blocks, 3, layout)
    second_group = collect_geometry_display_group(blocks, 4, layout)

    assert first_group is not None
    assert [block.index for block in first_group.blocks] == [0]
    assert bridge_group is None
    assert second_group is not None
    assert [block.index for block in second_group.blocks] == [2]


def test_wide_set_off_continuation_uses_x_axis_before_vertical_gap() -> None:
    layout = LayoutStats(page_width=1418, page_height=2092, body_left=184.34, body_right=1247.84)
    blocks = [
        _raw("正文段落建立页面正文栏。" * 12, [131, 181, 899, 347], index=1),
        _raw("缩进引导行。", [177, 355, 412, 375], index=2),
        _raw("宽的展示段落第一段。", [178, 413, 889, 462], index=3),
        _raw("宽的展示段落第二段。", [177, 471, 896, 551], index=4),
        _raw("短展示行一。", [223, 558, 454, 578], index=5),
        _raw("短展示行二。", [231, 586, 498, 607], index=6),
        _raw("正文恢复到页面正文栏内。" * 8, [128, 645, 896, 753], index=7),
    ]

    first_group = collect_geometry_display_group(blocks, 2, layout)
    second_group = collect_geometry_display_group(blocks, 3, layout)
    short_group = collect_geometry_display_group(blocks, 4, layout)

    assert first_group is not None
    assert [block.index for block in first_group.blocks] == [3]
    assert second_group is not None
    assert [block.index for block in second_group.blocks] == [4]
    assert short_group is not None
    assert [block.index for block in short_group.blocks] == [5, 6]


def test_multiline_set_off_block_after_display_gap_can_start_display_group() -> None:
    blocks = [
        _raw("正文段落" * 30, [118, 138, 895, 393], index=1),
        _raw("另一段正文" * 30, [118, 401, 893, 568], index=2),
        _raw(
            "正文流中的缩进引导句保持普通字号和紧密段距。",
            [164, 576, 817, 596],
            index=3,
        ),
        _raw(
            "第一行真正的展示文本明显与引导句拉开距离。\n"
            "第二行展示文本保存在同一个 MinerU raw block 内。",
            [165, 635, 891, 714],
            index=4,
        ),
    ]

    group = collect_geometry_display_group(blocks, 3, _layout())

    assert group is not None
    assert [block.index for block in group.blocks] == [4]


def test_tall_set_off_block_after_display_gap_can_start_display_group() -> None:
    blocks = [
        _raw("正文段落" * 30, [118, 138, 895, 393], index=1),
        _raw("另一段正文" * 30, [118, 401, 893, 568], index=2),
        _raw(
            "正文流中的缩进引导句保持普通字号和紧密段距。",
            [164, 576, 817, 596],
            index=3,
        ),
        _raw(
            "第一行真正的展示文本明显与引导句拉开距离。第二行展示文本被 MinerU 合并在同一个 raw block 内。",
            [165, 635, 891, 714],
            index=4,
        ),
    ]

    group = collect_geometry_display_group(blocks, 3, _layout())

    assert group is not None
    assert [block.index for block in group.blocks] == [4]


def test_geometry_display_group_wins_before_cjk_list_item_classification() -> None:
    blocks = [
        _raw("正文段落" * 20, [120, 100, 880, 150], index=1),
        _raw("一、展示条款", [250, 220, 470, 245], index=2),
        _raw("二、展示条款", [250, 252, 468, 276], index=3),
        _raw("正文恢复" * 20, [120, 330, 880, 380], index=4),
    ]

    out, _prev, _in_toc = process_normal_flow(IdFactory(), blocks, _layout(), None, False)

    assert [block["type"] for block in out] == [PARAGRAPH, DISPLAY_BLOCK, PARAGRAPH]
    assert out[1]["text"] == "一、展示条款\n二、展示条款"


def test_cjk_era_paragraph_is_not_promoted_to_list_item_by_text_prefix() -> None:
    blocks = [
        _raw(
            "十七、八世纪进入新疆的商队很少,也很少有人离开那里。"
            "一些新疆、甘肃的穆斯林常常为了向苏非大师学习前往中东。",
            [120, 100, 880, 170],
            index=1,
        )
    ]

    out, _prev, _in_toc = process_normal_flow(IdFactory(), blocks, _layout(), None, False)

    assert [block["type"] for block in out] == [PARAGRAPH]
    assert out[0]["attrs"]["raw_type"] == "paragraph"


def test_raw_mineru_list_still_expands_to_list_items() -> None:
    blocks = [
        _raw(
            "",
            [120, 100, 880, 170],
            index=1,
            raw_type="list",
        )
    ]
    blocks[0].raw = {
        "content": {
            "list_type": "ordered",
            "list_items": [
                {"item_content": [{"type": "text", "content": "一、真实列表项"}]},
                {"item_content": [{"type": "text", "content": "二、另一个列表项"}]},
            ],
        }
    }

    out, _prev, _in_toc = process_normal_flow(IdFactory(), blocks, _layout(), None, False)

    assert [block["type"] for block in out] == [LIST_ITEM, LIST_ITEM]
    assert [block["attrs"]["raw_type"] for block in out] == ["list_item", "list_item"]
