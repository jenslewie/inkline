from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_checker():
    path = Path(__file__).resolve().parents[1] / "tools" / "check_silk_road_canonical.py"
    spec = importlib.util.spec_from_file_location("check_silk_road_canonical", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _block(
    block_id: str,
    block_type: str,
    text: str = "",
    page: int = 1,
    bbox: list[float] | None = None,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "block_id": block_id,
        "type": block_type,
        "text": text,
        "source": {"page": page, "bbox": bbox or [100, 100, 200, 120]},
    }
    if attrs is not None:
        block["attrs"] = attrs
    return block


def _document(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"blocks": blocks}


def test_acceptance_checker_detects_unfixed_targets_and_extra_changes() -> None:
    baseline = _document(
        [
            _block("b000058", "paragraph", "2011年9月30日于北京"),
            _block("b000102", "figure", attrs={"captions": ["map caption"]}),
            _block("b000103", "heading", "欧亚大陆主要交通线"),
            _block("b000104", "caption", "印度洋"),
            _block("b000105", "caption", "---- 丝绸之路"),
            _block("b000106", "caption", "□ 古代遗址"),
            _block("b000271", "figure", attrs={"image_path": "images/original.jpg"}),
            _block("b000272", "caption", "---- 使节行进的路线"),
            _block("b000549", "paragraph", "body"),
            _block("b000711", "table", attrs={"footnotes": ["资料来源：Georges-Jean Pinault"]}),
            _block("b000095", "footnote", "*译注"),
        ]
    )
    candidate = _document(
        [
            _block("b000058", "paragraph", "2011年9月30日于北京"),
            _block("b000102", "figure", attrs={"captions": []}),
            _block("b000103", "heading", "欧亚大陆主要交通线"),
            _block("b000104", "caption", "印度洋"),
            _block("b000105", "caption", "---- 丝绸之路"),
            _block("b000106", "caption", "□ 古代遗址"),
            _block("b000271", "figure", attrs={"image_path": "images/original.jpg"}),
            _block("b000549", "paragraph", "body"),
            _block("b000711", "table", attrs={"footnotes": ["资料来源：Georges-Jean Pinault"]}),
            _block("b000095", "footnote", "*译注"),
            _block("b099999", "paragraph", "unexpected"),
        ]
    )

    findings = checker.run_checks(baseline, candidate)
    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}

    assert ("plan1", "b000102_single_visual") in failures
    assert ("plan2", "b000058") in failures
    assert ("plan2", "b000549") in failures
    assert ("plan5", "b000711") in failures
    assert ("regression", "unexpected_added_blocks") in failures


def test_plan2_filter_reports_only_display_target_checks() -> None:
    baseline = _document(
        [
            _block("b000058", "paragraph", "2011年9月30日于北京"),
            _block("b000102", "figure", attrs={"captions": ["map caption"]}),
            _block("b000103", "heading", "欧亚大陆主要交通线"),
            _block("b000549", "paragraph", "body"),
            _block("b000095", "footnote", "*译注"),
        ]
    )
    candidate = _document(
        [
            _block("b000058", "paragraph", "2011年9月30日于北京"),
            _block("b000102", "figure", attrs={"captions": []}),
            _block("b000103", "heading", "欧亚大陆主要交通线"),
            _block("b000549", "paragraph", "body"),
            _block("b000095", "footnote", "*译注"),
            _block("b099999", "paragraph", "unexpected"),
        ]
    )

    findings = checker.run_checks(baseline, candidate, plans={"plan2"})

    assert {item.plan for item in findings} <= {"plan2", "plan3"}
    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "b000058") in failures
    assert ("plan2", "b000549") in failures
    assert not any(plan == "plan1" for plan, _ in failures)
    assert not any(plan == "regression" for plan, _ in failures)


