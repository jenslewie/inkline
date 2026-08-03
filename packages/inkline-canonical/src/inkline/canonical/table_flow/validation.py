from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from inkline.canonical.observed import ObservedIndex, validate_observed_document
from inkline.canonical.page_review import validate_resolved_page_review
from inkline.canonical.schema import ValidationError
from inkline.canonical.table_flow.contract import (
    REQUIRED_TABLE_FIELDS,
    REQUIRED_TOP_LEVEL_FIELDS,
    TABLE_FLOW_SCHEMA_NAME,
    TABLE_FLOW_SCHEMA_VERSION,
)


def validate_table_flow(table_flow: dict[str, Any]) -> None:
    _require_fields(table_flow, REQUIRED_TOP_LEVEL_FIELDS, "table_flow")
    if set(table_flow) != set(REQUIRED_TOP_LEVEL_FIELDS):
        raise ValidationError("TableFlow has invalid top-level fields")
    metadata = table_flow["metadata"]
    if set(metadata) != {"schema_name", "schema_version", "doc_id"}:
        raise ValidationError("TableFlow metadata has invalid fields")
    if metadata["schema_name"] != TABLE_FLOW_SCHEMA_NAME:
        raise ValidationError("TableFlow schema_name is invalid")
    if metadata["schema_version"] != TABLE_FLOW_SCHEMA_VERSION:
        raise ValidationError("TableFlow schema_version is invalid")
    if not isinstance(metadata["doc_id"], str) or not metadata["doc_id"]:
        raise ValidationError("TableFlow doc_id is invalid")

    table_ids: set[str] = set()
    consumed_observation_ids: set[str] = set()
    for index, table in enumerate(table_flow["tables"]):
        _validate_table(table, index, table_ids, consumed_observation_ids)
    for index, run in enumerate(table_flow["unresolved_table_observation_runs"]):
        _validate_observation_run(
            run,
            index,
            consumed_observation_ids,
            collection="unresolved_table_observation_runs",
            reasons={
                "missing_normalized_table_content",
                "continuation_without_primary",
                "page_review_splits_table_candidate",
            },
        )
    for index, run in enumerate(table_flow["excluded_table_observation_runs"]):
        _validate_observation_run(
            run,
            index,
            consumed_observation_ids,
            collection="excluded_table_observation_runs",
            reasons={"excluded_by_page_review"},
        )


def validate_table_flow_against_sources(
    table_flow: dict[str, Any],
    observed_document: dict[str, Any],
    observed_index: ObservedIndex,
    page_review: dict[str, Any],
) -> None:
    validate_table_flow(table_flow)
    validate_observed_document(observed_document)
    validate_resolved_page_review(page_review)
    if table_flow["metadata"]["doc_id"] != observed_index.doc_id:
        raise ValidationError("TableFlow and ObservedDocument doc_id values differ")
    if table_flow["metadata"]["doc_id"] != page_review["metadata"]["doc_id"]:
        raise ValidationError("TableFlow and PageReview doc_id values differ")
    table_observation_ids = {
        observation_id
        for observation_id, observation in observed_index.observations_by_id.items()
        if observation["kind"] == "table_region"
    }
    consumed = (
        {
            observation_id
            for table in table_flow["tables"]
            for observation_id in table["observation_ids"]
        }
        | {
            observation_id
            for run in table_flow["unresolved_table_observation_runs"]
            for observation_id in run["observation_ids"]
        }
        | {
            observation_id
            for run in table_flow["excluded_table_observation_runs"]
            for observation_id in run["observation_ids"]
        }
    )
    if consumed != table_observation_ids:
        raise ValidationError("TableFlow must consume every table observation exactly once")

    for table in table_flow["tables"]:
        _validate_table_sources(table, observed_index)
    for run in table_flow["unresolved_table_observation_runs"]:
        for observation_id in run["observation_ids"]:
            if observation_id not in table_observation_ids:
                raise ValidationError(
                    f"TableFlow unresolved observation is not a table: {observation_id}"
                )
    _validate_page_review_disposition(table_flow, page_review)


def _require_fields(
    value: Any,
    fields: Mapping[str, type[Any] | tuple[type[Any], ...]],
    path: str,
) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must be object")
    for field, expected in fields.items():
        if field not in value or not isinstance(value[field], expected):
            raise ValidationError(f"{path}.{field} is invalid")


def _validate_table(
    table: Any,
    index: int,
    table_ids: set[str],
    consumed_observation_ids: set[str],
) -> None:
    path = f"tables[{index}]"
    _require_fields(table, REQUIRED_TABLE_FIELDS, path)
    if set(table) != set(REQUIRED_TABLE_FIELDS):
        raise ValidationError(f"{path} has invalid fields")
    table_id = table["table_id"]
    if not table_id or table_id in table_ids:
        raise ValidationError(f"{path}.table_id is invalid")
    table_ids.add(table_id)
    if not table["html"].strip():
        raise ValidationError(f"{path}.html must be non-empty")
    _validate_pages(table["pages"], f"{path}.pages")
    _validate_ids(table["observation_ids"], f"{path}.observation_ids", required=True)
    _validate_ids(
        table["caption_observation_ids"],
        f"{path}.caption_observation_ids",
    )
    _validate_texts(table["caption_texts"], f"{path}.caption_texts")
    _validate_texts(table["footnote_texts"], f"{path}.footnote_texts")
    if table["primary_observation_id"] != table["observation_ids"][0]:
        raise ValidationError(f"{path}.primary_observation_id must be first")
    for observation_id in table["observation_ids"]:
        if observation_id in consumed_observation_ids:
            raise ValidationError(f"table observation consumed twice: {observation_id}")
        consumed_observation_ids.add(observation_id)
    if len(table["spans"]) != len(table["observation_ids"]):
        raise ValidationError(f"{path}.spans must cover every observation")
    for span_index, span in enumerate(table["spans"]):
        _validate_span(span, f"{path}.spans[{span_index}]")
    if [span["observation_id"] for span in table["spans"]] != table["observation_ids"]:
        raise ValidationError(f"{path}.spans must preserve observation order")
    if sorted({span["page"] for span in table["spans"]}) != table["pages"]:
        raise ValidationError(f"{path}.pages must match spans")


