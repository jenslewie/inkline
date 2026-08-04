"""Deterministic candidate construction for same-page visual relation review."""

# ruff: noqa: PLR0914, PLR0915

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import pairwise
from typing import Any

from inkline.canonical.observed.index import ObservedIndex
from inkline.canonical.visual_relations.contract import (
    VISUAL_RELATION_REVIEW_SCHEMA_NAME,
    VISUAL_RELATION_REVIEW_SCHEMA_VERSION,
)
from inkline.canonical.visual_relations.llm import (
    VISUAL_RELATION_REVIEW_PROMPT_VERSION,
    build_visual_relation_review_request,
    normalize_visual_relation_review_response,
)
from inkline.canonical.visual_relations.validation import (
    validate_visual_relation_review_against_sources,
)

ReviewCallback = Callable[[dict[str, Any]], Any]


def build_visual_relation_review(
    observed_index: ObservedIndex,
    page_layout: dict[str, Any],
    page_review: dict[str, Any],
    table_flow: dict[str, Any],
    page_assets: dict[str, Any],
    *,
    review_callback: ReviewCallback | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Build an audit artifact without inferring a relation from geometry alone."""

    assets_by_page = _page_assets_by_page(page_assets)
    excluded_captions = _table_caption_ids(table_flow)
    pages = _reviewed_pages(page_review)
    evidence: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    unpaired_assets: list[str] = []
    unpaired_captions: list[str] = []
    unresolved: list[dict[str, Any]] = []
    next_evidence = 1
    next_group = 1
    next_candidate = 1

    for page in pages:
        page_observations = [
            observation
            for observation_id in observed_index.observation_ids_by_page.get(page, ())
            if (observation := observed_index.observations_by_id[observation_id]) is not None
        ]
        observations_by_id = {
            str(observation["observation_id"]): observation for observation in page_observations
        }
        assets = _ordered_ids(page_observations, "image_region")
        if not assets:
            continue
        captions = _candidate_caption_ids(
            page_observations,
            assets,
            page_layout,
            excluded_captions,
            observed_index.observations_by_id,
        )
        parser_groups = _parser_groups(page_observations, assets, captions)
        used_assets = {asset_id for asset_ids, _ in parser_groups for asset_id in asset_ids}
        used_captions = {
            caption_id for _, caption_ids in parser_groups for caption_id in caption_ids
        }
        for asset_ids, caption_ids in parser_groups:
            evidence_id = f"vre{next_evidence:06d}"
            next_evidence += 1
            evidence.append(
                _evidence(
                    evidence_id,
                    "parser_provenance",
                    page,
                    asset_ids + caption_ids,
                    [],
                    None,
                )
            )
            groups.append(
                _group(
                    f"vg{next_group:06d}",
                    asset_ids,
                    caption_ids,
                    page,
                    evidence_id,
                    "parser_provenance",
                    "high",
                )
            )
            next_group += 1

        remaining_assets = [asset_id for asset_id in assets if asset_id not in used_assets]
        remaining_captions = [
            caption_id for caption_id in captions if caption_id not in used_captions
        ]
        if not remaining_assets and not remaining_captions:
            continue
        image_id = assets_by_page.get(page)
        response = None
        if review_callback is not None and model_name and image_id:
            request = build_visual_relation_review_request(
                page=page,
                page_asset_id=image_id,
                asset_observation_ids=remaining_assets,
                caption_observation_ids=remaining_captions,
                candidates=[
                    _candidate_record(observations_by_id[observation_id])
                    for observation_id in remaining_assets + remaining_captions
                ],
            )
            try:
                response = normalize_visual_relation_review_response(
                    review_callback(request),
                    asset_observation_ids=remaining_assets,
                    caption_observation_ids=remaining_captions,
                )
            except Exception:  # bounded transport failure remains an explicit unresolved state
                response = None
        if response is not None:
            assert image_id is not None
            evidence_id = f"vre{next_evidence:06d}"
            next_evidence += 1
            evidence.append(
                _evidence(
                    evidence_id,
                    "bounded_multimodal_review",
                    page,
                    remaining_assets + remaining_captions,
                    [image_id],
                    model_name,
                )
            )
            for decision in response["groups"]:
                groups.append(
                    _group(
                        f"vg{next_group:06d}",
                        decision["asset_observation_ids"],
                        decision["caption_observation_ids"],
                        page,
                        evidence_id,
                        "bounded_multimodal_review",
                        decision["confidence"],
                    )
                )
                next_group += 1
            unpaired_assets.extend(response["unpaired_asset_observation_ids"])
            unpaired_captions.extend(response["unpaired_caption_observation_ids"])
            continue

        evidence_id = f"vre{next_evidence:06d}"
        next_evidence += 1
        evidence.append(
            _evidence(
                evidence_id,
                "deterministic_candidate",
                page,
                remaining_assets + remaining_captions,
                [image_id] if image_id else [],
                None,
            )
        )
        reason = "model_not_run" if review_callback is None else "model_unavailable_or_invalid"
        unresolved.append(
            {
                "candidate_id": f"vrc{next_candidate:06d}",
                "asset_observation_ids": remaining_assets,
                "caption_observation_ids": remaining_captions,
                "physical_pages": [page],
                "evidence_ids": [evidence_id],
                "reason": reason,
            }
        )
        next_candidate += 1

    review = {
        "metadata": {
            "schema_name": VISUAL_RELATION_REVIEW_SCHEMA_NAME,
            "schema_version": VISUAL_RELATION_REVIEW_SCHEMA_VERSION,
            "doc_id": observed_index.doc_id,
        },
        "evidence": evidence,
        "visual_groups": groups,
        "unpaired_asset_observation_ids": unpaired_assets,
        "unpaired_caption_observation_ids": unpaired_captions,
        "unresolved_candidates": unresolved,
    }
    validate_visual_relation_review_against_sources(
        review, observed_index, page_layout, page_review, page_assets, table_flow=table_flow
    )
    return review


def _reviewed_pages(page_review: Mapping[str, Any]) -> list[int]:
    return sorted(
        int(record["page"])
        for record in page_review.get("pages", [])
        if isinstance(record, Mapping) and type(record.get("page")) is int and record["page"] > 0
    )


def _page_assets_by_page(page_assets: Mapping[str, Any]) -> dict[int, str]:
    values: dict[int, str] = {}
    for item in page_assets.get("images", []):
        if not isinstance(item, Mapping):
            continue
        source = item.get("source")
        page = source.get("page") if isinstance(source, Mapping) else None
        image_id = item.get("image_id")
        if type(page) is int and isinstance(image_id, str) and image_id:
            values.setdefault(page, image_id)
    return values


def _table_caption_ids(table_flow: Mapping[str, Any]) -> set[str]:
    return {
        caption_id
        for table in table_flow.get("tables", [])
        if isinstance(table, Mapping)
        for caption_id in table.get("caption_observation_ids", [])
        if isinstance(caption_id, str)
    }


def _ordered_ids(observations: list[Mapping[str, Any]], kind: str) -> list[str]:
    return [
        str(observation["observation_id"])
        for observation in sorted(observations, key=_observation_order)
        if observation.get("kind") == kind
    ]


def _candidate_caption_ids(
    observations: list[Mapping[str, Any]],
    assets: list[str],
    page_layout: Mapping[str, Any],
    excluded: set[str],
    source_observations: Mapping[str, Any],
) -> list[str]:
    by_id = {str(item["observation_id"]): item for item in observations}
    asset_records = [by_id[item] for item in assets]
    initial = [
        observation
        for observation in sorted(observations, key=_observation_order)
        if str(observation["observation_id"]) not in excluded
        and not _is_direct_table_caption(observation, source_observations)
        and observation.get("kind") in {"text_region", "footnote_region"}
        and _is_caption_signal(observation, asset_records, page_layout)
    ]
    selected = {str(item["observation_id"]) for item in initial}
    ordered = sorted(observations, key=_observation_order)
    for previous, following in pairwise(ordered):
        if (
            str(previous["observation_id"]) in selected
            and previous.get("role_hint") in {"caption_text", "title_text"}
            and str(following["observation_id"]) not in excluded
            and not _is_direct_table_caption(following, source_observations)
            and following.get("kind") in {"text_region", "footnote_region"}
            and _adjacent_caption_line(previous, following)
        ):
            selected.add(str(following["observation_id"]))
    return [
        str(item["observation_id"]) for item in ordered if str(item["observation_id"]) in selected
    ]


def _is_caption_signal(
    observation: Mapping[str, Any], assets: list[Mapping[str, Any]], page_layout: Mapping[str, Any]
) -> bool:
    attrs = observation.get("attrs")
    parent = attrs.get("visual_parent_observation_id") if isinstance(attrs, Mapping) else None
    if isinstance(parent, str) and parent:
        return True
    if observation.get("role_hint") == "caption_text":
        return any(_within_corridor(observation, asset, page_layout) for asset in assets)
    if observation.get("role_hint") == "title_text":
        return any(_within_corridor(observation, asset, page_layout) for asset in assets)
    return False


def _within_corridor(
    text: Mapping[str, Any], asset: Mapping[str, Any], page_layout: Mapping[str, Any]
) -> bool:
    text_bbox = _bbox(text.get("bbox"))
    asset_bbox = _bbox(asset.get("bbox"))
    if text_bbox is None or asset_bbox is None:
        return False
    width, height, normal_gap = _page_corridor(page_layout, int(text["page"]))
    horizontal_gap = max(asset_bbox[0] - text_bbox[2], text_bbox[0] - asset_bbox[2], 0.0)
    vertical_gap = max(asset_bbox[1] - text_bbox[3], text_bbox[1] - asset_bbox[3], 0.0)
    overlap = min(text_bbox[2], asset_bbox[2]) - max(text_bbox[0], asset_bbox[0])
    return (
        horizontal_gap <= max(48.0, width * 0.12)
        and vertical_gap <= max(normal_gap * 6, height * 0.16)
    ) or (overlap > 0 and vertical_gap <= max(72.0, height * 0.12))


def _adjacent_caption_line(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_bbox = _bbox(left.get("bbox"))
    right_bbox = _bbox(right.get("bbox"))
    if left_bbox is None or right_bbox is None:
        return False
    gap = right_bbox[1] - left_bbox[3]
    horizontal_overlap = min(left_bbox[2], right_bbox[2]) - max(left_bbox[0], right_bbox[0])
    return 0 <= gap <= max(48.0, (left_bbox[3] - left_bbox[1]) * 2.5) and horizontal_overlap >= 0


def _parser_groups(
    observations: list[Mapping[str, Any]], assets: list[str], captions: list[str]
) -> list[tuple[list[str], list[str]]]:
    by_id = {str(item["observation_id"]): item for item in observations}
    unmatched = set(captions)
    groups: list[tuple[list[str], list[str]]] = []
    for asset_id in assets:
        direct = [
            caption_id
            for caption_id in captions
            if caption_id in unmatched
            and _direct_parent(by_id[caption_id]) == asset_id
            and not _is_table_caption(by_id[caption_id])
        ]
        if not direct:
            direct = _unique_exact_parser_captions(by_id[asset_id], by_id, unmatched)
        if direct:
            unmatched.difference_update(direct)
            groups.append(([asset_id], direct))
    return groups


def _direct_parent(observation: Mapping[str, Any]) -> str | None:
    attrs = observation.get("attrs")
    value = attrs.get("visual_parent_observation_id") if isinstance(attrs, Mapping) else None
    return value if isinstance(value, str) and value else None


def _is_table_caption(observation: Mapping[str, Any]) -> bool:
    attrs = observation.get("attrs")
    return isinstance(attrs, Mapping) and attrs.get("source_kind") == "table_caption"


def _is_direct_table_caption(
    observation: Mapping[str, Any], source_observations: Mapping[str, Any]
) -> bool:
    attrs = observation.get("attrs")
    parent = attrs.get("visual_parent_observation_id") if isinstance(attrs, Mapping) else None
    source = source_observations.get(parent) if isinstance(parent, str) and parent else None
    return (
        isinstance(attrs, Mapping)
        and attrs.get("source_kind") == "table_caption"
        and isinstance(source, Mapping)
        and source.get("kind") == "table_region"
    )


def _unique_exact_parser_captions(
    asset: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    unmatched: set[str],
) -> list[str]:
    payload = asset.get("parser_payload")
    raw = payload.get("raw") if isinstance(payload, Mapping) else None
    content = raw.get("content") if isinstance(raw, Mapping) else None
    values = content.get("image_caption") if isinstance(content, Mapping) else None
    if not isinstance(values, tuple | list):
        return []
    result: list[str] = []
    for value in values:
        text = _parser_caption_text(value)
        if text is None:
            return []
        matches = [
            candidate_id
            for candidate_id in unmatched
            if by_id[candidate_id].get("text") == text
            and not _is_table_caption(by_id[candidate_id])
        ]
        if len(matches) != 1:
            return []
        result.extend(matches)
    return result


def _parser_caption_text(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if (
        isinstance(value, Mapping)
        and value.get("type") == "text"
        and isinstance(value.get("content"), str)
        and value["content"]
    ):
        return value["content"]
    return None


def _evidence(
    evidence_id: str,
    kind: str,
    page: int,
    observation_ids: list[str],
    page_asset_ids: list[str],
    model_name: str | None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "observation_ids": observation_ids,
        "pages": [page],
        "page_asset_ids": page_asset_ids,
        "model_name": model_name,
        "prompt_version": VISUAL_RELATION_REVIEW_PROMPT_VERSION if model_name else None,
    }


def _candidate_record(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Materialize only a supplied same-page endpoint for a bounded review request."""

    bbox = observation.get("bbox")
    return {
        "observation_id": str(observation["observation_id"]),
        "kind": str(observation["kind"]),
        "role_hint": str(observation.get("role_hint") or "unknown"),
        "bbox": list(bbox) if isinstance(bbox, tuple | list) else None,
        "text": str(observation.get("text") or ""),
    }


def _group(
    group_id: str,
    asset_ids: list[str],
    caption_ids: list[str],
    page: int,
    evidence_id: str,
    source: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "visual_group_id": group_id,
        "asset_observation_ids": asset_ids,
        "caption_observation_ids": caption_ids,
        "relation_type": "caption_of",
        "physical_pages": [page],
        "evidence_ids": [evidence_id],
        "decision_source": source,
        "confidence": confidence,
    }


def _observation_order(observation: Mapping[str, Any]) -> tuple[int, float, float, str]:
    attrs = observation.get("attrs")
    reading_order = attrs.get("reading_order") if isinstance(attrs, Mapping) else None
    bbox = _bbox(observation.get("bbox"))
    return (
        int(reading_order) if isinstance(reading_order, int) else 1_000_000,
        bbox[1] if bbox else float("inf"),
        bbox[0] if bbox else float("inf"),
        str(observation["observation_id"]),
    )


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, tuple | list) or len(value) != 4:
        return None
    if not all(isinstance(item, int | float) and not isinstance(item, bool) for item in value):
        return None
    return tuple(float(item) for item in value)  # type: ignore[return-value]


def _page_corridor(page_layout: Mapping[str, Any], page: int) -> tuple[float, float, float]:
    for record in page_layout.get("pages", []):
        if isinstance(record, Mapping) and record.get("page") == page:
            size = record.get("page_size")
            if isinstance(size, Mapping):
                width, height = size.get("width"), size.get("height")
                if isinstance(width, int | float) and isinstance(height, int | float):
                    lane = record.get("body_lane")
                    normal_gap = lane.get("normal_gap_y") if isinstance(lane, Mapping) else None
                    return (
                        float(width),
                        float(height),
                        float(normal_gap)
                        if isinstance(normal_gap, int | float) and normal_gap > 0
                        else max(12.0, float(height) * 0.02),
                    )
    return 1000.0, 1000.0, 20.0