def test_plan2_accepts_display_target_absorbed_into_merged_block() -> None:
    baseline = _document(
        [
            _block("b000981", "paragraph", "第一行展示文字。"),
            _block("b000982", "paragraph", "第二行展示文字。"),
        ]
    )
    candidate = _document(
        [
            _block(
                "b000981",
                "display_block",
                "第一行展示文字。\n第二行展示文字。",
            ),
        ]
    )

    findings = checker.check_plan2_display(
        checker.blocks_by_id(baseline),
        checker.blocks_by_id(candidate),
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "b000982") not in failures
    assert any(
        item.status == "PASS" and item.check == "b000982" and "b000981" in item.detail
        for item in findings
    )


def test_plan2_accepts_display_target_when_old_id_reused_for_other_text() -> None:
    baseline = _document(
        [
            _block("b000981", "paragraph", "所有光明的众生，将与圣父一同欢乐。"),
        ]
    )
    candidate = _document(
        [
            _block("b000981", "paragraph", "前置正文说明。"),
            _block("b000982", "display_block", "所有光明的众生，将与圣父一同欢乐。"),
        ]
    )

    findings = checker.check_plan2_display(
        checker.blocks_by_id(baseline),
        checker.blocks_by_id(candidate),
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "b000981") not in failures


def test_plan2_accepts_paragraph_target_after_id_drift() -> None:
    baseline = _document(
        [
            _block("b000868", "display_block", "六、七世纪银币在吐鲁番的流通再一次说明。"),
        ]
    )
    candidate = _document(
        [
            _block("b000869", "paragraph", "六、七世纪银币在吐鲁番的流通再一次说明。"),
        ]
    )

    findings = checker.check_plan2_display(
        checker.blocks_by_id(baseline),
        checker.blocks_by_id(candidate),
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "b000868") not in failures


