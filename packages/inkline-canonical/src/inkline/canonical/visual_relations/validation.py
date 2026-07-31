from __future__ import annotations

from typing import Any

from inkline.canonical.artifact_dag.validation import (
    validate_choice,
    validate_confidence,
    validate_doc_ids,
    validate_exact_fields,
    validate_id_list,
    validate_metadata,
    validate_nullable_string,
    validate_ordered_ids,
    validate_pages,
    validate_reason,
)
from inkline.canonical.observed.index import ObservedIndex
from inkline.canonical.schema import ValidationError
from inkline.canonical.visual_relations.contract import (
    EVIDENCE_FIELDS,
    TOP_LEVEL_FIELDS,
    UNRESOLVED_CANDIDATE_FIELDS,
    VISUAL_DECISION_SOURCES,
    VISUAL_EVIDENCE_KINDS,
    VISUAL_GROUP_FIELDS,
    VISUAL_RELATION_REVIEW_SCHEMA_NAME,
    VISUAL_RELATION_REVIEW_SCHEMA_VERSION,
)


def validate_visual_relation_review(review: dict[str, Any]) -> None:
    """Validate immutable visual groups and explicit endpoint audit states."""

    validate_exact_fields(review, TOP_LEVEL_FIELDS, "visual_relation_review")
    validate_metadata(
        review["metadata"],
        schema_name=VISUAL_RELATION_REVIEW_SCHEMA_NAME,
        schema_version=VISUAL_RELATION_REVIEW_SCHEMA_VERSION,
        path="visual_relation_review.metadata",
    )
    evidence_ids = _validate_evidence(review["evidence"])
    grouped_assets, grouped_captions = _validate_groups(
        review["visual_groups"], evidence_ids
    )
    unpaired_assets = validate_id_list(
        review["unpaired_asset_observation_ids"],
        "visual_relation_review.unpaired_asset_observation_ids",
    )
    unpaired_captions = validate_id_list(
        review["unpaired_caption_observation_ids"],
        "visual_relation_review.unpaired_caption_observation_ids",
    )
    unresolved_assets, unresolved_captions = _validate_unresolved(
        review["unresolved_candidates"], evidence_ids
    )
    _validate_endpoint_partitions(
        grouped_assets,
        grouped_captions,
        set(unpaired_assets),
        set(unpaired_captions),
        unresolved_assets,
        unresolved_captions,
    )


def validate_visual_relation_review_against_sources(
    review: dict[str, Any],
    observed_index: ObservedIndex,
    page_layout: dict[str, Any],
    page_review: dict[str, Any],
    page_assets: dict[str, Any],
    *,
    table_flow: dict[str, Any] | None = None,
) -> None:
    """Validate visual endpoint identity, kind, page, and exclusive caption ownership."""

    validate_visual_relation_review(review)
    doc_id = review["metadata"]["doc_id"]
    if observed_index.doc_id != doc_id:
        raise ValidationError("ObservedIndex doc_id differs from VisualRelationReview")
    validate_doc_ids(
        doc_id,
        {"PageLayoutAnalysis": page_layout, "PageReview": page_review},
    )
    observations = observed_index.observations_by_id
    reviewed_pages = {
        record.get("page")
        for record in page_review.get("pages", [])
        if isinstance(record, dict)
    }
    table_caption_ids = _table_caption_ids(table_flow)
    page_assets_by_id = _page_assets_by_id(page_assets)
    for evidence in review["evidence"]:
        for page_asset_id in evidence["page_asset_ids"]:
            asset_page = page_assets_by_id.get(page_asset_id)
            if asset_page is None or asset_page not in evidence["pages"]:
                raise ValidationError(
                    f"visual evidence references invalid page asset: {page_asset_id}"
                )
    for asset_id in _all_endpoint_ids(review, "asset_observation_ids"):
        observation = observations.get(asset_id)
        if observation is None or observation.get("kind") != "image_region":
            raise ValidationError(f"visual asset endpoint is invalid: {asset_id}")
        if observation.get("page") not in reviewed_pages:
            raise ValidationError(f"visual asset endpoint page is not reviewed: {asset_id}")
    for caption_id in _all_endpoint_ids(review, "caption_observation_ids"):
        observation = observations.get(caption_id)
        if observation is None or observation.get("kind") not in {
            "text_region",
            "footnote_region",
        }:
            raise ValidationError(f"visual caption endpoint is invalid: {caption_id}")
        if caption_id in table_caption_ids:
            raise ValidationError(f"caption endpoint is already owned by TableFlow: {caption_id}")
    for group in review["visual_groups"]:
        pages = {
            int(observations[endpoint_id]["page"])
            for endpoint_id in (
                group["asset_observation_ids"] + group["caption_observation_ids"]
            )
        }
        if pages != set(group["physical_pages"]):
            raise ValidationError(
                f"visual group page provenance differs: {group['visual_group_id']}"
            )


