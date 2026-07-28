from __future__ import annotations

from typing import Any

from inkline.canonical.page_layout.contract import (
    PAGE_LAYOUT_ANALYSIS_SCHEMA_NAME,
    PAGE_LAYOUT_ANALYSIS_SCHEMA_VERSION,
)
from inkline.canonical.schema import ValidationError

PAGE_RECORD_FIELDS = {"page", "page_size", "body_lane", "coverage", "role_signals"}
BODY_LANE_FIELDS = {
    "profile_scope",
    "profile_source",
    "page_width",
    "page_height",
    "body_left",
    "body_right",
    "body_width",
    "book_body_width",
    "body_width_delta",
    "indent_unit",
    "line_height",
    "normal_gap_y",
    "display_gap_y",
    "reference_fragment_count",
}
ROLE_SIGNAL_FIELDS = {
    "kind_counts",
    "role_hint_counts",
    "content_count",
    "text_count",
    "visual_count",
    "body_zone_footnote_count",
    "visual_area_ratio",
    "text_area_ratio",
    "centered_text_ratio",
    "tall_text_count",
}


def validate_page_layout_analysis(analysis: dict[str, Any]) -> None:
    """Validate the development contract for parser-neutral layout evidence."""

    if set(analysis) != {"metadata", "book_layout_profile", "pages", "audit"}:
        raise ValidationError("page layout analysis has invalid top-level fields")
    _validate_metadata(analysis.get("metadata"))
    _validate_pages(analysis.get("pages"))
    if not isinstance(analysis.get("book_layout_profile"), dict):
        raise ValidationError("page layout analysis book_layout_profile must be object")
    if not isinstance(analysis.get("audit"), dict):
        raise ValidationError("page layout analysis audit must be object")


def _validate_metadata(value: Any) -> None:
    metadata = value
    if not isinstance(metadata, dict):
        raise ValidationError("page layout analysis metadata must be object")
    if set(metadata) != {"schema_name", "schema_version", "doc_id"}:
        raise ValidationError("page layout analysis metadata has invalid fields")
    expected_metadata = {
        "schema_name": PAGE_LAYOUT_ANALYSIS_SCHEMA_NAME,
        "schema_version": PAGE_LAYOUT_ANALYSIS_SCHEMA_VERSION,
    }
    for field, expected in expected_metadata.items():
        if metadata.get(field) != expected:
            raise ValidationError(f"page layout analysis metadata.{field} must be {expected}")
    if not isinstance(metadata.get("doc_id"), str) or not metadata["doc_id"]:
        raise ValidationError("page layout analysis metadata.doc_id must be non-empty string")


def _validate_pages(value: Any) -> None:
    pages = value
    if not isinstance(pages, list):
        raise ValidationError("page layout analysis pages must be list")
    page_numbers: list[int] = []
    for index, record in enumerate(pages):
        if not isinstance(record, dict):
            raise ValidationError(f"page layout analysis pages[{index}] must be object")
        if set(record) != PAGE_RECORD_FIELDS:
            raise ValidationError(f"page layout analysis pages[{index}] has invalid fields")
        if not isinstance(record.get("page"), int):
            raise ValidationError(f"page layout analysis pages[{index}].page must be integer")
        _validate_page_record(record, index)
        page_numbers.append(record["page"])
    if page_numbers != sorted(set(page_numbers)):
        raise ValidationError("page layout analysis pages must be unique and ordered")


def _validate_page_record(record: dict[str, Any], index: int) -> None:
    page_size = record.get("page_size")
    if not isinstance(page_size, dict) or set(page_size) != {"width", "height"}:
        raise ValidationError(f"page layout analysis pages[{index}].page_size is invalid")
    coverage = record.get("coverage")
    if (
        not isinstance(coverage, dict)
        or set(coverage) != {"profile_status"}
        or not isinstance(coverage.get("profile_status"), str)
    ):
        raise ValidationError(f"page layout analysis pages[{index}].coverage is invalid")
    role_signals = record.get("role_signals")
    if not isinstance(role_signals, dict) or set(role_signals) != ROLE_SIGNAL_FIELDS:
        raise ValidationError(f"page layout analysis pages[{index}].role_signals is invalid")
    _validate_body_lane(record.get("body_lane"), index)


def _validate_body_lane(value: Any, index: int) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValidationError(f"page layout analysis pages[{index}].body_lane must be object")
    expected_fields = set(BODY_LANE_FIELDS)
    if value.get("profile_source") == "nearest_page":
        expected_fields.add("profile_source_page")
    if set(value) != expected_fields:
        raise ValidationError(f"page layout analysis pages[{index}].body_lane has invalid fields")