def test_plan2_rejects_stein_niya_tail_as_paragraph() -> None:
    target = "向北走约两英里，越过一些相当高的沙包，我来到一个用土坯修建的废墟上"
    findings = checker.check_plan2_display(
        {},
        {
            "b000315_body": _block(
                "b000315_body",
                "paragraph",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "stein_niya_first_impression_tail") in failures


def test_plan2_accepts_stein_niya_tail_as_display_block() -> None:
    target = "向北走约两英里，越过一些相当高的沙包，我来到一个用土坯修建的废墟上"
    findings = checker.check_plan2_display(
        {},
        {
            "b000315": _block(
                "b000315",
                "display_block",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "stein_niya_first_impression_tail") not in failures


def test_plan2_accepts_exact_manual_dialogue_display_block() -> None:
    target = "我要去中国。\n你去中国有什么事？\n我要去看文殊菩萨。"
    findings = checker.check_plan2_display(
        {},
        {
            "b_dialogue": _block(
                "b_dialogue",
                "display_block",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "manual_pilgrim_dialogue") not in failures


def test_plan2_rejects_overmerged_manual_conflict_dialogue() -> None:
    target = (
        "不要生我的气。\n"
        "我不会扯你的头发。\n"
        "你要是说让人不愉快的话\n"
        "我就生气了。\n"
        "有些甚至提到了性："
    )
    findings = checker.check_plan2_display(
        {},
        {
            "b_dialogue": _block(
                "b_dialogue",
                "display_block",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "manual_conflict_dialogue") in failures


def test_plan2_accepts_exact_storyteller_army_quote_display_block() -> None:
    target = "贼等不虞汉兵忽到，都无准备之心。我军遂列乌云之阵，四面急攻。蕃贼獐狂，星分南北；汉军得势，押背便追。不过五十里之间，"
    findings = checker.check_plan2_display(
        {},
        {
            "b001622": _block(
                "b001622",
                "display_block",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "storyteller_army_quote") not in failures


def test_plan2_rejects_overmerged_storyteller_army_quote_paragraph() -> None:
    target = (
        "贼等不虞汉兵忽到，都无准备之心。我军遂列乌云之阵，四面急攻。"
        "蕃贼獐狂，星分南北；汉军得势，押背便追。不过五十里之间，"
        "然后说书人指着画中军队的图说：“煞戮横尸遍野处。”"
    )
    findings = checker.check_plan2_display(
        {},
        {
            "b001622": _block(
                "b001622",
                "paragraph",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "storyteller_army_quote") in failures


def test_plan2_rejects_storyteller_army_body_as_display_block() -> None:
    target = "然后说书人指着画中军队的图说：“煞戮横尸遍野处。” 虽然这类画无一保留下来"
    findings = checker.check_plan2_display(
        {},
        {
            "b001621": _block(
                "b001621",
                "display_block",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "storyteller_army_body") in failures


def test_plan2_accepts_storyteller_army_body_as_paragraph() -> None:
    target = "然后说书人指着画中军队的图说：“煞戮横尸遍野处。” 虽然这类画无一保留下来"
    findings = checker.check_plan2_display(
        {},
        {
            "b001621": _block(
                "b001621",
                "paragraph",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "storyteller_army_body") not in failures


def test_plan2_rejects_gaochang_king_intro_as_display_block() -> None:
    target = "高昌王想劝他留下："
    findings = checker.check_plan2_display(
        {},
        {
            "b000789": _block(
                "b000789",
                "display_block",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "gaochang_king_intro") in failures


def test_plan2_accepts_gaochang_king_intro_as_paragraph() -> None:
    target = "高昌王想劝他留下："
    findings = checker.check_plan2_display(
        {},
        {
            "b000789": _block(
                "b000789",
                "paragraph",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "gaochang_king_intro") not in failures


def test_plan2_rejects_gaochang_dispute_tail_left_in_display_block() -> None:
    findings = checker.check_plan2_display(
        {},
        {
            "b000790": _block(
                "b000790",
                "display_block",
                "自承法师名。\n玄奘不同意，二人便开始争吵。高昌王威胁要把玄奘遣送回国。玄奘",
            ),
            "b000797": _block(
                "b000797",
                "paragraph",
                "坚持要走，国王就把玄奘锁在宫里。",
            ),
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "gaochang_dispute_joined_body") in failures


def test_plan2_accepts_gaochang_dispute_tail_joined_as_paragraph() -> None:
    findings = checker.check_plan2_display(
        {},
        {
            "b000791_body": _block(
                "b000791_body",
                "paragraph",
                "玄奘不同意，二人便开始争吵。高昌王威胁要把玄奘遣送回国。"
                "玄奘坚持要走，国王就把玄奘锁在宫里。",
            ),
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "gaochang_dispute_joined_body") not in failures


def test_plan2_rejects_gaochang_route_body_as_display_block() -> None:
    target = "玄奘的路线让他可以尽量处在西突厥及其同盟的控制区内"
    findings = checker.check_plan2_display(
        {},
        {
            "b000799": _block(
                "b000799",
                "display_block",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "gaochang_route_body") in failures


def test_plan2_accepts_gaochang_route_body_as_paragraph() -> None:
    target = "玄奘的路线让他可以尽量处在西突厥及其同盟的控制区内"
    findings = checker.check_plan2_display(
        {},
        {
            "b000799": _block(
                "b000799",
                "paragraph",
                target,
            )
        },
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan2", "gaochang_route_body") not in failures


def test_plan1_rejects_gaochang_caption_spilled_into_flow_blocks() -> None:
    baseline = _document(
        [
            _block(
                "b000791",
                "figure",
                attrs={
                    "captions": [
                        "高昌故城遗址\n吐鲁番附近高昌故城夯土墙是中国境内为数不多的地上古迹之一。"
                    ]
                },
            )
        ]
    )
    candidate = _document(
        [
            _block("b000791", "figure", attrs={"captions": []}),
            _block("b000792", "heading", "高昌故城遗址"),
            _block(
                "b000793", "paragraph", "吐鲁番附近高昌故城夯土墙是中国境内为数不多的地上古迹之一。"
            ),
        ]
    )

    findings = checker.check_plan1_figures(
        checker.blocks_by_id(baseline),
        checker.blocks_by_id(candidate),
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan1", "b000791_caption_attached") in failures


def test_plan1_accepts_gaochang_caption_attached_to_figure() -> None:
    baseline = _document(
        [
            _block(
                "b000791",
                "figure",
                attrs={
                    "captions": [
                        "高昌故城遗址\n吐鲁番附近高昌故城夯土墙是中国境内为数不多的地上古迹之一。"
                    ]
                },
            )
        ]
    )
    candidate = _document(
        [
            _block(
                "b000791",
                "figure",
                attrs={
                    "captions": [
                        "高昌故城遗址\n吐鲁番附近高昌故城夯土墙是中国境内为数不多的地上古迹之一。"
                    ],
                    "caption_block_ids": ["b000792", "b000793"],
                },
            )
        ]
    )

    findings = checker.check_plan1_figures(
        checker.blocks_by_id(baseline),
        checker.blocks_by_id(candidate),
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan1", "b000791_caption_attached") not in failures


def test_plan1_accepts_gaochang_caption_after_figure_id_drift() -> None:
    baseline = _document(
        [
            _block(
                "b000791",
                "figure",
                attrs={
                    "captions": [
                        "高昌故城遗址\n吐鲁番附近高昌故城夯土墙是中国境内为数不多的地上古迹之一。"
                    ]
                },
            )
        ]
    )
    candidate = _document(
        [
            _block("b000791", "footnote", "2 旧页脚。"),
            _block(
                "b000792",
                "figure",
                attrs={
                    "captions": [
                        "高昌故城遗址\n吐鲁番附近高昌故城夯土墙是中国境内为数不多的地上古迹之一。"
                    ],
                    "caption_block_ids": ["b000793", "b000794"],
                },
            ),
        ]
    )

    findings = checker.check_plan1_figures(
        checker.blocks_by_id(baseline),
        checker.blocks_by_id(candidate),
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan1", "b000791_caption_attached") not in failures


def test_plan1_accepts_figure_group_after_anchor_id_drift() -> None:
    baseline = _document([_block("b001422", "figure", attrs={"captions": []})])
    candidate = _document(
        [
            _block("b001422", "footnote", "2 source note"),
            _block(
                "b001423",
                "figure",
                attrs={
                    "absorbed_block_ids": ["b001424"],
                    "fragment_block_ids": ["b001423", "b001425"],
                },
            ),
        ]
    )

    findings = checker.check_plan1_figures(
        checker.blocks_by_id(baseline),
        checker.blocks_by_id(candidate),
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan1", "b001422_single_visual") not in failures


def test_plan1_rejects_page51_caption_and_paragraph_crop_regression() -> None:
    baseline = _document([_block("b000289", "figure", attrs={"captions": []})])
    candidate = _document(
        [
            _block(
                "b000284",
                "paragraph",
                "这种方法只能得到一个大致的时此外在奇拉斯下游50公里左右的夏迪亚尔遗址",
            ),
            _block(
                "b000289",
                "figure",
                attrs={
                    "captions": [],
                    "absorbed_block_ids": ["b000290", "b000291", "b000292"],
                    "embedded_text_absorb_reason": "following_visual_legend_strip",
                },
            ),
            _block("b000296", "paragraph", "一个堡垒，人们可以从这里进入西域。"),
        ]
    )

    findings = checker.check_plan1_figures(
        checker.blocks_by_id(baseline),
        checker.blocks_by_id(candidate),
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan1", "b000289_caption_not_cropped") in failures
    assert ("plan1", "chilas_destination_joined") in failures
    assert ("plan1", "date_range_tail_joined") in failures
    assert ("plan1", "page51_no_bad_time_join") in failures


def test_plan1_accepts_page51_caption_and_paragraph_repair() -> None:
    baseline = _document([_block("b000289", "figure", attrs={"captions": []})])
    candidate = _document(
        [
            _block(
                "b000284",
                "paragraph",
                "这种方法只能得到一个大致的时间范围，即一到八世纪之间。",
            ),
            _block(
                "b000289",
                "figure",
                attrs={
                    "captions": [
                        "喀喇昆仑公路上的佛教石刻\n"
                        "图中石刻坐落于巴基斯坦吉尔吉特－巴尔蒂斯坦省霍独尔镇附近的大石堆中"
                    ]
                },
            ),
            _block(
                "b000293",
                "paragraph",
                "此人的目的地是塔什库尔干，即喀什西面山中的一个堡垒，"
                "人们可以从这里进入西域。这表明犹太商人也走过这条路。",
            ),
        ]
    )

    findings = checker.check_plan1_figures(
        checker.blocks_by_id(baseline),
        checker.blocks_by_id(candidate),
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan1", "b000289_caption_not_cropped") not in failures
    assert ("plan1", "chilas_destination_joined") not in failures
    assert ("plan1", "date_range_tail_joined") not in failures
    assert ("plan1", "page51_no_bad_time_join") not in failures


def test_display_regression_scope_catches_unrelated_added_blocks() -> None:
    baseline = _document(
        [
            _block("b000058", "paragraph", "2011年9月30日于北京"),
            _block("b000549", "paragraph", "body"),
        ]
    )
    candidate = _document(
        [
            _block(
                "b000058",
                "display_block",
                "2011年9月30日于北京",
                attrs={"alignment": "right"},
            ),
            _block("b000549", "display_block", "body"),
            _block("b099999", "figure", attrs={"captions": []}),
        ]
    )

    findings = checker.run_checks(
        baseline,
        candidate,
        plans={"plan2", "display-regression"},
    )

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("display_regression", "unexpected_added_blocks") in failures
    assert ("plan2", "b000058") not in failures
    assert ("plan2", "b000549") not in failures


def test_plan5_accepts_table_notes_after_table_id_drift() -> None:
    candidate = _document(
        [
            _block("b000711", "paragraph", "old id reused"),
            _block(
                "b000712",
                "table",
                attrs={
                    "table_notes": ["资料来源：Georges-Jean Pinault, Mission Paul Pelliot VIII."]
                },
            ),
        ]
    )

    findings = checker.check_plan5_tables(checker.blocks_by_id(candidate))

    failures = {(item.plan, item.check) for item in findings if item.status == "FAIL"}
    assert ("plan5", "b000711") not in failures


def test_acceptance_checker_passes_core_repaired_fixture() -> None:
    baseline = _document(
        [
            _block("b000058", "paragraph", "2011年9月30日于北京"),
            _block("b000102", "figure", attrs={"captions": ["map caption"]}),
            _block("b000103", "heading", "欧亚大陆主要交通线"),
            _block("b000104", "caption", "印度洋"),
            _block("b000105", "caption", "---- 丝绸之路"),
            _block("b000106", "caption", "□ 古代遗址"),
            _block("b000271", "figure", attrs={"image_path": "images/original.jpg"}),
            _block("b000272", "caption", "---- 使节行进的路线"),
            _block("b000549", "paragraph", "body"),
            _block("b000711", "table", attrs={"footnotes": ["资料来源：Georges-Jean Pinault"]}),
            _block("b000095", "footnote", "*译注"),
        ]
    )
    candidate = _document(
        [
            _block(
                "b000058",
                "display_block",
                "2011年9月30日于北京",
                attrs={"alignment": "right"},
            ),
            _block(
                "b000102",
                "figure",
                attrs={
                    "captions": ["map caption"],
                    "absorbed_block_ids": ["b000103", "b000104", "b000105", "b000106"],
                },
            ),
            _block("b000271", "figure", attrs={"image_path": "images/repaired/b000271.png"}),
            _block("b000549", "display_block", "body"),
            _block(
                "b000711",
                "table",
                attrs={
                    "footnotes": ["资料来源：Georges-Jean Pinault"],
                    "table_notes": ["资料来源：Georges-Jean Pinault"],
                },
            ),
            _block("b000095", "footnote", "*译注"),
        ]
    )

    findings = checker.run_checks(baseline, candidate)
    target_failures = [
        item
        for item in findings
        if item.status == "FAIL"
        and item.check
        in {
            "b000058",
            "b000102_single_visual",
            "b000271_visual_image",
            "b000549",
            "b000711",
            "canonical_footnote_text_contract",
            "unexpected_added_blocks",
            "unexpected_removed_blocks",
        }
    ]

    assert target_failures == []
