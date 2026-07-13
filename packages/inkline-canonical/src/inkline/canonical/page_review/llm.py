"""LLM request construction for bounded semantic page review."""

from __future__ import annotations

import json
from typing import Any


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


def page_review_llm_prompt(input_data: dict[str, Any]) -> str:
    return (
        "You classify selected book pages for a strict JSON contract.\n"
        "Only classify the supplied candidate pages. Do not add, omit, or reorder pages. "
        "Do not change the front/body/back boundary; it was already established from the TOC.\n\n"
        "Return strict JSON only:\n"
        "{\n"
        '  "page_reviews": [\n'
        "    {\n"
        '      "page": 1,\n'
        '      "page_role": "title_page",\n'
        '      "text_flow_action": "exclude",\n'
        '      "visual_asset_action": "retain",\n'
        '      "confidence": "high"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "page_role must be one of: cover_page, back_cover, front_visual_page, "
        "half_title_page, title_page, copyright_page, toc_page, front_text_page, "
        "visual_page, table_or_chart_page, blank_page, unknown.\n"
        "text_flow_action must be one of: include, exclude, metadata_only, needs_review.\n"
        "visual_asset_action must be one of: retain, not_needed, needs_review.\n"
        "confidence must be one of: high, medium, low.\n\n"
        "Action rules:\n"
        "- text_flow_action=include: the page OCR text remains eligible for reading-flow nodes.\n"
        "- text_flow_action=exclude: do not turn page OCR text into reading-flow nodes.\n"
        "- text_flow_action=metadata_only: retain page evidence only for later metadata extraction.\n"
        "- visual_asset_action=retain: preserve a rendered page image as a v2 asset, independently "
        "of whether text remains in reading flow.\n"
        "- visual_asset_action=not_needed: no rendered full-page visual asset is needed.\n"
        "- needs_review: visual evidence remains insufficient.\n\n"
        "Every page_reviews item must contain exactly these keys and no others: page, page_role, "
        "text_flow_action, visual_asset_action, confidence. In particular, use page rather than "
        "page_number; do not emit image quality scores, descriptions, explanations, or analyses.\n\n"
        "Use the page image, position in the supplied sequence, and the structural signals as "
        "evidence. Do not infer a page role from the meaning of OCR text alone.\n\n"
        f"Input JSON:\n{json.dumps(input_data, ensure_ascii=False, indent=2)}"
    )
