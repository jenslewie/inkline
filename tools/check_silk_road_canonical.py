#!/usr/bin/env python3
"""Acceptance checker for the Silk Road canonical repair plans.

This intentionally lives outside the production packages: it is a book-specific
review gate for comparing a baseline canonical.json with a candidate output.
Implementation fixes must stay layout/structure driven, but this acceptance
gate can name known block ids from the audit report.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLAN3_ALLOWED_CHANGED_IDS = {"b000315"}

PLAN1_FIGURE_GROUPS = {
    "b000102": ["b000103", "b000104", "b000105", "b000106"],
    "b001422": ["b001423", "b001424", "b001425"],
}
PLAN1_FIGURE_CAPTIONS = {
    "b000791": ("高昌故城遗址", "吐鲁番附近高昌故城夯土墙"),
}
PLAN1_PAGE51_CAPTION = ("喀喇昆仑公路上的佛教石刻", "巴基斯坦吉尔吉特－巴尔蒂斯坦省")
PLAN1_PAGE51_PARAGRAPH_FIXES = {
    "chilas_destination_joined": (
        "塔什库尔干，即喀什西面山中的一个堡垒",
        "这表明犹太商人也走过这条路",
    ),
    "date_range_tail_joined": ("这种方法只能得到一个大致的时间范围，即一到八世纪之间。",),
}
PLAN1_EXPECTED_REMOVED = {
    "b000272",
    *PLAN1_FIGURE_GROUPS["b000102"],
    *PLAN1_FIGURE_GROUPS["b001422"],
}

PLAN2_DISPLAY_BLOCKS = {
    "b000058",
    "b000549",
    "b000827",
    "b000981",
    "b000982",
    "b001008",
    "b001630",
    "b001972",
}
PLAN2_PARAGRAPHS = {"b000868", "b001700", "b001873", "b001992"}
PLAN2_PARAGRAPH_TEXTS = {
    "manual_audience_identity": "只有僧人或者资深的佛教学习者才会用到这样的句子",
    "manual_pilgrim_user": "手册的假想使用者是朝觐路上的僧侣",
    "animal_loss_letter": "一封随从的信解释了牲口是怎么丢的。",
    "gaochang_dispute_joined_body": "玄奘不同意，二人便开始争吵。高昌王威胁要把玄奘遣送回国。玄奘坚持要走",
    "gaochang_king_intro": "高昌王想劝他留下：",
    "gaochang_route_body": "玄奘的路线让他可以尽量处在西突厥及其同盟的控制区内",
    "loulan_king_commands_body": "这些命令都来自楼兰王，写给相当于刺史的当地最高长官cozbo",
    "storyteller_army_body": "然后说书人指着画中军队的图说：“煞戮横尸遍野处。” 虽然这类画无一保留下来",
}
PLAN2_DISPLAY_TEXTS = {
    "stein_niya_first_impression_tail": "向北走约两英里，越过一些相当高的沙包",
    "kizil_earthquake_quote_tail": "这时，我向着山谷河流的方向望去，只见河水剧烈地荡来荡去",
}
PLAN2_EXACT_DISPLAY_TEXTS = {
    "manual_pilgrim_dialogue": "我要去中国。\n你去中国有什么事？\n我要去看文殊菩萨。",
    "manual_conflict_dialogue": "不要生我的气。\n我不会扯你的头发。\n你要是说让人不愉快的话\n我就生气了。",
    "storyteller_army_quote": "贼等不虞汉兵忽到，都无准备之心。我军遂列乌云之阵，四面急攻。蕃贼獐狂，星分南北；汉军得势，押背便追。不过五十里之间，",
}

PLAN5_TABLE_NOTES = {
    "b000711": "资料来源：Georges-Jean Pinault",
    "b000908": "资料来源：《高昌内藏奏得称价钱帐》",
    "b001344": "资料来源：原始报告发表于《西安南郊何家村发现唐代窖藏文物》",
}
CONTINUATION_MARKERS = {"接上页", "接下页", "续表", "续上表"}

FOOTNOTE_MARKER_RE = re.compile(r"^(\*+|[0-9]{1,3}[.．、）)]|[①-⑳])")
ALLOWED_NEW_BLOCK_SUFFIXES = ("_body",)
DISPLAY_REFACTOR_ATTR_ONLY_TYPES = {"display_block"}
DISPLAY_REFACTOR_TARGET_PLANS = {"plan2", "display-regression"}
ALL_PLANS = {"plan1", "plan2", "plan3", "plan4", "plan5", "regression"}


@dataclass(frozen=True)
class Finding:
    status: str
    plan: str
    check: str
    detail: str


def load_document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def blocks_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(block.get("block_id")): block
        for block in document.get("blocks", [])
        if block.get("block_id")
    }


def text_of(block: dict[str, Any] | None) -> str:
    return str((block or {}).get("text") or "")


def attrs_of(block: dict[str, Any] | None) -> dict[str, Any]:
    attrs = (block or {}).get("attrs") or {}
    return attrs if isinstance(attrs, dict) else {}


def is_continuation_marker(text: str) -> bool:
    value = str(text or "").strip().strip("()（）[]【】")
    return value in CONTINUATION_MARKERS


def finding(status: str, plan: str, check: str, detail: str) -> Finding:
    return Finding(status=status, plan=plan, check=check, detail=detail)


def check_plan1_figures(
    baseline_by_id: dict[str, dict[str, Any]],
    candidate_by_id: dict[str, dict[str, Any]],
) -> list[Finding]:
    findings: list[Finding] = []

    figure = candidate_by_id.get("b000271")
    removed_caption = "b000272" not in candidate_by_id
    repaired_image = "repaired/" in str(attrs_of(figure).get("image_path") or "")
    if figure and figure.get("type") == "figure" and removed_caption and repaired_image:
        findings.append(
            finding(
                "PASS",
                "plan1",
                "b000271_visual_image",
                "b000272 removed and repaired figure image is used",
            )
        )
    else:
        findings.append(
            finding(
                "FAIL",
                "plan1",
                "b000271_visual_image",
                "expected b000271 figure with b000272 removed and repaired image_path",
            )
        )

    for anchor_id, absorbed_ids in PLAN1_FIGURE_GROUPS.items():
        anchor = _figure_group_carrier(candidate_by_id, anchor_id, absorbed_ids)
        absorbed = set(attrs_of(anchor).get("absorbed_block_ids") or [])
        caption_ids = set(attrs_of(anchor).get("caption_block_ids") or [])
        fragment_ids = set(attrs_of(anchor).get("fragment_block_ids") or [])
        carrier_id = str((anchor or {}).get("block_id") or "")
        remaining = [
            block_id
            for block_id in absorbed_ids
            if block_id in candidate_by_id
            and block_id != carrier_id
            and block_id not in absorbed
            and block_id not in caption_ids
            and block_id not in fragment_ids
        ]
        known = sorted(set(absorbed_ids) & (absorbed | caption_ids | fragment_ids))
        if anchor and anchor.get("type") == "figure" and not remaining:
            findings.append(
                finding(
                    "PASS",
                    "plan1",
                    f"{anchor_id}_single_visual",
                    f"fragment blocks removed; carrier={carrier_id}; linked ids={known}",
                )
            )
        else:
            findings.append(
                finding(
                    "FAIL",
                    "plan1",
                    f"{anchor_id}_single_visual",
                    f"expected one visual figure; remaining fragment blocks={remaining}",
                )
            )

    for figure_id, snippets in PLAN1_FIGURE_CAPTIONS.items():
        if figure_id not in baseline_by_id and not any(
            any(snippet in text_of(block) for snippet in snippets)
            for block in candidate_by_id.values()
        ):
            continue
        figure = _figure_caption_carrier(candidate_by_id, snippets) or candidate_by_id.get(
            figure_id
        )
        carrier_id = str((figure or {}).get("block_id") or figure_id)
        caption_text = "\n".join(str(item) for item in attrs_of(figure).get("captions") or [])
        spilled = [
            block.get("block_id")
            for block in candidate_by_id.values()
            if block.get("block_id") != carrier_id
            and block.get("type") in {"heading", "paragraph", "caption"}
            and any(snippet in text_of(block) for snippet in snippets)
        ]
        if (
            figure
            and figure.get("type") == "figure"
            and all(snippet in caption_text for snippet in snippets)
            and not spilled
        ):
            findings.append(
                finding(
                    "PASS",
                    "plan1",
                    f"{figure_id}_caption_attached",
                    f"figure caption remains attached to {carrier_id}",
                )
            )
        else:
            findings.append(
                finding(
                    "FAIL",
                    "plan1",
                    f"{figure_id}_caption_attached",
                    f"expected figure attrs.captions to contain {snippets}; spilled blocks={spilled}",
                )
            )

    blocks = list(candidate_by_id.values())
    page51_relevant = (
        "b000289" in baseline_by_id
        or "b000289" in candidate_by_id
        or any(
            any(snippet in text_of(block) for snippet in PLAN1_PAGE51_CAPTION)
            for block in candidate_by_id.values()
        )
    )
    if page51_relevant:
        page51_figure = candidate_by_id.get("b000289")
        page51_attrs = attrs_of(page51_figure)
        page51_caption = "\n".join(str(item) for item in page51_attrs.get("captions") or [])
        absorbed_ids = set(page51_attrs.get("absorbed_block_ids") or [])
        bad_absorption = bool({"b000290", "b000291", "b000292"} & absorbed_ids) or (
            page51_attrs.get("embedded_text_absorb_reason") == "following_visual_legend_strip"
        )
        if (
            page51_figure
            and page51_figure.get("type") == "figure"
            and all(snippet in page51_caption for snippet in PLAN1_PAGE51_CAPTION)
            and not bad_absorption
        ):
            findings.append(
                finding(
                    "PASS",
                    "plan1",
                    "b000289_caption_not_cropped",
                    "caption attached without absorbing surrounding prose into repaired figure crop",
                )
            )
        else:
            findings.append(
                finding(
                    "FAIL",
                    "plan1",
                    "b000289_caption_not_cropped",
                    "expected b000289 caption in attrs.captions and no following_visual_legend_strip absorption",
                )
            )

        for check_name, snippets in PLAN1_PAGE51_PARAGRAPH_FIXES.items():
            carriers = [
                block
                for block in blocks
                if block.get("type") == "paragraph"
                and all(snippet in text_of(block) for snippet in snippets)
            ]
            if carriers:
                ids = [str(block.get("block_id")) for block in carriers]
                findings.append(
                    finding("PASS", "plan1", check_name, f"paragraph text carried by {ids}")
                )
            else:
                findings.append(
                    finding(
                        "FAIL",
                        "plan1",
                        check_name,
                        f"expected one paragraph containing snippets={snippets}",
                    )
                )

        bad_time_join = [
            str(block.get("block_id"))
            for block in blocks
            if block.get("type") == "paragraph" and "大致的时此外" in text_of(block)
        ]
        if bad_time_join:
            findings.append(
                finding(
                    "FAIL",
                    "plan1",
                    "page51_no_bad_time_join",
                    f"paragraph still has bad join in blocks {bad_time_join}",
                )
            )
        else:
            findings.append(
                finding("PASS", "plan1", "page51_no_bad_time_join", "no bad time/page join")
            )

    caption_spills = figure_caption_spills(baseline_by_id, candidate_by_id)
    if caption_spills:
        sample = ", ".join(
            f"{item['figure_id']}->{','.join(item['added_ids'][:3])}" for item in caption_spills[:8]
        )
        findings.append(
            finding(
                "FAIL",
                "plan1",
                "no_figure_caption_spillover",
                f"{len(caption_spills)} figures lost attrs.captions into new flow blocks; sample {sample}",
            )
        )
    else:
        findings.append(
            finding(
                "PASS", "plan1", "no_figure_caption_spillover", "no lost figure captions detected"
            )
        )

    return findings


def _figure_group_carrier(
    candidate_by_id: dict[str, dict[str, Any]],
    anchor_id: str,
    absorbed_ids: list[str],
) -> dict[str, Any] | None:
    direct = candidate_by_id.get(anchor_id)
    if direct and direct.get("type") == "figure":
        return direct
    expected_ids = {anchor_id, *absorbed_ids}
    best: tuple[int, dict[str, Any]] | None = None
    for block in candidate_by_id.values():
        if block.get("type") != "figure":
            continue
        attrs = attrs_of(block)
        linked = {
            str(block.get("block_id") or ""),
            *map(str, attrs.get("absorbed_block_ids") or []),
            *map(str, attrs.get("caption_block_ids") or []),
            *map(str, attrs.get("fragment_block_ids") or []),
        }
        score = len(expected_ids & linked)
        if score and (best is None or score > best[0]):
            best = (score, block)
    return best[1] if best else None


def _figure_caption_carrier(
    candidate_by_id: dict[str, dict[str, Any]], snippets: tuple[str, ...]
) -> dict[str, Any] | None:
    for block in candidate_by_id.values():
        if block.get("type") != "figure":
            continue
        caption_text = "\n".join(str(item) for item in attrs_of(block).get("captions") or [])
        if all(snippet in caption_text for snippet in snippets):
            return block
    return None


def figure_caption_spills(
    baseline_by_id: dict[str, dict[str, Any]],
    candidate_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    added_ids = set(candidate_by_id) - set(baseline_by_id)
    out: list[dict[str, Any]] = []
    for block_id, old_block in baseline_by_id.items():
        if old_block.get("type") != "figure":
            continue
        old_captions = attrs_of(old_block).get("captions") or []
        if not old_captions:
            continue
        new_block = candidate_by_id.get(block_id)
        if not new_block or new_block.get("type") != "figure":
            continue
        if attrs_of(new_block).get("captions"):
            continue
        old_page = (old_block.get("source") or {}).get("page")
        old_bbox = (old_block.get("source") or {}).get("bbox") or []
        if not old_page or len(old_bbox) != 4:
            continue
        added_nearby: list[str] = []
        old_bottom = float(old_bbox[3])
        for added_id in sorted(added_ids):
            candidate = candidate_by_id[added_id]
            if candidate.get("type") not in {"heading", "paragraph", "caption"}:
                continue
            source = candidate.get("source") or {}
            bbox = source.get("bbox") or []
            if source.get("page") != old_page or len(bbox) != 4:
                continue
            gap = float(bbox[1]) - old_bottom
            horizontal_overlap = min(float(old_bbox[2]), float(bbox[2])) - max(
                float(old_bbox[0]), float(bbox[0])
            )
            if -30.0 <= gap <= 220.0 and horizontal_overlap > 0:
                added_nearby.append(added_id)
        if added_nearby:
            out.append({"figure_id": block_id, "added_ids": added_nearby})
    return out


def check_plan2_display(
    baseline_by_id: dict[str, dict[str, Any]],
    candidate_by_id: dict[str, dict[str, Any]],
) -> list[Finding]:
    findings: list[Finding] = []
    for block_id in sorted(PLAN2_DISPLAY_BLOCKS):
        block = candidate_by_id.get(block_id)
        baseline_text = text_of(baseline_by_id.get(block_id)).strip()
        carrier = _display_text_carrier(candidate_by_id, baseline_text)
        if carrier:
            findings.append(
                finding(
                    "PASS",
                    "plan2",
                    block_id,
                    f"display text carried by block {carrier.get('block_id')}",
                )
            )
            continue
        if not block:
            detail = "target block is missing"
            text_carriers = _text_carriers(candidate_by_id, baseline_text)
            if text_carriers:
                detail = f"expected display text is in non-display blocks {[b.get('block_id') for b in text_carriers]}"
            findings.append(finding("FAIL", "plan2", block_id, detail))
            continue
        if block.get("type") != "display_block":
            findings.append(
                finding(
                    "FAIL", "plan2", block_id, f"expected display_block, got {block.get('type')}"
                )
            )
            continue
        if block_id == "b000058" and attrs_of(block).get("alignment") != "right":
            findings.append(finding("FAIL", "plan2", block_id, "expected attrs.alignment=right"))
            continue
        findings.append(finding("PASS", "plan2", block_id, "display classification is correct"))

    for block_id in sorted(PLAN2_PARAGRAPHS):
        block = candidate_by_id.get(block_id)
        baseline_text = text_of(baseline_by_id.get(block_id)).strip()
        carrier = _paragraph_text_carrier(candidate_by_id, baseline_text)
        if carrier:
            findings.append(
                finding(
                    "PASS",
                    "plan2",
                    block_id,
                    f"paragraph text carried by block {carrier.get('block_id')}",
                )
            )
            continue
        if not block:
            findings.append(finding("WARN", "plan2", block_id, "target block missing in candidate"))
            continue
        if not baseline_text:
            findings.append(
                finding(
                    "INFO",
                    "plan2",
                    block_id,
                    f"skipped id check because baseline block is missing; candidate id is {block.get('type')}",
                )
            )
            continue
        if block.get("type") != "paragraph":
            findings.append(
                finding("FAIL", "plan2", block_id, f"expected paragraph, got {block.get('type')}")
            )
        else:
            findings.append(
                finding("PASS", "plan2", block_id, "paragraph classification is correct")
            )

    blocks = list(candidate_by_id.values())
    for name, needle in PLAN2_DISPLAY_TEXTS.items():
        carriers = [
            block
            for block in blocks
            if needle in text_of(block) and block.get("type") != "footnote"
        ]
        if not carriers:
            findings.append(finding("FAIL", "plan2", name, "target display text is missing"))
            continue
        bad = [block.get("block_id") for block in carriers if block.get("type") != "display_block"]
        if bad:
            findings.append(
                finding(
                    "FAIL",
                    "plan2",
                    name,
                    f"target display text is in non-display blocks {bad}",
                )
            )
        else:
            ids = [str(block.get("block_id")) for block in carriers]
            findings.append(
                finding("PASS", "plan2", name, f"target text carried by display blocks {ids}")
            )

    for name, expected_text in PLAN2_EXACT_DISPLAY_TEXTS.items():
        expected = _normalize_multiline_text(expected_text)
        exact_carriers = [
            block
            for block in blocks
            if block.get("type") == "display_block"
            and _normalize_multiline_text(text_of(block)) == expected
        ]
        if exact_carriers:
            ids = [str(block.get("block_id")) for block in exact_carriers]
            findings.append(finding("PASS", "plan2", name, f"exact display text carried by {ids}"))
            continue
        first_line = expected_text.split("\n", 1)[0]
        near = [
            f"{block.get('block_id')}:{block.get('type')}"
            for block in blocks
            if first_line in text_of(block) and block.get("type") != "footnote"
        ]
        findings.append(
            finding(
                "FAIL",
                "plan2",
                name,
                f"expected exact display block text; nearby carriers={near}",
            )
        )

    for name, needle in PLAN2_PARAGRAPH_TEXTS.items():
        carriers = [
            block
            for block in blocks
            if needle in text_of(block) and block.get("type") != "footnote"
        ]
        if not carriers:
            findings.append(finding("FAIL", "plan2", name, "target text is missing"))
            continue
        bad = [block.get("block_id") for block in carriers if block.get("type") != "paragraph"]
        if bad:
            findings.append(
                finding(
                    "FAIL",
                    "plan2",
                    name,
                    f"target text is still in non-paragraph blocks {bad}",
                )
            )
        else:
            ids = [str(block.get("block_id")) for block in carriers]
            findings.append(
                finding("PASS", "plan2", name, f"target text carried by paragraphs {ids}")
            )
    return findings


def check_plan3_mineru_newlines(candidate_by_id: dict[str, dict[str, Any]]) -> list[Finding]:
    carriers = [
        block
        for block in candidate_by_id.values()
        if "在一片低矮的沙丘中" in text_of(block)
        and "珍贵的木板文书还有多少有待发现" in text_of(block)
    ]
    if not carriers:
        return [
            finding(
                "FAIL",
                "plan3",
                "b000315_mineru_prose_wrap",
                "target text is missing",
            )
        ]

    block = carriers[0]
    text = text_of(block)
    bad_breaks = [
        "继续往北走\n了不到两英里",
        "乍看起来\n似乎坐落",
    ]
    remaining_bad = [pattern for pattern in bad_breaks if pattern in text]
    required = [
        "继续往北走了不到两英里",
        "乍看起来似乎坐落",
        "部分……\n向北走约两英里",
        "下面……\n当我第一次",
    ]
    missing = [pattern for pattern in required if pattern not in text]
    line_count = len([line for line in text.splitlines() if line.strip()])
    attr_line_count = attrs_of(block).get("line_count")
    bad_line_count = line_count != 3 or (attr_line_count is not None and attr_line_count != 3)
    if remaining_bad or missing or bad_line_count:
        detail_parts = []
        if remaining_bad:
            detail_parts.append(f"remaining bad internal wraps={remaining_bad}")
        if missing:
            detail_parts.append(f"missing expected joins/boundaries={missing}")
        if bad_line_count:
            detail_parts.append(f"line_count text={line_count} attrs={attr_line_count}")
        return [
            finding(
                "FAIL",
                "plan3",
                "b000315_mineru_prose_wrap",
                "; ".join(detail_parts),
            )
        ]
    return [
        finding(
            "PASS",
            "plan3",
            "b000315_mineru_prose_wrap",
            f"internal MinerU prose wraps collapsed on {block.get('block_id')}; display boundaries preserved",
        )
    ]


def _normalize_multiline_text(text: str) -> str:
    return "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())


def _display_text_carrier(
    candidate_by_id: dict[str, dict[str, Any]], text: str
) -> dict[str, Any] | None:
    return _typed_text_carrier(candidate_by_id, text, "display_block")


def _paragraph_text_carrier(
    candidate_by_id: dict[str, dict[str, Any]], text: str
) -> dict[str, Any] | None:
    return _typed_text_carrier(candidate_by_id, text, "paragraph")


def _typed_text_carrier(
    candidate_by_id: dict[str, dict[str, Any]], text: str, block_type: str
) -> dict[str, Any] | None:
    if not text:
        return None
    normalized = "".join(str(text).split())
    for block in candidate_by_id.values():
        if block.get("type") != block_type:
            continue
        candidate_text = "".join(text_of(block).split())
        if normalized and normalized in candidate_text:
            return block
    return None


def _text_carriers(candidate_by_id: dict[str, dict[str, Any]], text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    normalized = "".join(str(text).split())
    carriers: list[dict[str, Any]] = []
    for block in candidate_by_id.values():
        candidate_text = "".join(text_of(block).split())
        if normalized and normalized in candidate_text:
            carriers.append(block)
    return carriers


def check_plan4_footnote_contract(
    baseline_by_id: dict[str, dict[str, Any]],
    candidate_by_id: dict[str, dict[str, Any]],
) -> list[Finding]:
    old_footnotes = {
        block_id: text_of(block)
        for block_id, block in baseline_by_id.items()
        if block.get("type") == "footnote"
    }
    new_footnotes = {
        block_id: text_of(block)
        for block_id, block in candidate_by_id.items()
        if block.get("type") == "footnote"
    }
    changed = [
        block_id
        for block_id in sorted(set(old_footnotes) & set(new_footnotes))
        if old_footnotes[block_id] != new_footnotes[block_id]
    ]
    old_markers = sum(
        1 for text in old_footnotes.values() if FOOTNOTE_MARKER_RE.match(text.strip())
    )
    new_markers = sum(
        1 for text in new_footnotes.values() if FOOTNOTE_MARKER_RE.match(text.strip())
    )
    if changed:
        return [
            finding(
                "FAIL",
                "plan4",
                "canonical_footnote_text_contract",
                f"{len(changed)} footnote texts changed in canonical; sample {changed[:8]}",
            )
        ]
    return [
        finding(
            "PASS",
            "plan4",
            "canonical_footnote_text_contract",
            f"canonical footnote text preserved; marker-like count {old_markers}->{new_markers}",
        )
    ]


def check_plan5_tables(candidate_by_id: dict[str, dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for block_id, expected_substring in PLAN5_TABLE_NOTES.items():
        block = _table_note_carrier(candidate_by_id, expected_substring) or candidate_by_id.get(
            block_id
        )
        attrs = attrs_of(block)
        notes = attrs.get("table_notes")
        if block is None or block.get("type") != "table":
            findings.append(finding("FAIL", "plan5", block_id, "expected table block"))
            continue
        if not isinstance(notes, list):
            findings.append(finding("FAIL", "plan5", block_id, "expected attrs.table_notes list"))
            continue
        joined = "\n".join(str(note) for note in notes)
        if expected_substring not in joined:
            findings.append(
                finding(
                    "FAIL",
                    "plan5",
                    block_id,
                    f"missing expected table note substring {expected_substring!r}",
                )
            )
            continue
        markers = [note for note in notes if is_continuation_marker(str(note))]
        if markers:
            findings.append(
                finding(
                    "FAIL",
                    "plan5",
                    block_id,
                    f"table_notes contains continuation markers {markers}",
                )
            )
            continue
        findings.append(
            finding(
                "PASS",
                "plan5",
                block_id,
                f"table_notes contains source note on {block.get('block_id')}",
            )
        )

    blocks_with_alignment = [
        block.get("block_id")
        for block in candidate_by_id.values()
        if (attrs_of(block).get("cell_alignments") is not None)
    ]
    if blocks_with_alignment:
        findings.append(
            finding(
                "PASS",
                "plan5",
                "cell_alignments_present",
                f"found on blocks {blocks_with_alignment}",
            )
        )
    else:
        findings.append(
            finding(
                "WARN",
                "plan5",
                "cell_alignments_present",
                "no canonical table uses attrs.cell_alignments; only renderer support can be verified",
            )
        )
    return findings


def _table_note_carrier(
    candidate_by_id: dict[str, dict[str, Any]], expected_substring: str
) -> dict[str, Any] | None:
    for block in candidate_by_id.values():
        if block.get("type") != "table":
            continue
        notes = attrs_of(block).get("table_notes")
        if not isinstance(notes, list):
            continue
        joined = "\n".join(str(note) for note in notes)
        if expected_substring in joined:
            return block
    return None


def check_extra_changes(
    baseline_by_id: dict[str, dict[str, Any]],
    candidate_by_id: dict[str, dict[str, Any]],
) -> list[Finding]:
    findings: list[Finding] = []
    old_ids = set(baseline_by_id)
    new_ids = set(candidate_by_id)
    removed = sorted(old_ids - new_ids)
    added = sorted(new_ids - old_ids)
    unexpected_removed = [
        block_id
        for block_id in removed
        if block_id not in PLAN1_EXPECTED_REMOVED and block_id not in PLAN3_ALLOWED_CHANGED_IDS
    ]
    unexpected_added = [
        block_id for block_id in added if not block_id.endswith(ALLOWED_NEW_BLOCK_SUFFIXES)
    ]
    if unexpected_removed:
        findings.append(
            finding(
                "FAIL",
                "regression",
                "unexpected_removed_blocks",
                f"{len(unexpected_removed)} unexpected removed blocks; sample {unexpected_removed[:12]}",
            )
        )
    else:
        findings.append(finding("PASS", "regression", "unexpected_removed_blocks", "none"))

    if unexpected_added:
        findings.append(
            finding(
                "FAIL",
                "regression",
                "unexpected_added_blocks",
                f"{len(unexpected_added)} unexpected added blocks; sample {unexpected_added[:12]}",
            )
        )
    else:
        findings.append(finding("PASS", "regression", "unexpected_added_blocks", "none"))

    common = old_ids & new_ids
    unexpected_type_changes: list[str] = []
    changed_fields = Counter()
    for block_id in sorted(common):
        old_block = baseline_by_id[block_id]
        new_block = candidate_by_id[block_id]
        if block_id in PLAN3_ALLOWED_CHANGED_IDS:
            continue
        if old_block.get("type") != new_block.get("type"):
            expected = block_id in PLAN2_DISPLAY_BLOCKS or block_id in PLAN2_PARAGRAPHS
            if not expected:
                unexpected_type_changes.append(
                    f"{block_id}:{old_block.get('type')}->{new_block.get('type')}"
                )
        for key in sorted(set(old_block) | set(new_block)):
            if old_block.get(key) != new_block.get(key):
                changed_fields[key] += 1

    if unexpected_type_changes:
        findings.append(
            finding(
                "FAIL",
                "regression",
                "unexpected_type_changes",
                f"sample {unexpected_type_changes[:12]}",
            )
        )
    else:
        findings.append(finding("PASS", "regression", "unexpected_type_changes", "none"))

    findings.append(
        finding(
            "INFO",
            "regression",
            "diff_summary",
            (
                f"old={len(old_ids)} new={len(new_ids)} common={len(common)} "
                f"added={len(added)} removed={len(removed)} changed_fields={dict(changed_fields)}"
            ),
        )
    )
    return findings


def check_display_scope_regression(
    baseline_by_id: dict[str, dict[str, Any]],
    candidate_by_id: dict[str, dict[str, Any]],
) -> list[Finding]:
    """Ensure a display-block-focused change did not spill into other structures."""
    findings: list[Finding] = []
    old_ids = set(baseline_by_id)
    new_ids = set(candidate_by_id)
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    target_carrier_ids = _display_target_text_carrier_ids(baseline_by_id, candidate_by_id)
    allowed_target_ids = PLAN2_DISPLAY_BLOCKS | PLAN2_PARAGRAPHS | target_carrier_ids

    unexpected_added = [
        block_id for block_id in added if not block_id.endswith(ALLOWED_NEW_BLOCK_SUFFIXES)
    ]
    unexpected_removed = [block_id for block_id in removed if block_id not in allowed_target_ids]

    if unexpected_added:
        findings.append(
            finding(
                "FAIL",
                "display_regression",
                "unexpected_added_blocks",
                f"{len(unexpected_added)} non-display-split blocks added; sample {unexpected_added[:12]}",
            )
        )
    else:
        findings.append(finding("PASS", "display_regression", "unexpected_added_blocks", "none"))

    if unexpected_removed:
        findings.append(
            finding(
                "FAIL",
                "display_regression",
                "unexpected_removed_blocks",
                f"{len(unexpected_removed)} unrelated blocks removed; sample {unexpected_removed[:12]}",
            )
        )
    else:
        findings.append(finding("PASS", "display_regression", "unexpected_removed_blocks", "none"))

    unexpected_common_changes: list[str] = []
    for block_id in sorted(old_ids & new_ids):
        if block_id in PLAN3_ALLOWED_CHANGED_IDS or block_id in allowed_target_ids:
            continue
        old_block = baseline_by_id[block_id]
        new_block = candidate_by_id[block_id]
        changed_fields = {
            key
            for key in sorted(set(old_block) | set(new_block))
            if old_block.get(key) != new_block.get(key)
        }
        if not changed_fields:
            continue
        old_type = old_block.get("type")
        new_type = new_block.get("type")
        attr_only_display_change = (
            old_type == new_type
            and old_type in DISPLAY_REFACTOR_ATTR_ONLY_TYPES
            and changed_fields <= {"attrs"}
        )
        if attr_only_display_change:
            continue
        unexpected_common_changes.append(
            f"{block_id}:{old_type}->{new_type}:{','.join(sorted(changed_fields))}"
        )

    if unexpected_common_changes:
        findings.append(
            finding(
                "FAIL",
                "display_regression",
                "unexpected_common_block_changes",
                f"sample {unexpected_common_changes[:12]}",
            )
        )
    else:
        findings.append(
            finding("PASS", "display_regression", "unexpected_common_block_changes", "none")
        )

    findings.append(
        finding(
            "INFO",
            "display_regression",
            "scope_summary",
            (
                f"target_ids={sorted(allowed_target_ids)} added={len(added)} "
                f"removed={len(removed)} common={len(old_ids & new_ids)}"
            ),
        )
    )
    return findings


def _display_target_text_carrier_ids(
    baseline_by_id: dict[str, dict[str, Any]],
    candidate_by_id: dict[str, dict[str, Any]],
) -> set[str]:
    out: set[str] = set()
    for block_map in (baseline_by_id, candidate_by_id):
        for block_id, block in block_map.items():
            text = text_of(block)
            if any(
                needle in text
                for needle in (
                    *PLAN2_PARAGRAPH_TEXTS.values(),
                    *PLAN2_DISPLAY_TEXTS.values(),
                    *PLAN2_EXACT_DISPLAY_TEXTS.values(),
                )
            ):
                out.add(block_id)
    return out


def _normalize_plans(plans: set[str] | None) -> set[str]:
    if not plans or "all" in plans:
        return set(ALL_PLANS)
    return set(plans)


def run_checks(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    plans: set[str] | None = None,
) -> list[Finding]:
    baseline_by_id = blocks_by_id(baseline)
    candidate_by_id = blocks_by_id(candidate)
    selected = _normalize_plans(plans)
    findings: list[Finding] = []
    if "plan1" in selected:
        findings.extend(check_plan1_figures(baseline_by_id, candidate_by_id))
    if "plan2" in selected:
        findings.extend(check_plan2_display(baseline_by_id, candidate_by_id))
    if "plan3" in selected:
        findings.extend(check_plan3_mineru_newlines(candidate_by_id))
    if "plan4" in selected:
        findings.extend(check_plan4_footnote_contract(baseline_by_id, candidate_by_id))
    if "plan5" in selected:
        findings.extend(check_plan5_tables(candidate_by_id))
    if "regression" in selected:
        findings.extend(check_extra_changes(baseline_by_id, candidate_by_id))
    if "display-regression" in selected:
        findings.extend(check_display_scope_regression(baseline_by_id, candidate_by_id))
    return findings


def print_text(findings: list[Finding]) -> None:
    for status in ["FAIL", "WARN", "PASS", "INFO"]:
        rows = [item for item in findings if item.status == status]
        if not rows:
            continue
        print(f"\n{status}")
        for item in rows:
            print(f"- [{item.plan}] {item.check}: {item.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--plan",
        action="append",
        choices=[
            "all",
            "plan1",
            "plan2",
            "plan3",
            "plan4",
            "plan5",
            "regression",
            "display-regression",
        ],
        help="Run only selected plan checks. Repeat for multiple plans. Defaults to all.",
    )
    parser.add_argument(
        "--scope",
        choices=["all", "display_block"],
        default="all",
        help="Shortcut scope. display_block runs plan2 plus display-only regression checks.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    selected_plans = set(args.plan or [])
    if args.scope == "display_block" and not selected_plans:
        selected_plans = set(DISPLAY_REFACTOR_TARGET_PLANS)
    findings = run_checks(
        load_document(args.baseline),
        load_document(args.candidate),
        plans=selected_plans or None,
    )
    if args.json:
        print(json.dumps([item.__dict__ for item in findings], ensure_ascii=False, indent=2))
    else:
        print_text(findings)
    return 1 if any(item.status == "FAIL" for item in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
