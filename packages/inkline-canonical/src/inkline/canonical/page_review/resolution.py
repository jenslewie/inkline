"""Apply strictly scoped multimodal page-review decisions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.schema import ValidationError

PAGE_REVIEW_SCHEMA_VERSION = "0.8-shadow"
PAGE_REVIEW_TEXT_FLOW_ACTIONS = {
    "include",
    "exclude",
    "metadata_only",
    "needs_review",
}
PAGE_REVIEW_VISUAL_ASSET_ACTIONS = {"retain", "not_needed", "needs_review"}
PAGE_REVIEW_ROLES = {"text_flow_page", "visual_page"}
PAGE_REVIEW_BOOK_BLOCK_POSITIONS = {
    "external_wrap",
    "front_matter",
    "body",
    "back_matter",
    "unknown",
}
PAGE_REVIEW_SPECIAL_PAGE_KINDS = {
    "cover_page",
    "back_cover",
    "cover_flap",
    "dust_jacket_spread",
    "front_board",
    "back_board",
    "half_title_page",
    "title_page",
    "dedication_page",
    "acknowledgments_page",
    "copyright_page",
    "toc_page",
    "blank_page",
}
PAGE_REVIEW_CONFIDENCES = {"high", "medium", "low"}
_EXTERNAL_WRAP_SPECIAL_PAGE_KINDS = {
    "cover_page",
    "back_cover",
    "cover_flap",
    "dust_jacket_spread",
    "front_board",
    "back_board",
}
_FRONT_MATTER_SPECIAL_PAGE_KINDS = {
    "half_title_page",
    "title_page",
    "dedication_page",
    "acknowledgments_page",
    "copyright_page",
    "toc_page",
    "blank_page",
}
_COPYRIGHT_PAGE_POLICY = {
    "page_role": "visual_page",
    "book_block_position": "front_matter",
    "text_flow_action": "metadata_only",
    "visual_asset_action": "retain",
}
_ACKNOWLEDGMENTS_PAGE_POLICY = {
    "page_role": "text_flow_page",
    "book_block_position": "front_matter",
    "text_flow_action": "include",
    "visual_asset_action": "not_needed",
}
_EXTERNAL_WRAP_PAGE_POLICY = {
    "page_role": "visual_page",
    "text_flow_action": "exclude",
    "visual_asset_action": "retain",
}


def resolve_page_review(
    plan: dict[str, Any],
    decisions: list[dict[str, Any]],
    *,
    llm_model: str,
    llm_prompt_version: str,
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
        record["book_block_position"] = decision["book_block_position"]
        record["special_page_kind"] = decision["special_page_kind"]
        record["text_flow_action"] = decision["text_flow_action"]
        record["visual_asset_action"] = decision["visual_asset_action"]
        record["decision_source"] = "llm_page_review"
        record["llm_review_status"] = "sent_and_resolved"
        record["confidence"] = decision["confidence"]
    resolved["llm"] = {
        "model": llm_model,
        "prompt_version": llm_prompt_version,
    }
    return resolved


def validate_resolved_page_review(review: dict[str, Any]) -> None:
    """Require every LLM candidate to have a non-deferred review action."""

    candidate_pages = _candidate_pages(review)
    page_records = review.get("pages")
    if not isinstance(page_records, list):
        raise ValidationError("page_review.pages must be a list")
    for index, record in enumerate(page_records):
        _validate_page_record(record, f"page_review.pages[{index}]")
    records_by_page = {
        record.get("page"): record
        for record in page_records
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
        fields = _validate_page_record(
            decision, f"page_review decisions[{index}]", require_book_block_position=True
        )
        confidence = decision.get("confidence")
        if confidence not in PAGE_REVIEW_CONFIDENCES:
            raise ValidationError(f"page_review decisions[{index}].confidence is invalid")
        resolved[page] = {
            **fields,
            "confidence": confidence,
        }
    missing = sorted(expected - set(resolved))
    if missing:
        raise ValidationError(f"page_review decisions missing selected pages: {missing}")
    return resolved


def _validate_page_record(
    record: Any,
    path: str,
    *,
    require_book_block_position: bool = False,
) -> dict[str, str | None]:
    if not isinstance(record, dict):
        raise ValidationError(f"{path} must be object")
    fields = _normalized_page_fields(record, path)
    page_role = fields["page_role"]
    if page_role not in PAGE_REVIEW_ROLES:
        raise ValidationError(f"{path}.page_role is invalid")
    book_block_position = fields["book_block_position"]
    if require_book_block_position and book_block_position is None:
        raise ValidationError(f"{path}.book_block_position is required")
    if book_block_position not in PAGE_REVIEW_BOOK_BLOCK_POSITIONS:
        raise ValidationError(f"{path}.book_block_position is invalid")
    special_page_kind = fields["special_page_kind"]
    _validate_special_page_position(
        special_page_kind, book_block_position, path, required=require_book_block_position
    )
    text_flow_action = fields["text_flow_action"]
    if text_flow_action not in PAGE_REVIEW_TEXT_FLOW_ACTIONS:
        raise ValidationError(f"{path}.text_flow_action is invalid")
    if page_role == "visual_page" and text_flow_action == "include":
        raise ValidationError(f"{path}.visual_page cannot include text flow")
    visual_asset_action = fields["visual_asset_action"]
    if visual_asset_action not in PAGE_REVIEW_VISUAL_ASSET_ACTIONS:
        raise ValidationError(f"{path}.visual_asset_action is invalid")
    return fields


def _normalized_page_fields(record: dict[str, Any], path: str) -> dict[str, str | None]:
    """Apply deterministic policy after validating the model's special-page identity."""

    special_page_kind = _special_page_kind(record, path)
    fields = {
        "page_role": record.get("page_role"),
        "book_block_position": record.get("book_block_position"),
        "special_page_kind": special_page_kind,
        "text_flow_action": record.get("text_flow_action"),
        "visual_asset_action": record.get("visual_asset_action"),
    }
    if special_page_kind == "copyright_page":
        fields.update(_COPYRIGHT_PAGE_POLICY)
    if special_page_kind == "acknowledgments_page":
        fields.update(_ACKNOWLEDGMENTS_PAGE_POLICY)
    if special_page_kind in _EXTERNAL_WRAP_SPECIAL_PAGE_KINDS:
        fields.update(_EXTERNAL_WRAP_PAGE_POLICY)
    return fields


def _special_page_kind(record: dict[str, Any], path: str) -> str | None:
    if "special_page_kind" not in record:
        raise ValidationError(f"{path}.special_page_kind is required")
    value = record["special_page_kind"]
    if value == "null":
        return None
    if value is not None and value not in PAGE_REVIEW_SPECIAL_PAGE_KINDS:
        raise ValidationError(f"{path}.special_page_kind is invalid")
    return value


def _validate_special_page_position(
    special_page_kind: str | None,
    book_block_position: str | None,
    path: str,
    *,
    required: bool,
) -> None:
    if required and special_page_kind in _EXTERNAL_WRAP_SPECIAL_PAGE_KINDS and book_block_position != "external_wrap":
        raise ValidationError(f"{path}.special_page_kind requires external_wrap")
    if required and special_page_kind in _FRONT_MATTER_SPECIAL_PAGE_KINDS and book_block_position != "front_matter":
        raise ValidationError(f"{path}.special_page_kind requires front_matter")
