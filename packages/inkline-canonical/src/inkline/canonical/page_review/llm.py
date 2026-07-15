"""LLM request construction for bounded semantic page review."""

from __future__ import annotations

import json
from typing import Any

PAGE_REVIEW_PROMPT_VERSION = "2.3-hardcover-external-wrap"

_PROMPT_PROFILES = {
    "front_special",
    "front_residual_unknown",
    "body_section_start",
    "visual_sparse_text",
    "mixed_visual_body",
    "textual_table",
    "general",
}


def page_review_groups(candidate_pages: list[int], *, max_pages: int) -> list[list[int]]:
    """Keep visual review batches bounded while retaining every physical page number."""

    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    groups: list[list[int]] = []
    current: list[int] = []
    for run in _contiguous_runs(candidate_pages):
        while run:
            capacity = max_pages - len(current)
            if len(run) <= capacity:
                current.extend(run)
                break
            if current:
                groups.append(current)
                current = []
                continue
            groups.append(run[:max_pages])
            run = run[max_pages:]
    if current:
        groups.append(current)
    return groups


def _contiguous_runs(pages: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for page in pages:
        if not runs or page != runs[-1][-1] + 1:
            runs.append([page])
            continue
        runs[-1].append(page)
    return runs


def page_review_prompt_profile(page_record: dict[str, Any]) -> str:
    """Select one focused visual-review instruction profile from structural evidence."""

    context = page_record.get("skeleton_context") or {}
    signals = set(page_record.get("signals") or [])
    visual_kinds = set(page_record.get("visual_kinds") or [])
    if context.get("matter") == "pre_body":
        return "front_special"
    if "table_region" in visual_kinds:
        return "textual_table"
    if "image_region" in visual_kinds:
        return "mixed_visual_body" if "body_profile" in signals else "visual_sparse_text"
    if context.get("is_body_section_start") is True:
        return "body_section_start"
    if "visual_sparse_text" in signals:
        return "visual_sparse_text"
    if "visual_verifier_candidate" in signals:
        return "mixed_visual_body"
    return "general"


def page_review_profile_groups(
    candidate_pages: list[int], page_records: dict[int, dict[str, Any]], *, max_pages: int
) -> list[dict[str, Any]]:
    """Batch pages by focused review profile without mixing instructions."""

    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    pages_by_group: dict[tuple[str, str], list[int]] = {}
    group_order: list[tuple[str, str]] = []
    for page in candidate_pages:
        record = page_records[page]
        profile = page_review_prompt_profile(record)
        matter = _page_review_matter(record)
        group_key = (matter, profile)
        if group_key not in pages_by_group:
            pages_by_group[group_key] = []
            group_order.append(group_key)
        pages_by_group[group_key].append(page)

    groups: list[dict[str, Any]] = []
    for matter, profile in group_order:
        pages = pages_by_group[(matter, profile)]
        for start in range(0, len(pages), max_pages):
            groups.append(
                {
                    "matter": matter,
                    "prompt_profile": profile,
                    "pages": pages[start : start + max_pages],
                }
            )
    return groups


def _page_review_matter(page_record: dict[str, Any]) -> str:
    context = page_record.get("skeleton_context")
    if isinstance(context, dict):
        matter = context.get("matter")
        if matter in {"pre_body", "body", "back_matter"}:
            return str(matter)
    return "unknown"


def page_review_llm_prompt(input_data: dict[str, Any], *, profile: str = "general") -> str:
    """Compose a short common contract with one focused visual-review profile."""

    if profile not in _PROMPT_PROFILES:
        raise ValueError(f"unknown page review prompt profile: {profile}")
    return (
        "Classify selected book pages. The input is structural evidence, not a prior decision.\n"
        "Only classify the supplied candidate pages. Do not add, omit, or reorder pages. "
        "Do not change the front/body/back boundary.\n"
        "Return strict JSON only:\n"
        "{\n"
        '  "page_reviews": [\n'
        "    {\n"
        '      "page": 1,\n'
        '      "page_role": "visual_page",\n'
        '      "book_block_position": "external_wrap",\n'
        '      "special_page_kind": "title_page",\n'
        '      "text_flow_action": "exclude",\n'
        '      "visual_asset_action": "retain",\n'
        '      "confidence": "high"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "page_role must be one of: text_flow_page, visual_page.\n"
        "book_block_position must be one of: external_wrap, front_matter, body, back_matter, unknown. "
        "Use external_wrap only for a cover, back cover, or cover flap that belongs to the outer "
        "binding rather than the book block. Use front_matter for a book-internal preliminary page. "
        "Required pairs: cover_page/back_cover/cover_flap/dust_jacket_spread/front_board/back_board -> external_wrap; "
        "half_title_page/title_page/dedication_page/acknowledgments_page/copyright_page/toc_page/blank_page -> front_matter.\n"
        "For copyright_page, use visual_page, front_matter, metadata_only, and retain.\n"
        "special_page_kind must be one of: cover_page, back_cover, cover_flap, dust_jacket_spread, front_board, back_board, half_title_page, "
        "title_page, dedication_page, acknowledgments_page, copyright_page, toc_page, blank_page, or null. It describes a special "
        "page identity and must not be used for ordinary body pages. When it is absent, emit the JSON "
        "literal null without quotes, never the string \\\"null\\\".\n"
        "text_flow_action must be one of: include, exclude, metadata_only, needs_review.\n"
        "visual_asset_action must be one of: retain, not_needed, needs_review.\n"
        "confidence must be one of: high, medium, low.\n\n"
        f"Review profile: {profile}.\n"
        f"Profile instruction: {_profile_instruction(profile)}\n"
        "- text_flow_action=include: the page OCR text remains eligible for reading-flow nodes.\n"
        "- text_flow_action=exclude: do not turn page OCR text into reading-flow nodes.\n"
        "- visual_page must use text_flow_action=exclude. Captions and labels alone are not "
        "independent body paragraphs.\n"
        "- text_flow_action=metadata_only: retain page evidence only for later metadata extraction.\n"
        "- visual_asset_action=retain: preserve a rendered page image as a v2 asset, independently "
        "of whether text remains in reading flow.\n"
        "- visual_asset_action=not_needed: no rendered full-page visual asset is needed.\n"
        "- needs_review: visual evidence remains insufficient.\n\n"
        "Every page_reviews item must contain exactly these keys and no others: page, page_role, "
        "book_block_position, special_page_kind, text_flow_action, visual_asset_action, confidence. In particular, use page rather than "
        "page_number; do not emit image quality scores, descriptions, explanations, or analyses.\n\n"
        "Use the page image, position in the supplied sequence, and the structural signals as "
        "evidence. Do not infer a page role from the meaning of OCR text alone.\n\n"
        f"Input JSON:\n{json.dumps(input_data, ensure_ascii=False, indent=2)}"
    )


def _profile_instruction(profile: str) -> str:
    instructions = {
        "front_special": (
            "This is a pre-body physical range, not a claim that every page is front matter. Identify "
            "external-wrap pages (cover, back cover, or cover flap) separately from book-block pages "
            "(half title, title, dedication, acknowledgments, copyright, TOC, or blank). "
            "A sparse centered page dedicating the book to a person or memory is dedication_page. "
            "A page headed Acknowledgments, Acknowledgements, 致谢, or 鸣谢 is acknowledgments_page, not "
            "dedication_page; it is ordinary front prose and uses text_flow_page/include/not_needed. "
            "A back cover can appear near the PDF beginning, but requires a rear-cover panel such as ISBN, price, barcode, "
            "or a full back-cover blurb. A narrow folded cover panel with author biography, publisher/contact "
            "details, or a QR code is cover_flap rather than back_cover. When a sequence is cover, panel, "
            "barcode back cover, panel, both panels are cover_flap. External-wrap pages use "
            "visual_page/exclude/retain. A flattened image showing a whole dust jacket with front cover, "
            "back cover, spine, and one or more flaps is dust_jacket_spread, not cover_flap. The exposed "
            "hardcover front board after a dust jacket is removed is front_board; its reverse is back_board."
        ),
        "front_residual_unknown": (
            "This pre-body page was not localized by a TOC section boundary and remains unresolved after "
            "the initial visual review selection. Decide whether it belongs to the external binding or the "
            "internal front matter. A normal reading-flow text page inside the book block is front_matter, "
            "text_flow_page, include, and not_needed. Do not use title_page merely because a page has a "
            "heading. Use external_wrap only for an actual cover, back cover, or cover flap."
        ),
        "body_section_start": (
            "Every page is a TOC-confirmed body-section start. Return text_flow_page, "
            "special_page_kind=null, and text_flow_action=include; its heading belongs in reading flow."
        ),
        "visual_sparse_text": (
            "visual_sparse_text means a visual asset has no body-text profile. Return "
            "visual_page/exclude/retain unless the image visibly contains a continuous narrative paragraph. "
            "Labels, legends, place names, and captions are not narrative paragraphs."
        ),
        "mixed_visual_body": (
            "Use an inclusion-first decision. A continuous body paragraph wins over visual area. "
            "Return text_flow_page/include when a map, image, or diagram shares the page with "
            "independent continuous body prose, even when the visual occupies most of the page. "
            "A narrow explanatory block directly attached to an image is a caption, even when it has "
            "multiple lines; it is not body prose. Return visual_page/exclude only when every readable "
            "text region is a caption, legend, place name, or label."
        ),
        "textual_table": (
            "A table_region is presumed to be a readable cell-based table or its continuation. Return "
            "text_flow_page/include, including when the table fills the page. Return visual_page/exclude "
            "only when the apparent table has labels or captions but no readable rows, columns, or cells."
        ),
        "general": (
            "Return text_flow_page/include for independent body prose; otherwise return visual_page/exclude "
            "for a visual with only labels or captions."
        ),
    }
    return instructions[profile]
