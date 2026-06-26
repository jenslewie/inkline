"""Regression tests for geometry-first display block reconciliation."""

from __future__ import annotations

from inkline.parsers.mineru.reconcile.cross_page import merge_cross_page_paragraphs
from inkline.parsers.mineru.reconcile.display_block.body_paragraph_split import (
    reconcile_display_block_body_paragraph_split,
)
from inkline.parsers.mineru.reconcile.display_block.cleanup import (
    reconcile_display_block_cleanup_structures,
)
from inkline.parsers.mineru.reconcile.display_block.footnote_interruptions import (
    reconcile_display_block_across_footnote_interruptions,
)
from inkline.parsers.mineru.reconcile.display_block.layout import reconcile_display_blocks
from inkline.parsers.mineru.reconcile.display_block.right_align import (
    reconcile_right_aligned_terminal_blocks,
)
from inkline.parsers.mineru.reconcile.layout_helpers import (
    _display_block_layout,
    _is_body_paragraph_layout,
)
from inkline.parsers.mineru.schema.block_types import DISPLAY_BLOCK, FIGURE, PARAGRAPH
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


def test_layout_helpers_use_scaled_body_metrics_for_canonical_bboxes() -> None:
    layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
    body = _block(
        PARAGRAPH,
        "正文段落在 canonical bbox 坐标系中回到正文栏。",
        page=1,
        bbox=[95, 597, 867, 646],
    )

    assert not _display_block_layout(body, layout, coord_width=1000.0)
    assert _is_body_paragraph_layout(body, layout, coord_width=1000.0)


# ---------------------------------------------------------------------------
# Task 1: Geometry-only paragraph/display promotion guards
# ---------------------------------------------------------------------------


class TestGeometryPromotion:
    def test_colon_introduced_body_lane_long_paragraph_not_promoted(self) -> None:
        intro = _block(
            PARAGRAPH,
            "张议潮变文讲述了856年他的军队与吐蕃的几场战斗，先是渲染气氛：",
            page=1,
            bbox=[120, 540, 880, 585],
        )
        body = _block(
            PARAGRAPH,
            "贼等不虞汉兵忽到，都无准备之心。我军遂列乌云之阵，四面急攻。"
            "蕃贼獐狂，星分南北；汉军得势，押背便追。不过五十里之间，然后说书人指着画中军队的图说："
            "“煞戮横尸遍野处。”",
            page=1,
            bbox=[165, 600, 875, 655],
        )
        blocks = [intro, body]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert body["type"] == PARAGRAPH

    def test_colon_does_not_promote_single_block_without_geometry_group(self) -> None:
        intro = _block(PARAGRAPH, "前文说明：", page=1, bbox=[120, 120, 880, 160])
        body = _block(
            PARAGRAPH,
            "单个普通段落没有形成几何分组。",
            page=1,
            bbox=[145, 180, 850, 220],
        )
        resumed = _block(PARAGRAPH, "正文恢复" * 20, page=1, bbox=[120, 250, 880, 300])
        blocks = [intro, body, resumed]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert body["type"] == PARAGRAPH


# ---------------------------------------------------------------------------
# Task 2: Display run stop conditions for body-text paragraphs
# ---------------------------------------------------------------------------