def _validate_evidence(value: Any) -> set[str]:
    records = validate_ordered_ids(
        value, id_field="evidence_id", prefix="vre", path="visual_relation_review.evidence"
    )
    ids: set[str] = set()
    for index, record in enumerate(records):
        path = f"visual_relation_review.evidence[{index}]"
        validate_exact_fields(record, EVIDENCE_FIELDS, path)
        kind = validate_choice(record["kind"], VISUAL_EVIDENCE_KINDS, f"{path}.kind")
        validate_id_list(record["observation_ids"], f"{path}.observation_ids", required=True)
        validate_pages(record["pages"], f"{path}.pages", required=True)
        page_asset_ids = validate_id_list(
            record["page_asset_ids"], f"{path}.page_asset_ids"
        )
        model = validate_nullable_string(record["model_name"], f"{path}.model_name")
        prompt = validate_nullable_string(record["prompt_version"], f"{path}.prompt_version")
        if kind == "bounded_multimodal_review" and (model is None or prompt is None):
            raise ValidationError(f"{path} model review requires model and prompt provenance")
        if kind == "bounded_multimodal_review" and not page_asset_ids:
            raise ValidationError(f"{path} model review requires a PageAssets image")
        if kind == "parser_provenance" and (model is not None or prompt is not None):
            raise ValidationError(f"{path} parser provenance must not claim model provenance")
        ids.add(record["evidence_id"])
    return ids


def _validate_groups(value: Any, evidence_ids: set[str]) -> tuple[set[str], set[str]]:
    records = validate_ordered_ids(
        value, id_field="visual_group_id", prefix="vg", path="visual_relation_review.visual_groups"
    )
    assets: set[str] = set()
    captions: set[str] = set()
    for index, record in enumerate(records):
        path = f"visual_relation_review.visual_groups[{index}]"
        validate_exact_fields(record, VISUAL_GROUP_FIELDS, path)
        group_assets = set(
            validate_id_list(
                record["asset_observation_ids"],
                f"{path}.asset_observation_ids",
                required=True,
            )
        )
        group_captions = set(
            validate_id_list(
                record["caption_observation_ids"],
                f"{path}.caption_observation_ids",
                required=True,
            )
        )
        if assets & group_assets or captions & group_captions:
            raise ValidationError("visual endpoints must have one group owner")
        assets.update(group_assets)
        captions.update(group_captions)
        if record["relation_type"] != "caption_of":
            raise ValidationError(f"{path}.relation_type is invalid")
        pages = validate_pages(record["physical_pages"], f"{path}.physical_pages", required=True)
        if len(pages) != 1:
            raise ValidationError(f"{path} must be a same-page visual group")
        _validate_known_evidence(record["evidence_ids"], evidence_ids, path)
        validate_choice(record["decision_source"], VISUAL_DECISION_SOURCES, f"{path}.decision_source")
        validate_confidence(record["confidence"], f"{path}.confidence")
    return assets, captions