def _validate_span(span: Any, path: str) -> None:
    if not isinstance(span, dict) or set(span) != {"observation_id", "page", "bbox"}:
        raise ValidationError(f"{path} is invalid")
    if not isinstance(span["observation_id"], str) or not span["observation_id"]:
        raise ValidationError(f"{path}.observation_id is invalid")
    if not isinstance(span["page"], int) or isinstance(span["page"], bool) or span["page"] <= 0:
        raise ValidationError(f"{path}.page is invalid")
    bbox = span["bbox"]
    if bbox is not None and (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or not all(isinstance(value, int | float) for value in bbox)
    ):
        raise ValidationError(f"{path}.bbox is invalid")


def _validate_observation_run(
    run: Any,
    index: int,
    consumed_observation_ids: set[str],
    *,
    collection: str,
    reasons: set[str],
) -> None:
    path = f"{collection}[{index}]"
    if not isinstance(run, dict) or set(run) != {"observation_ids", "pages", "reason"}:
        raise ValidationError(f"{path} is invalid")
    _validate_ids(run["observation_ids"], f"{path}.observation_ids", required=True)
    _validate_pages(run["pages"], f"{path}.pages")
    if run["reason"] not in reasons:
        raise ValidationError(f"{path}.reason is invalid")
    for observation_id in run["observation_ids"]:
        if observation_id in consumed_observation_ids:
            raise ValidationError(f"table observation consumed twice: {observation_id}")
        consumed_observation_ids.add(observation_id)


def _validate_page_review_disposition(
    table_flow: dict[str, Any],
    page_review: dict[str, Any],
) -> None:
    included_pages = {
        int(record["page"])
        for record in page_review["pages"]
        if record["text_flow_action"] == "include"
    }
    if any(not set(table["pages"]) <= included_pages for table in table_flow["tables"]):
        raise ValidationError("TableFlow table includes a PageReview-excluded page")
    if any(
        not set(run["pages"]).isdisjoint(included_pages)
        for run in table_flow["excluded_table_observation_runs"]
    ):
        raise ValidationError("TableFlow excluded run contains a PageReview-included page")


def _validate_table_sources(table: dict[str, Any], index: ObservedIndex) -> None:
    for span in table["spans"]:
        observation_id = span["observation_id"]
        observation = index.observations_by_id.get(observation_id)
        if observation is None or observation["kind"] != "table_region":
            raise ValidationError(f"TableFlow source is not a table observation: {observation_id}")
        source_bbox = observation.get("bbox")
        normalized_source_bbox = list(source_bbox) if source_bbox is not None else None
        if int(observation["page"]) != span["page"] or normalized_source_bbox != span["bbox"]:
            raise ValidationError(f"TableFlow span differs from source: {observation_id}")
    primary = index.observations_by_id[table["primary_observation_id"]]
    attrs = primary.get("attrs")
    normalized = attrs.get("table") if isinstance(attrs, Mapping) else None
    if not isinstance(normalized, Mapping) or normalized.get("html") != table["html"]:
        raise ValidationError("TableFlow html differs from primary source")
    for caption_id in table["caption_observation_ids"]:
        caption = index.observations_by_id.get(caption_id)
        caption_attrs = caption.get("attrs") if isinstance(caption, Mapping) else None
        if (
            caption is None
            or caption["kind"] != "text_region"
            or not isinstance(caption_attrs, Mapping)
            or caption_attrs.get("source_kind") != "table_caption"
            or caption_attrs.get("visual_parent_observation_id") not in table["observation_ids"]
        ):
            raise ValidationError(f"TableFlow caption source is invalid: {caption_id}")


def _validate_ids(values: Any, path: str, *, required: bool = False) -> None:
    if not isinstance(values, list) or (required and not values):
        raise ValidationError(f"{path} is invalid")
    if not all(isinstance(value, str) and value for value in values):
        raise ValidationError(f"{path} must contain non-empty ids")
    if len(values) != len(set(values)):
        raise ValidationError(f"{path} must contain unique ids")


def _validate_texts(values: Any, path: str) -> None:
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value for value in values
    ):
        raise ValidationError(f"{path} must contain non-empty text")
    if len(values) != len(set(values)):
        raise ValidationError(f"{path} must contain unique text")


def _validate_pages(values: Any, path: str) -> None:
    if not isinstance(values, list) or not values:
        raise ValidationError(f"{path} must be non-empty")
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in values
    ):
        raise ValidationError(f"{path} must contain positive pages")
    if values != sorted(set(values)):
        raise ValidationError(f"{path} must be sorted and unique")