class TestDisplayRunStopConditions:
    def test_body_paragraph_not_absorbed_into_display(self) -> None:
        """A body-width paragraph at body indent should NOT be absorbed into
        a preceding display block during same-page continuation."""
        display = _block(DISPLAY_BLOCK, "这是一段引文内容。", page=1, bbox=[250, 200, 520, 240])
        body = _block(
            PARAGRAPH, "这是正文叙事段落，宽度接近正文宽度。", page=1, bbox=[120, 260, 880, 300]
        )
        blocks = [display, body]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert body["type"] == PARAGRAPH

    def test_embedded_short_dialogue_group_split_from_body_paragraph(self) -> None:
        block = _block(
            PARAGRAPH,
            "正文说明这些对话表现了冲突：\n"
            "不要生我的气。\n"
            "我不会扯你的头发。\n"
            "你要是说让人不愉快的话\n"
            "后续正文恢复，继续说明手册内容，并且回到正常正文宽度的长段落，"
            "这一行不再属于展示性短行组。",
            page=1,
            bbox=[120, 400, 880, 620],
            block_id="b_body",
            attrs={
                "split_from_display_block_id": "b_display",
                "layout_form": "short_line_group",
            },
        )
        block["source"]["spans"] = [
            {"page": 1, "bbox": [120, 400, 880, 450], "block_id": "intro"},
            {"page": 1, "bbox": [210, 470, 470, 540], "block_id": "dialogue"},
            {"page": 1, "bbox": [120, 560, 880, 620], "block_id": "body"},
        ]
        blocks = [block]

        reconcile_display_block_body_paragraph_split(blocks, DEFAULT_LAYOUT)

        assert [b["type"] for b in blocks] == [PARAGRAPH, DISPLAY_BLOCK, PARAGRAPH]
        assert blocks[0]["text"] == "正文说明这些对话表现了冲突："
        assert blocks[1]["text"] == "不要生我的气。\n我不会扯你的头发。\n你要是说让人不愉快的话"
        assert blocks[1]["source"]["bbox"] == [210, 470, 470, 540]
        assert blocks[2]["text"] == (
            "后续正文恢复，继续说明手册内容，并且回到正常正文宽度的长段落，"
            "这一行不再属于展示性短行组。"
        )

    def test_embedded_short_group_split_does_not_require_colon_intro(self) -> None:
        block = _block(
            PARAGRAPH,
            "正文说明这些对话表现了冲突\n"
            "不要生我的气。\n"
            "我不会扯你的头发。\n"
            "你要是说让人不愉快的话\n"
            "后续正文恢复，继续说明手册内容，并且回到正常正文宽度的长段落，"
            "这一行不再属于展示性短行组。",
            page=1,
            bbox=[120, 400, 880, 620],
            block_id="b_body",
            attrs={
                "split_from_display_block_id": "b_display",
                "layout_form": "short_line_group",
            },
        )
        block["source"]["spans"] = [
            {"page": 1, "bbox": [120, 400, 880, 450], "block_id": "intro"},
            {"page": 1, "bbox": [210, 470, 470, 540], "block_id": "dialogue"},
            {"page": 1, "bbox": [120, 560, 880, 620], "block_id": "body"},
        ]
        blocks = [block]

        reconcile_display_block_body_paragraph_split(blocks, DEFAULT_LAYOUT)

        assert [b["type"] for b in blocks] == [PARAGRAPH, DISPLAY_BLOCK, PARAGRAPH]
        assert blocks[0]["text"] == "正文说明这些对话表现了冲突"
        assert blocks[1]["text"] == "不要生我的气。\n我不会扯你的头发。\n你要是说让人不愉快的话"

    def test_embedded_short_group_split_partitions_inline_metadata(self) -> None:
        after_text = (
            "后续正文恢复，继续说明手册内容，并且回到正常正文宽度的长段落，"
            "这一行不再属于展示性短行组。"
        )
        block = _block(
            PARAGRAPH,
            f"正文说明这些对话表现了冲突：\n不要生我的气。\n我不会扯你的头发。\n{after_text}",
            page=1,
            bbox=[120, 400, 880, 620],
            block_id="b_body",
            attrs={
                "split_from_display_block_id": "b_display",
                "layout_form": "short_line_group",
                "inline_runs": [
                    {
                        "type": "text",
                        "text": "正文说明这些对话表现了冲突：\n不要生我的气。\n我不会扯你的头发。\n",
                    },
                    {"type": "text", "text": after_text},
                    {"type": "note_ref", "marker": "1", "target_note_id": "n1"},
                ],
                "note_refs": [{"marker": "1", "target_note_id": "n1"}],
            },
        )
        block["source"]["spans"] = [
            {"page": 1, "bbox": [120, 400, 880, 450], "block_id": "intro"},
            {"page": 1, "bbox": [210, 470, 470, 500], "block_id": "dialogue_1"},
            {"page": 1, "bbox": [210, 510, 470, 540], "block_id": "dialogue_2"},
            {"page": 1, "bbox": [120, 560, 880, 620], "block_id": "body"},
        ]
        blocks = [block]

        reconcile_display_block_body_paragraph_split(blocks, DEFAULT_LAYOUT)

        assert [b["type"] for b in blocks] == [PARAGRAPH, DISPLAY_BLOCK, PARAGRAPH]
        assert (blocks[0].get("attrs") or {}).get("note_refs") in (None, [])
        assert (blocks[1].get("attrs") or {}).get("note_refs") in (None, [])
        assert (blocks[2].get("attrs") or {}).get("note_refs") == [
            {"marker": "1", "target_note_id": "n1"}
        ]
        assert blocks[0]["source"]["spans"] == [
            {"page": 1, "bbox": [120, 400, 880, 450], "block_id": "intro"}
        ]
        assert blocks[1]["source"]["spans"] == [
            {"page": 1, "bbox": [210, 470, 470, 500], "block_id": "dialogue_1"},
            {"page": 1, "bbox": [210, 510, 470, 540], "block_id": "dialogue_2"},
        ]
        assert blocks[2]["source"]["spans"] == [
            {"page": 1, "bbox": [120, 560, 880, 620], "block_id": "body"}
        ]

    def test_embedded_short_group_split_partitions_source_without_line_aligned_spans(
        self,
    ) -> None:
        block = _block(
            PARAGRAPH,
            "正文说明这些对话表现了冲突：\n"
            "不要生我的气。\n"
            "我不会扯你的头发。\n"
            "你要是说让人不愉快的话\n"
            "后续正文恢复，继续说明手册内容，并且回到正常正文宽度的长段落，"
            "这一行不再属于展示性短行组。",
            page=1,
            bbox=[120, 400, 880, 620],
            block_id="b_body",
            attrs={
                "split_from_display_block_id": "b_display",
                "layout_form": "short_line_group",
            },
        )
        block["source"]["spans"] = [
            {"page": 1, "bbox": [120, 400, 880, 450], "block_id": "intro"},
            {"page": 1, "bbox": [210, 470, 470, 540], "block_id": "dialogue"},
            {"page": 1, "bbox": [120, 560, 880, 620], "block_id": "body"},
        ]
        blocks = [block]

        reconcile_display_block_body_paragraph_split(blocks, DEFAULT_LAYOUT)

        assert [b["type"] for b in blocks] == [PARAGRAPH, DISPLAY_BLOCK, PARAGRAPH]
        assert [span["block_id"] for span in blocks[0]["source"]["spans"]] == ["intro"]
        assert [span["block_id"] for span in blocks[1]["source"]["spans"]] == ["dialogue"]
        assert [span["block_id"] for span in blocks[2]["source"]["spans"]] == ["body"]

    def test_split_short_dialogue_group_merges_across_footnote(self) -> None:
        body = _block(
            PARAGRAPH,
            "正文说明这些对话表现了冲突：\n"
            "不要生我的气。\n"
            "我不会扯你的头发。\n"
            "你要是说让人不愉快的话",
            page=1,
            bbox=[120, 650, 880, 847],
            block_id="b_body",
            attrs={
                "split_from_display_block_id": "b_display",
                "layout_form": "short_line_group",
            },
        )
        body["source"]["spans"] = [
            {"page": 1, "bbox": [120, 650, 880, 732], "block_id": "intro"},
            {"page": 1, "bbox": [210, 770, 475, 847], "block_id": "dialogue"},
        ]
        footnote = _block(
            "footnote",
            "1 注释。",
            page=1,
            bbox=[120, 890, 880, 920],
        )
        continuation = _block(
            DISPLAY_BLOCK,
            "我就生气了。\n有些甚至提到了性：\n他爱许多女人。\n他做爱。\n"
            "有些对话让人可以猜出手册使用者的身份：",
            page=2,
            bbox=[139, 106, 595, 331],
        )
        continuation["source"]["spans"] = [
            {"page": 2, "bbox": [188, 106, 321, 125], "block_id": "continuation"},
            {"page": 2, "bbox": [139, 164, 351, 184], "block_id": "next_intro"},
            {"page": 2, "bbox": [187, 223, 345, 243], "block_id": "next_display_1"},
            {"page": 2, "bbox": [188, 253, 274, 271], "block_id": "next_display_2"},
            {"page": 2, "bbox": [139, 310, 595, 331], "block_id": "next_intro_2"},
        ]
        blocks = [body, footnote, continuation]

        reconcile_display_block_cleanup_structures(blocks, DEFAULT_LAYOUT)

        assert [b["type"] for b in blocks] == [
            PARAGRAPH,
            DISPLAY_BLOCK,
            "footnote",
            PARAGRAPH,
            DISPLAY_BLOCK,
            PARAGRAPH,
        ]
        assert (
            blocks[1]["text"]
            == "不要生我的气。\n我不会扯你的头发。\n你要是说让人不愉快的话\n我就生气了。"
        )
        assert blocks[1]["source"]["bbox"] == [188, 106, 475, 847]
        assert blocks[3]["text"] == "有些甚至提到了性："
        assert blocks[4]["text"] == "他爱许多女人。\n他做爱。"
        assert blocks[5]["text"] == "有些对话让人可以猜出手册使用者的身份："

    def test_footnote_interruption_split_partitions_inline_metadata(self) -> None:
        display = _block(
            DISPLAY_BLOCK,
            "页尾展示行",
            page=1,
            bbox=[188, 770, 321, 805],
        )
        footnote = _block("footnote", "1 注释。", page=1, bbox=[120, 890, 880, 920])
        continuation = _block(
            DISPLAY_BLOCK,
            "我就生气了。\n后续展示行带脚注。",
            page=2,
            bbox=[188, 106, 420, 170],
            block_id="b_cont",
            attrs={
                "inline_runs": [
                    {"type": "text", "text": "我就生气了。\n后续展示行带脚注。"},
                    {"type": "note_ref", "marker": "2", "target_note_id": "n2"},
                ],
                "note_refs": [{"marker": "2", "target_note_id": "n2"}],
            },
        )
        continuation["source"]["spans"] = [
            {"page": 2, "bbox": [188, 106, 321, 125], "block_id": "line_1"},
            {"page": 2, "bbox": [188, 145, 420, 170], "block_id": "line_2"},
        ]
        blocks = [display, footnote, continuation]

        reconcile_display_block_across_footnote_interruptions(blocks, DEFAULT_LAYOUT)

        assert len(blocks) == 3
        assert blocks[0]["text"] == "页尾展示行\n我就生气了。"
        assert (blocks[0].get("attrs") or {}).get("note_refs") in (None, [])
        assert blocks[2]["text"] == "后续展示行带脚注。"
        assert (blocks[2].get("attrs") or {}).get("note_refs") == [
            {"marker": "2", "target_note_id": "n2"}
        ]

    def test_footnote_interruption_lane_match_uses_scaled_width(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        display = _block(
            DISPLAY_BLOCK,
            "页尾展示行",
            page=1,
            bbox=[130, 770, 300, 805],
        )
        footnote = _block("footnote", "1 注释。", page=1, bbox=[95, 890, 888, 920])
        continuation = _block(
            DISPLAY_BLOCK,
            "下一页展示续行",
            page=2,
            bbox=[180, 106, 350, 130],
        )
        body = _block(
            PARAGRAPH,
            "正文恢复，提供下一页 canonical 坐标宽度。",
            page=2,
            bbox=[95, 300, 900, 350],
        )
        blocks = [display, footnote, continuation, body]

        reconcile_display_block_across_footnote_interruptions(blocks, layout)

        assert len(blocks) == 4
        assert blocks[0]["text"] == "页尾展示行"
        assert blocks[2]["text"] == "下一页展示续行"

    def test_footnote_interruption_merges_wide_set_off_continuation_by_right_edge(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        display = _block(
            DISPLAY_BLOCK,
            "页尾宽展示段落。",
            page=253,
            bbox=[170, 762, 888, 812],
        )
        footnote = _block(
            "footnote",
            "1 注释。",
            page=253,
            bbox=[119, 862, 888, 916],
        )
        continuation = _block(
            DISPLAY_BLOCK,
            "页顶宽展示续段。",
            page=254,
            bbox=[131, 106, 852, 185],
        )
        body = _block(
            PARAGRAPH,
            "正文恢复到页面正文栏内。",
            page=254,
            bbox=[81, 223, 855, 390],
        )
        note = _block(
            "footnote",
            "1 页底注释。",
            page=254,
            bbox=[81, 702, 853, 736],
            block_id="b_note",
            attrs={"referenced_by": [continuation["block_id"]]},
        )
        blocks = [display, footnote, continuation, body, note]

        reconcile_display_block_across_footnote_interruptions(blocks, layout)

        assert len(blocks) == 4
        assert blocks[0]["type"] == DISPLAY_BLOCK
        assert blocks[0]["text"] == "页尾宽展示段落。页顶宽展示续段。"
        assert blocks[1]["type"] == "footnote"
        assert blocks[2]["type"] == PARAGRAPH
        assert blocks[3]["attrs"]["referenced_by"] == [display["block_id"]]

    def test_footnote_interruption_merges_by_geometry_not_text_prefix(self) -> None:
        display = _block(
            DISPLAY_BLOCK,
            "展示第一行\n——署名行",
            page=1,
            bbox=[188, 770, 340, 835],
        )
        footnote = _block("footnote", "1 注释。", page=1, bbox=[120, 890, 880, 920])
        continuation = _block(
            DISPLAY_BLOCK,
            "下一页展示续行",
            page=2,
            bbox=[188, 106, 340, 130],
        )
        blocks = [display, footnote, continuation]

        reconcile_display_block_across_footnote_interruptions(blocks, DEFAULT_LAYOUT)

        assert len(blocks) == 2
        assert blocks[0]["text"] == "展示第一行\n——署名行\n下一页展示续行"

    def test_display_continuation_aligned_narrow_absorbed(self) -> None:
        """A narrow, indented paragraph aligned with the display block should
        be absorbed as continuation."""
        display = _block(DISPLAY_BLOCK, "引文第一行。", page=1, bbox=[250, 200, 520, 240])
        cont = _block(PARAGRAPH, "引文第二行。", page=1, bbox=[250, 260, 510, 290])
        blocks = [display, cont]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        # Should be merged into one display block
        assert len(blocks) == 1
        assert blocks[0]["type"] == DISPLAY_BLOCK

    def test_first_line_body_indent_after_display_is_not_absorbed(self) -> None:
        display = _block(
            DISPLAY_BLOCK,
            "自承法师名，身心欢喜，手舞足蹈，拟师至止，受弟子供养以终身。"
            "令一国人皆为师弟子，望师讲授，僧徒虽少，亦有数千，并使执经充师听众。",
            page=127,
            bbox=[163, 662, 886, 740],
        )
        body = _block(
            PARAGRAPH,
            "玄奘不同意，二人便开始争吵。高昌王威胁要把玄奘遣送回国。玄奘",
            page=127,
            bbox=[163, 769, 886, 789],
        )
        blocks = [display, body]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert len(blocks) == 2
        assert display["type"] == DISPLAY_BLOCK
        assert body["type"] == PARAGRAPH

    def test_single_line_between_display_and_body_uses_vertical_context(self) -> None:
        display = _block(
            DISPLAY_BLOCK,
            "我们的人把牲口都丢了。衣服也丢了。什么时候命令能来？",
            page=296,
            bbox=[147, 284, 870, 392],
        )
        single_line = _block(
            PARAGRAPH,
            "一封随从的信解释了牲口是怎么丢的。",
            page=296,
            bbox=[147, 430, 575, 450],
        )
        body = _block(
            PARAGRAPH,
            "不让王子们上路的统治者认为王子们与随他们一起赶路的僧人很不一样。",
            page=296,
            bbox=[100, 459, 873, 654],
        )
        blocks = [display, single_line, body]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert [b["type"] for b in blocks] == [DISPLAY_BLOCK, PARAGRAPH, PARAGRAPH]
        assert blocks[1]["text"] == "一封随从的信解释了牲口是怎么丢的。"

    def test_footnote_interruption_does_not_absorb_body_width_paragraph(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        display = _block(
            DISPLAY_BLOCK,
            "页尾展示行",
            page=1,
            bbox=[260, 760, 520, 790],
        )
        footnote = _block(
            "footnote",
            "1 注释内容。",
            page=1,
            bbox=[112, 900, 888, 930],
        )
        body = _block(
            PARAGRAPH,
            "下一页恢复正文叙述，宽度接近正文栏，不应该被跨脚注合并进展示块。",
            page=2,
            bbox=[126, 110, 899, 160],
        )
        blocks = [display, footnote, body]

        reconcile_display_block_across_footnote_interruptions(blocks, layout)

        assert len(blocks) == 3
        assert body["type"] == PARAGRAPH

    def test_float_boundary_blocks_intro_from_promoting_body_resume(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        intro = _block(
            DISPLAY_BLOCK,
            "国王陛下亲书，命令某官如下：",
            page=70,
            bbox=[145, 600, 870, 680],
        )
        figure = _block(
            FIGURE,
            "",
            page=71,
            bbox=[133, 118, 901, 520],
        )
        body = _block(
            PARAGRAPH,
            "图后的正文恢复，回到页面正文栏内，宽度接近正文栏，不应该被冒号上下文提升。",
            page=71,
            bbox=[127, 553, 899, 602],
        )
        body_next = _block(
            PARAGRAPH,
            "后续正文仍然保持相同左边界和宽度，证明这里已经恢复正常正文流。",
            page=71,
            bbox=[126, 611, 899, 719],
        )
        blocks = [intro, figure, body, body_next]

        reconcile_display_blocks(blocks, layout)

        assert body["type"] == PARAGRAPH
        assert body_next["type"] == PARAGRAPH

    def test_intro_still_promotes_immediate_indented_display(self) -> None:
        intro = _block(
            PARAGRAPH,
            "下面引用如下：",
            page=1,
            bbox=[120, 200, 880, 240],
        )
        display = _block(
            PARAGRAPH,
            "缩进的展示文字保持在正文栏内侧。",
            page=1,
            bbox=[250, 270, 780, 320],
        )
        body = _block(
            PARAGRAPH,
            "正文恢复，回到正文左边界。",
            page=1,
            bbox=[120, 360, 880, 410],
        )
        blocks = [intro, display, body]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert display["type"] == DISPLAY_BLOCK
        assert body["type"] == PARAGRAPH

    def test_intro_page_bottom_display_before_float_not_merged_into_body_resume(
        self,
    ) -> None:
        layout = _layout(body_left=100, body_right=880, page_width=1000)
        intro = _block(
            PARAGRAPH,
            "张议潮变文讲述了856年他的军队与吐蕃的几场战斗，先是渲染气氛：",
            page=1,
            bbox=[100, 600, 880, 640],
        )
        quote = _block(
            PARAGRAPH,
            "贼等不虞汉兵忽到，都无准备之心。我军遂列乌云之阵，四面急攻。"
            "蕃贼獐狂，星分南北；汉军得势，押背便追。不过五十里之间，",
            page=1,
            bbox=[141, 850, 866, 910],
        )
        figure = _block(
            FIGURE,
            "",
            page=2,
            bbox=[100, 50, 900, 520],
        )
        body = _block(
            PARAGRAPH,
            "然后说书人指着画中军队的图说：“煞戮横尸遍野处。” "
            "虽然这类画无一保留下来，但是一幅861年的壁画描绘了归义军的出行。",
            page=2,
            bbox=[100, 600, 880, 650],
        )
        blocks = [intro, quote, figure, body]

        merge_cross_page_paragraphs(
            blocks,
            source_pdf=None,
            layout=layout,
            allow_missing_pdf_text=True,
        )
        reconcile_display_blocks(blocks, layout)
        reconcile_display_block_cleanup_structures(blocks, layout)

        assert [block["type"] for block in blocks] == [
            PARAGRAPH,
            DISPLAY_BLOCK,
            FIGURE,
            PARAGRAPH,
        ]
        assert blocks[1]["text"].startswith("贼等不虞汉兵忽到")
        assert blocks[3]["text"].startswith("然后说书人指着画中军队的图说")

    def test_page_local_set_off_before_float_not_merged_with_body_resume(
        self,
    ) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        body_before = _block(
            PARAGRAPH,
            "张议潮变文讲述了856年他的军队与吐蕃的几场战斗，先是渲染气氛：",
            page=252,
            bbox=[95, 597, 867, 646],
        )
        quote = _block(
            PARAGRAPH,
            "贼等不虞汉兵忽到，都无准备之心。我军遂列乌云之阵，四面急攻。"
            "蕃贼獐狂，星分南北；汉军得势，押背便追。不过五十里之间，",
            page=252,
            bbox=[141, 684, 866, 734],
        )
        footnote = _block("footnote", "1 注释。", page=252, bbox=[94, 786, 865, 912])
        figure = _block(FIGURE, "", page=253, bbox=[123, 109, 892, 559])
        body_after = _block(
            PARAGRAPH,
            "然后说书人指着画中军队的图说：“煞戮横尸遍野处。” "
            "虽然这类画无一保留下来，但是一幅861年的壁画描绘了归义军的出行。",
            page=253,
            bbox=[123, 586, 889, 636],
        )
        blocks = [body_before, quote, footnote, figure, body_after]

        merge_cross_page_paragraphs(
            blocks,
            source_pdf=None,
            layout=layout,
            allow_missing_pdf_text=True,
        )
        reconcile_display_blocks(blocks, layout)

        assert [block["type"] for block in blocks] == [
            PARAGRAPH,
            DISPLAY_BLOCK,
            "footnote",
            FIGURE,
            PARAGRAPH,
        ]
        assert blocks[1]["text"].startswith("贼等不虞汉兵忽到")

    def test_tight_body_flow_before_float_body_resume_not_promoted(
        self,
    ) -> None:
        body_before = _block(
            PARAGRAPH,
            "编号为M8的墓葬时代稍晚，墓主也是一对夫妇。其中出土了带汉字的织物和一个朴素的陶罐。",
            page=63,
            bbox=[115, 654, 885, 791],
        )
        body_intro = _block(
            PARAGRAPH,
            "营盘（在楼兰西南）遗址一座同时代的墓葬跟尼雅形成了鲜明对比。",
            page=63,
            bbox=[163, 800, 881, 819],
        )
        footnote = _block("footnote", "1 注释。", page=63, bbox=[112, 867, 873, 920])
        figure = _block(FIGURE, "", page=64, bbox=[101, 101, 869, 657])
        body_after = _block(
            PARAGRAPH,
            "死者用羊毛制品裹身，而不是棉布或者丝绸。死者为男性，身着一件红色羊皮袄。",
            page=64,
            bbox=[99, 683, 872, 822],
        )
        blocks = [body_before, body_intro, footnote, figure, body_after]

        merge_cross_page_paragraphs(
            blocks,
            source_pdf=None,
            layout=DEFAULT_LAYOUT,
            allow_missing_pdf_text=True,
        )
        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert body_intro["type"] == PARAGRAPH
        assert not (body_intro.get("attrs") or {}).get("display_boundary_after_float_body_resume")


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

    def test_scaled_layout_splits_body_tail_from_display_block(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        block = _block(
            DISPLAY_BLOCK,
            (
                "你好吗？\n很好，谢谢！\n"
                "对话中也提到了其他的地方：印度、中国、藏区、甘州（甘州回鹘汗国的首都，今甘肃张掖）。"
                "手册教人如何买马买草料，如何要针线，以及如何让人给自己洗衣服。"
                "这些连续说明文字显然已经回到正文叙述。"
            ),
            page=291,
            bbox=[90, 106, 887, 914],
        )
        blocks = [block]

        reconcile_display_block_body_paragraph_split(blocks, layout)

        assert len(blocks) == 2
        assert blocks[0]["type"] == DISPLAY_BLOCK
        assert blocks[1]["type"] == PARAGRAPH

    def test_set_off_display_spans_are_not_split_by_long_lines(self) -> None:
        layout = _layout()
        before = _block(
            PARAGRAPH,
            "正文段落在页面正文栏内，提供页内正文左边界。",
            page=54,
            bbox=[118, 401, 893, 568],
        )
        display = _block(
            DISPLAY_BLOCK,
            (
                "在一片低矮的沙丘中，出现了古代果树枯萎的树干。继续往北走\n"
                "了不到两英里，我很快就看到了最先出现的两间旧屋。\n"
                "向北走约两英里，越过一些相当高的沙包，我来到一个用土坯修建的废墟上，"
                "这是阿卜杜拉在克里雅作为一座炮台早已介绍给我的。不出所料，这是一座小佛塔的遗迹，"
                "大部分都埋在一个高沙岗的斜坡下面……\n"
                "当我第一次在这些古代民居默默无言的见证者中就寝时，一直在想木板文书还有多少有待发现。"
            ),
            page=54,
            bbox=[151, 117, 891, 714],
        )
        display["source"]["pages"] = [54, 55]
        display["source"]["spans"] = [
            {"page": 54, "bbox": [165, 635, 891, 714], "block_id": "b000315"},
            {"page": 55, "bbox": [154, 117, 397, 136], "block_id": "b000318"},
            {"page": 55, "bbox": [151, 146, 877, 252], "block_id": "b000319"},
            {"page": 55, "bbox": [151, 262, 875, 340], "block_id": "b000320"},
        ]
        after = _block(
            PARAGRAPH,
            "正文恢复，回到页面正文栏内。",
            page=55,
            bbox=[103, 378, 875, 456],
        )
        blocks = [before, display, after]

        reconcile_display_block_body_paragraph_split(blocks, layout)

        assert len(blocks) == 3
        assert display["type"] == DISPLAY_BLOCK
        assert "向北走约两英里" in display["text"]

    def test_page_local_indented_display_block_without_spans_is_not_split(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        before = _block(
            PARAGRAPH,
            "正文段落在页面正文栏内，提供页内正文左边界。",
            page=91,
            bbox=[103, 178, 892, 316],
        )
        display = _block(
            DISPLAY_BLOCK,
            (
                "忽然一阵剧烈的像打雷般的巨响从我们头顶滚过。……这时灾难发生了，"
                "一切都是那么快，仅仅瞬息之间。我看见工人们突然趴在陡峭的山坡上，"
                "就在这一瞬间，大量的岩石铺天盖地朝我们砸下来。\n"
                "这时，我向着山谷河流的方向望去，只见河水剧烈地荡来荡去，拍打着堤岸。"
                "在山谷顺着河流的远方突然升起了巨大的尘土，像云，更像巨大的柱子，"
                "一直升到无际的天空。同时大地开始震动。"
            ),
            page=91,
            bbox=[166, 353, 890, 635],
        )
        after = _block(
            PARAGRAPH,
            "正文恢复，回到页面正文栏内。",
            page=91,
            bbox=[120, 672, 888, 751],
        )
        blocks = [before, display, after]

        reconcile_display_block_body_paragraph_split(blocks, layout)

        assert len(blocks) == 3
        assert display["type"] == DISPLAY_BLOCK
        assert "这时，我向着山谷河流的方向望去" in display["text"]

    def test_short_body_tail_after_note_boundary_splits_from_indented_display(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        quote_text = (
            "我们的人把牲口都丢了。衣服也丢了。……没人能跟我们前往甘州。"
            "我们怎么能到得了朔方呢？我们既没有贡品也没有国书给中国皇帝。"
            "好多人都死了。我们没有吃的。什么时候命令能来？"
        )
        tail_text = "一封随从的信解释了牲口是怎么丢的。"
        before = _block(
            PARAGRAPH,
            "正文段落在页面正文栏内，提供页内正文左边界。",
            page=296,
            bbox=[100, 108, 874, 247],
        )
        display = _block(
            DISPLAY_BLOCK,
            f"{quote_text}\n{tail_text}",
            page=296,
            bbox=[147, 284, 870, 450],
            attrs={
                "inline_runs": [
                    {"type": "text", "text": quote_text},
                    {"type": "note_ref", "marker": "1"},
                    {"type": "text", "text": f"\n{tail_text}"},
                ],
            },
        )
        display["source"]["spans"] = [
            {"page": 296, "bbox": [147, 284, 870, 405], "block_id": "display_quote"},
            {"page": 296, "bbox": [100, 417, 873, 450], "block_id": "body_tail"},
        ]
        after = _block(
            PARAGRAPH,
            "正文恢复，回到页面正文栏内。",
            page=296,
            bbox=[100, 459, 873, 654],
        )
        blocks = [before, display, after]

        reconcile_display_block_body_paragraph_split(blocks, layout)

        assert len(blocks) == 4
        assert blocks[1]["type"] == DISPLAY_BLOCK
        assert blocks[2]["type"] == PARAGRAPH
        assert tail_text in blocks[2]["text"]

    def test_body_lane_span_tail_still_splits_from_display_block(self) -> None:
        layout = _layout()
        before = _block(
            PARAGRAPH,
            "正文段落在页面正文栏内，提供页内正文左边界。",
            page=1,
            bbox=[102, 100, 878, 160],
        )
        block = _block(
            DISPLAY_BLOCK,
            (
                "引文开头\n"
                "这是一段非常长的正文叙事段落它显然已经回到正文栏，长度远超display阈值，"
                "因为它在几何上与正文左边界一致，并且宽度也接近正文宽度。"
                "这些连续说明文字继续保持正文排版，应当被拆回 paragraph。"
            ),
            page=1,
            bbox=[102, 200, 878, 320],
        )
        block["source"]["spans"] = [
            {"page": 1, "bbox": [150, 200, 650, 230], "block_id": "display_prefix"},
            {"page": 1, "bbox": [102, 246, 878, 320], "block_id": "body_tail"},
        ]
        blocks = [before, block]

        reconcile_display_block_body_paragraph_split(blocks, layout)

        assert len(blocks) == 3
        assert blocks[1]["type"] == DISPLAY_BLOCK
        assert blocks[2]["type"] == PARAGRAPH
        assert "正文叙事段落" in blocks[2]["text"]

    def test_same_page_display_continuation_body_indent_tail_splits(self) -> None:
        before = _block(
            PARAGRAPH,
            "正如慧立所讲，玄奘一离开唐境，运势就变了。在丝路北道上，"
            "伊吾之后的绿洲便是高昌，当时是高昌国的国都。",
            page=127,
            bbox=[116, 410, 889, 603],
        )
        display = _block(
            DISPLAY_BLOCK,
            (
                "自承法师名，身心欢喜，手舞足蹈，拟师至止，受弟子供养以终身。"
                "令一国人皆为师弟子，望师讲授，僧徒虽少，亦有数千，并使执经充师听众。\n"
                "玄奘不同意，二人便开始争吵。高昌王威胁要把玄奘遣送回国。玄奘"
            ),
            page=127,
            bbox=[163, 662, 886, 789],
            attrs={"merge_reason": "same_page_display_block_continuation"},
        )
        display["source"]["spans"] = [
            {"page": 127, "bbox": [163, 662, 886, 740], "block_id": "display"},
            {"page": 127, "bbox": [163, 769, 886, 789], "block_id": "body_tail"},
        ]
        footnote = _block("footnote", "1 注释。", page=127, bbox=[78, 894, 847, 929])
        figure = _block(FIGURE, "", page=128, bbox=[81, 227, 850, 550])
        next_body = _block(
            PARAGRAPH,
            "坚持要走，国王就把玄奘锁在宫里，并每天亲自给他送饭。",
            page=128,
            bbox=[80, 576, 847, 655],
        )
        blocks = [before, display, footnote, figure, next_body]

        reconcile_display_block_body_paragraph_split(blocks, DEFAULT_LAYOUT)

        assert len(blocks) == 5
        assert blocks[1]["type"] == DISPLAY_BLOCK
        assert blocks[2]["type"] == PARAGRAPH
        assert blocks[1]["text"].startswith("自承法师名")
        assert blocks[2]["text"].startswith("玄奘不同意")
        assert "玄奘坚持要走" in blocks[2]["text"]
        assert [span["block_id"] for span in blocks[1]["source"]["spans"]] == ["display"]


# ---------------------------------------------------------------------------
# Task 4: Right-aligned terminal block detection
# ---------------------------------------------------------------------------


class TestRightAlignedTerminal:
    def test_right_aligned_date_promoted(self) -> None:
        """A short right-aligned date block near page bottom should be promoted
        to display_block with alignment="right"."""
        # Page-bottom body paragraph
        body = _block(PARAGRAPH, "正文内容到此结束。", page=1, bbox=[120, 700, 880, 740])
        # Right-aligned date near page bottom
        date = _block(PARAGRAPH, "万历二十一年", page=1, bbox=[600, 820, 880, 850])
        # Need a large bbox to trigger near-page-bottom detection
        date2 = _block(PARAGRAPH, "万历二十一年", page=1, bbox=[600, 850, 880, 900])
        blocks = [body, date, date2]

        reconcile_right_aligned_terminal_blocks(blocks, DEFAULT_LAYOUT)

        # At least one right-aligned block should be promoted
        promoted = [b for b in blocks if b["type"] == DISPLAY_BLOCK]
        assert len(promoted) >= 1
        for p in promoted:
            attrs = p.get("attrs", {})
            assert attrs.get("alignment") == "right"

    def test_scaled_layout_right_aligned_date_promoted(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        body = _block(
            PARAGRAPH,
            "正文内容到此结束。",
            page=9,
            bbox=[112, 722, 887, 890],
        )
        date = _block(
            PARAGRAPH,
            "2011年9月30日于北京",
            page=9,
            bbox=[621, 898, 885, 919],
        )
        blocks = [body, date]

        reconcile_right_aligned_terminal_blocks(blocks, layout)

        assert date["type"] == DISPLAY_BLOCK
        assert date["attrs"]["alignment"] == "right"
        assert date["attrs"].get("style_hints", {}).get("text_align") == "right"

    def test_body_paragraph_not_right_aligned_promoted(self) -> None:
        """A normal body-width paragraph should NOT be promoted as
        right-aligned terminal block."""
        body = _block(
            PARAGRAPH,
            "这是一段正常的正文叙事内容，宽度接近正文宽度。",
            page=1,
            bbox=[120, 700, 880, 740],
        )
        blocks = [body]

        reconcile_right_aligned_terminal_blocks(blocks, DEFAULT_LAYOUT)

        assert blocks[0]["type"] == PARAGRAPH

    def test_right_aligned_with_gap_from_prev(self) -> None:
        """A right-aligned block with significant gap from previous block
        should be promoted even if not near page bottom."""
        layout = _layout()
        body = _block(PARAGRAPH, "正文内容。", page=1, bbox=[120, 400, 880, 450])
        # Right-aligned, not near page bottom, but large gap
        date = _block(PARAGRAPH, "一九九三年", page=1, bbox=[620, 700, 880, 730])
        # Need a page-height marker so page_heights has data
        marker = _block(PARAGRAPH, "", page=1, bbox=[0, 0, 1000, 1000])
        blocks = [marker, body, date]

        reconcile_right_aligned_terminal_blocks(blocks, layout)

        date_result = [b for b in blocks if b.get("text") == "一九九三年"]
        if date_result:
            assert date_result[0]["type"] == DISPLAY_BLOCK
            assert date_result[0].get("attrs", {}).get("alignment") == "right"


class TestScaledDisplayLayout:
    def test_page_local_set_off_paragraph_promoted_with_scaled_layout(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        body = _block(
            PARAGRAPH,
            "六天之后，赫定到达叶尔羌河分为诸多支流之处，每条支流都暗藏着危险。",
            page=88,
            bbox=[112, 628, 886, 678],
        )
        quote = _block(
            PARAGRAPH,
            "河床变窄。水流以惊险的速度带着我们前行。水花在我们周围翻腾，"
            "生出许多泡沫。我们顺激流而下。河道之窄转弯之急，使我们无法控制船体。"
            "大船猛烈地撞到岸边，我的箱子差点掉下船去……水流一直如此湍急，"
            "而我们又航行得非常快，以至于船触河底时差点翻船。",
            page=88,
            bbox=[157, 711, 886, 820],
        )
        footnote = _block(
            "footnote",
            "1 Hedin, My Life as an Explorer.",
            page=88,
            bbox=[112, 880, 888, 914],
        )
        blocks = [body, quote, footnote]

        reconcile_display_blocks(blocks, layout)

        assert quote["type"] == DISPLAY_BLOCK

    def test_bounded_set_off_group_promoted_with_scaled_layout(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        before = _block(
            PARAGRAPH,
            "正文段落说明前文内容，宽度接近正文栏。",
            page=152,
            bbox=[99, 119, 874, 256],
        )
        line1 = _block(
            PARAGRAPH,
            "所有光明的众生，所有忍受了巨大痛苦的正义和听者，将与圣父一同欢乐。",
            page=152,
            bbox=[147, 294, 859, 342],
        )
        line2 = _block(
            PARAGRAPH,
            "因为他们曾与他并肩战斗，因为他们克服并消灭了黑暗者。",
            page=152,
            bbox=[149, 353, 870, 402],
        )
        after = _block(
            PARAGRAPH,
            "正文继续恢复，宽度仍然接近正文栏。",
            page=152,
            bbox=[99, 440, 870, 490],
        )
        blocks = [before, line1, line2, after]

        reconcile_display_blocks(blocks, layout)

        assert line1["type"] == DISPLAY_BLOCK
        assert line2["type"] == DISPLAY_BLOCK

    def test_page_top_set_off_before_body_promoted_with_scaled_layout(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        quote = _block(
            PARAGRAPH,
            "培姆州，广五日程，处东方及东北方之间。居民崇拜摩诃末，臣属大汗。"
            "境内有环以墙垣之城村不少。最名贵者是培姆城，国之都也，有河流经城下。"
            "河中产碧玉及玉髓甚丰。百物不缺，棉甚多。居民行商贸产业。",
            page=303,
            bbox=[145, 152, 868, 260],
        )
        body = _block(
            PARAGRAPH,
            "正文恢复，继续解释前面引述的内容。",
            page=303,
            bbox=[97, 297, 868, 375],
        )
        blocks = [quote, body]

        reconcile_display_blocks(blocks, layout)

        assert quote["type"] == DISPLAY_BLOCK

    def test_page_top_set_off_after_previous_page_footnotes_promoted(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        intro = _block(
            PARAGRAPH,
            "一位名叫马希克的当地盗墓者告诉斯坦因，自己和父亲已经亲自检查过遗址中的每一座墓。",
            page=131,
            bbox=[95, 103, 898, 745],
        )
        footnote = _block(
            "footnote",
            "1 注释内容。",
            page=131,
            bbox=[129, 888, 897, 922],
        )
        quote = _block(
            PARAGRAPH,
            "我们的特别墓地助手马希克由于长期的实践，在给死人搜身方面已经毫无顾忌，"
            "他把骷髅的颌骨敲碎，从口腔中取出了一枚薄薄的金币。……马希克宣称"
            "他是第一批从经验中学会要在死人嘴里找金币银币的人，但他的搜索很少得到回报。",
            page=132,
            bbox=[145, 191, 868, 299],
        )
        body = _block(
            PARAGRAPH,
            "在阿斯塔纳和喀喇和卓的墓葬中，斯坦因发现了许多物品。",
            page=132,
            bbox=[95, 337, 867, 416],
        )
        blocks = [intro, footnote, quote, body]

        reconcile_display_blocks(blocks, layout)

        assert quote["type"] == DISPLAY_BLOCK
        assert body["type"] == PARAGRAPH

    def test_page_top_body_flow_after_footnote_uses_same_page_span_body_left(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        previous_cross_page_body = _block(
            PARAGRAPH,
            "上一页正文跨页合并到当前页顶部。",
            page=68,
            bbox=[101, 119, 904, 684],
        )
        previous_cross_page_body["source"]["pages"] = [68, 69]
        previous_cross_page_body["source"]["spans"] = [
            {"page": 68, "bbox": [101, 605, 873, 684], "block_id": "prev_page_part"},
            {"page": 69, "bbox": [131, 119, 904, 168], "block_id": "cur_page_part"},
        ]
        footnote = _block(
            "footnote",
            "3 Thomas Burrow, Tokharian Elements.",
            page=68,
            bbox=[98, 887, 870, 921],
        )
        page_top_body = _block(
            PARAGRAPH,
            "当前页顶部正文继续，宽度接近正文栏，不能因为上一页脚注后页顶而提升为展示块。",
            page=69,
            bbox=[131, 178, 905, 313],
        )
        next_body = _block(
            PARAGRAPH,
            "同页后续正文保持相同左边界和宽度，证明这里是连续正文流。",
            page=69,
            bbox=[131, 323, 905, 430],
        )
        blocks = [previous_cross_page_body, footnote, page_top_body, next_body]

        reconcile_display_blocks(blocks, layout)

        assert page_top_body["type"] == PARAGRAPH
        assert next_body["type"] == PARAGRAPH

    def test_cross_page_body_first_line_indent_not_promoted_to_display(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        before = _block(
            PARAGRAPH,
            "上一段正文建立本页正文左边界。",
            page=128,
            bbox=[78, 664, 847, 830],
        )
        cross_page_body = _block(
            PARAGRAPH,
            "玄奘的路线让他可以尽量处在西突厥及其同盟的控制区内。"
            "高昌王给可汗的礼物是五百匹绫绢，两车水果（可能是干果）。"
            "可汗的牙帐建于碎叶，位于伊塞克湖的西北角，今吉尔吉斯斯坦托克马克西南阿克·贝希姆遗址。",
            page=128,
            bbox=[126, 133, 899, 859],
            attrs={
                "raw_type": "paragraph",
                "merged_from": ["b000799", "b000801"],
                "merge_reason": "cross_page_paragraph_continuation_across_footnote",
            },
        )
        cross_page_body["source"]["pages"] = [128, 129]
        cross_page_body["source"]["spans"] = [
            {"page": 128, "bbox": [126, 839, 845, 859], "block_id": "left"},
            {"page": 129, "bbox": [126, 133, 899, 269], "block_id": "right"},
        ]
        after = _block(
            PARAGRAPH,
            "下一段正文恢复正常正文栏。",
            page=129,
            bbox=[126, 278, 899, 501],
        )
        blocks = [before, cross_page_body, after]

        reconcile_display_blocks(blocks, layout)

        assert cross_page_body["type"] == PARAGRAPH

    def test_tight_body_intro_before_set_off_quote_stays_paragraph(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        before = _block(
            PARAGRAPH,
            "此前正文段落保持正常正文栏宽度，介绍考古学家转移壁画的上下文。",
            page=95,
            bbox=[119, 197, 892, 305],
        )
        intro = _block(
            PARAGRAPH,
            "勒柯克发明了一种转移这些易碎壁画的新技术。他不无骄傲地描述道：",
            page=95,
            bbox=[165, 313, 888, 334],
        )
        quote = _block(
            PARAGRAPH,
            "一名工人用刀沿着壁画边缘切开，再把湿纸覆盖在画面上，"
            "等胶水干后便能把画面从墙上剥离下来。",
            page=95,
            bbox=[165, 371, 891, 652],
        )
        after = _block(
            PARAGRAPH,
            "正文恢复，继续说明这些壁画被送往柏林后的遭遇。",
            page=95,
            bbox=[116, 691, 888, 799],
        )
        blocks = [before, intro, quote, after]

        reconcile_display_blocks(blocks, layout)

        assert intro["type"] == PARAGRAPH
        assert quote["type"] == DISPLAY_BLOCK
        assert intro["text"].startswith("勒柯克发明了一种")

    def test_intro_display_after_footnote_promoted(self) -> None:
        intro = _block(
            PARAGRAPH,
            "前面的正文给出介绍，然后留下深刻的印象：",
            page=158,
            bbox=[106, 720, 876, 857],
        )
        footnote = _block(
            "footnote",
            "1 注释内容。",
            page=158,
            bbox=[105, 913, 442, 929],
        )
        quote = _block(
            PARAGRAPH,
            "其山险峭峻极于天。自开辟已来冰雪所聚。积而为凌。春夏不解。"
            "凝迂污漫与云连属。仰之皑然莫睹其际。其凌峰摧落横路侧者。"
            "或高百尺。或广数丈。",
            page=159,
            bbox=[153, 127, 874, 204],
        )
        blocks = [intro, footnote, quote]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert quote["type"] == DISPLAY_BLOCK

    def test_narrow_set_off_bridge_between_wide_display_blocks_stays_paragraph(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        intro = _block(
            PARAGRAPH,
            "上一页正文建立脚注前的正文流。",
            page=158,
            bbox=[106, 720, 876, 857],
        )
        footnote = _block(
            "footnote",
            "1 注释内容。",
            page=158,
            bbox=[105, 913, 442, 929],
        )
        first_display = _block(
            PARAGRAPH,
            "宽的页顶展示段落。",
            page=159,
            bbox=[153, 127, 874, 204],
        )
        bridge = _block(
            PARAGRAPH,
            "窄的桥接段。",
            page=159,
            bbox=[153, 242, 488, 263],
        )
        second_display = _block(
            PARAGRAPH,
            "宽的后续展示段落。",
            page=159,
            bbox=[153, 301, 864, 350],
        )
        body = _block(
            PARAGRAPH,
            "正文恢复到页面正文栏内。",
            page=159,
            bbox=[106, 387, 875, 437],
        )
        blocks = [intro, footnote, first_display, bridge, second_display, body]

        reconcile_display_blocks(blocks, layout)

        assert [block["type"] for block in blocks] == [
            PARAGRAPH,
            "footnote",
            DISPLAY_BLOCK,
            PARAGRAPH,
            DISPLAY_BLOCK,
            PARAGRAPH,
        ]
        assert bridge["text"] == "窄的桥接段。"

    def test_intro_multi_page_set_off_paragraph_promoted(self) -> None:
        intro = _block(
            PARAGRAPH,
            "文书中讲到：张三",
            page=253,
            bbox=[122, 645, 892, 723],
        )
        quote = _block(
            PARAGRAPH,
            "更欲镌龛一所，踌躇瞻眺，余所竟无，唯此一岭，磋峨可劈。"
            "匪限耗广，务取工成，情专穿石之殷，志切移山之重。",
            page=253,
            bbox=[131, 106, 888, 812],
        )
        quote["source"]["pages"] = [253, 254]
        after = _block(
            PARAGRAPH,
            "正文恢复，继续解释前面引述的内容，宽度接近正文栏。",
            page=254,
            bbox=[81, 223, 855, 390],
        )
        blocks = [intro, quote, after]

        reconcile_display_blocks(blocks, DEFAULT_LAYOUT)

        assert quote["type"] == DISPLAY_BLOCK

    def test_page_top_set_off_uses_scaled_x_axis(self) -> None:
        layout = _layout(body_left=184.34, body_right=1247.84, page_width=1418.0)
        quote = _block(
            PARAGRAPH,
            "页首缩进展示段落在 canonical 坐标系中明显偏离正文左边界，"
            "宽度也小于缩放后的正文栏宽度。",
            page=12,
            bbox=[165, 120, 790, 220],
        )
        body = _block(
            PARAGRAPH,
            "正文恢复，回到页面正文栏内，宽度接近正文栏。",
            page=12,
            bbox=[95, 260, 890, 930],
        )
        blocks = [quote, body]

        reconcile_display_block_cleanup_structures(blocks, layout)

        assert quote["type"] == DISPLAY_BLOCK
        assert body["type"] == PARAGRAPH


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
            attrs={"source": {"pages": [1, 2]}, "layout_role": "inline_display_block"},
        )
        blocks = [display]

        reconcile_display_block_body_paragraph_split(blocks, layout)

        # Should remain intact (short lines, no body prose)
        assert blocks[0]["type"] == DISPLAY_BLOCK
