"""Apply strictly scoped multimodal page-review decisions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.schema import ValidationError

PAGE_REVIEW_TEXT_FLOW_ACTIONS = {
    "include",
    "exclude",
    "metadata_only",
    "needs_review",
}
PAGE_REVIEW_VISUAL_ASSET_ACTIONS = {"retain", "not_needed", "needs_review"}
PAGE_REVIEW_ROLES = {
    "cover_page",
    "back_cover",
    "front_visual_page",
    "half_title_page",
    "title_page",
    "copyright_page",
    "toc_page",
    "front_text_page",
    "visual_page",
    "table_or_chart_page",
    "blank_page",
    "unknown",
}
PAGE_REVIEW_CONFIDENCES = {"high", "medium", "low"}


def resolve_page_review(
    plan: dict[str, Any],
    decisions: list[dict[str, Any]],
    *,
    llm_model: str,
) -> dict[str, Any]:
    """Resolve every selected candidate exactly once, without altering other pages."""

    candidate_pages = _candidate_pages(plan)
    decisions_by_page = validate_page_review_decisions(decisions, candidate_pages)
    resolved = deepcopy(plan)
    for record in resolved.get("pages") or []:
        page = record.get("page")
        decision = decisions_by_page.get(page)
        if decision is None:
            continue
        record["page_role"] = decision["page_role"]
        record["text_flow_action"] = decision["text_flow_action"]
        record["visual_asset_action"] = decision["visual_asset_action"]
        record["decision_source"] = "llm_page_review"
        record["llm_review_status"] = "sent_and_resolved"
        record["confidence"] = decision["confidence"]
    resolved["llm"] = {
        "used": True,
        "model": llm_model,
        "source": "page_review_image_llm",
        "reviewed_pages": candidate_pages,
    }
    return resolved


def validate_resolved_page_review(review: dict[str, Any]) -> None:
    """Require every LLM candidate to have a non-deferred review action."""

    candidate_pages = _candidate_pages(review)
    records_by_page = {
        record.get("page"): record
        for record in review.get("pages") or []
        if isinstance(record, dict) and isinstance(record.get("page"), int)
    }
    for page in candidate_pages:
        record = records_by_page.get(page)
        if record is None:
            raise ValidationError(f"page_review missing candidate page {page}")
        if record.get("decision_source") != "llm_page_review":
            raise ValidationError(f"page_review candidate page {page} lacks LLM decision")
        if record.get("llm_review_status") != "sent_and_resolved":
            raise ValidationError(f"page_review candidate page {page} has not been resolved")
        if (
            record.get("text_flow_action") == "needs_review"
            or record.get("visual_asset_action") == "needs_review"
        ):
            raise ValidationError(f"page_review has unresolved candidate page {page}")


def _candidate_pages(plan: dict[str, Any]) -> list[int]:
    pages = plan.get("candidate_pages")
    if not isinstance(pages, list) or not all(isinstance(page, int) and page > 0 for page in pages):
        raise ValidationError("page_review.candidate_pages must be positive integers")
    if len(set(pages)) != len(pages):
        raise ValidationError("page_review.candidate_pages must not contain duplicates")
    return list(pages)


def validate_page_review_decisions(
    decisions: list[dict[str, Any]], candidate_pages: list[int]
) -> dict[int, dict[str, Any]]:
    if not isinstance(decisions, list):
        raise ValidationError("page_review decisions must be a list")
    expected = set(candidate_pages)
    resolved: dict[int, dict[str, Any]] = {}
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise ValidationError(f"page_review decisions[{index}] must be object")
        page = decision.get("page")
        if not isinstance(page, int) or page not in expected:
            raise ValidationError(f"page_review decisions[{index}].page is not a selected candidate")
        if page in resolved:
            raise ValidationError(f"duplicate page_review decision for page {page}")
        page_role = decision.get("page_role")
        if page_role not in PAGE_REVIEW_ROLES:
            raise ValidationError(f"page_review decisions[{index}].page_role is invalid")
        text_flow_action = decision.get("text_flow_action")
        if text_flow_action not in PAGE_REVIEW_TEXT_FLOW_ACTIONS:
            raise ValidationError(f"page_review decisions[{index}].text_flow_action is invalid")
        visual_asset_action = decision.get("visual_asset_action")
        if visual_asset_action not in PAGE_REVIEW_VISUAL_ASSET_ACTIONS:
            raise ValidationError(f"page_review decisions[{index}].visual_asset_action is invalid")
        confidence = decision.get("confidence")
        if confidence not in PAGE_REVIEW_CONFIDENCES:
            raise ValidationError(f"page_review decisions[{index}].confidence is invalid")
        resolved[page] = {
            "page_role": page_role,
            "text_flow_action": text_flow_action,
            "visual_asset_action": visual_asset_action,
            "confidence": confidence,
        }
    missing = sorted(expected - set(resolved))
    if missing:
        raise ValidationError(f"page_review decisions missing selected pages: {missing}")
    return resolved