def _validate_unresolved(value: Any, evidence_ids: set[str]) -> tuple[set[str], set[str]]:
    records = validate_ordered_ids(
        value,
        id_field="candidate_id",
        prefix="vrc",
        path="visual_relation_review.unresolved_candidates",
    )
    assets: set[str] = set()
    captions: set[str] = set()
    for index, record in enumerate(records):
        path = f"visual_relation_review.unresolved_candidates[{index}]"
        validate_exact_fields(record, UNRESOLVED_CANDIDATE_FIELDS, path)
        candidate_assets = set(
            validate_id_list(record["asset_observation_ids"], f"{path}.asset_observation_ids")
        )
        candidate_captions = set(
            validate_id_list(record["caption_observation_ids"], f"{path}.caption_observation_ids")
        )
        if not candidate_assets and not candidate_captions:
            raise ValidationError(f"{path} requires at least one endpoint")
        if assets & candidate_assets or captions & candidate_captions:
            raise ValidationError("unresolved visual endpoints must have one candidate owner")
        assets.update(candidate_assets)
        captions.update(candidate_captions)
        validate_pages(record["physical_pages"], f"{path}.physical_pages", required=True)
        _validate_known_evidence(record["evidence_ids"], evidence_ids, path)
        validate_reason(record["reason"], f"{path}.reason")
    return assets, captions


def _validate_known_evidence(value: Any, known: set[str], path: str) -> None:
    evidence_ids = set(validate_id_list(value, f"{path}.evidence_ids", required=True))
    if not evidence_ids <= known:
        raise ValidationError(f"{path}.evidence_ids contain unknown evidence")


def _validate_endpoint_partitions(
    grouped_assets: set[str],
    grouped_captions: set[str],
    unpaired_assets: set[str],
    unpaired_captions: set[str],
    unresolved_assets: set[str],
    unresolved_captions: set[str],
) -> None:
    if grouped_assets & unpaired_assets or grouped_assets & unresolved_assets:
        raise ValidationError("visual asset endpoint appears in multiple audit states")
    if unpaired_assets & unresolved_assets:
        raise ValidationError("visual asset endpoint appears in multiple audit states")
    if grouped_captions & unpaired_captions or grouped_captions & unresolved_captions:
        raise ValidationError("visual caption endpoint appears in multiple audit states")
    if unpaired_captions & unresolved_captions:
        raise ValidationError("visual caption endpoint appears in multiple audit states")


def _table_caption_ids(table_flow: dict[str, Any] | None) -> set[str]:
    if table_flow is None:
        return set()
    return {
        caption_id
        for table in table_flow.get("tables", [])
        if isinstance(table, dict)
        for caption_id in table.get("caption_observation_ids", [])
        if isinstance(caption_id, str)
    }


def _page_assets_by_id(page_assets: dict[str, Any]) -> dict[str, int]:
    indexed: dict[str, int] = {}
    images = page_assets.get("images", [])
    if not isinstance(images, list):
        raise ValidationError("PageAssets images must be list")
    for record in images:
        image_id = record.get("image_id") if isinstance(record, dict) else None
        source = record.get("source") if isinstance(record, dict) else None
        page = source.get("page") if isinstance(source, dict) else None
        if not isinstance(image_id, str) or not image_id or type(page) is not int or page <= 0:
            raise ValidationError("PageAssets image record is invalid")
        if image_id in indexed:
            raise ValidationError(f"duplicate PageAssets image_id: {image_id}")
        indexed[image_id] = page
    return indexed


def _all_endpoint_ids(review: dict[str, Any], field: str) -> set[str]:
    ids = {
        endpoint_id
        for collection in ("visual_groups", "unresolved_candidates")
        for record in review[collection]
        for endpoint_id in record[field]
    }
    unpaired_field = (
        "unpaired_asset_observation_ids"
        if field == "asset_observation_ids"
        else "unpaired_caption_observation_ids"
    )
    ids.update(review[unpaired_field])
    return ids
