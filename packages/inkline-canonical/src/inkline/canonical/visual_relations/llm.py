"""Canonical-owned bounded request and response rules for visual relation review."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

VISUAL_RELATION_REVIEW_PROMPT_VERSION = "visual-relation-review-v1"


def visual_relation_review_prompt(request: Mapping[str, Any]) -> str:
    """Return the bounded instruction sent with exactly one page image."""

    return (
        "Review only this one physical page. Select caption_of groups using only "
        "the supplied candidate observation ids. Do not transcribe text, infer "
        "cross-page relations, or add ids. Return JSON with groups, "
        "unpaired_asset_observation_ids, and unpaired_caption_observation_ids. "
        f"Page: {request['page']}; page asset: {request['page_asset_id']}; "
        f"candidate records: {json.dumps(request['candidates'], ensure_ascii=False)}."
    )


def build_visual_relation_review_request(
    *,
    page: int,
    page_asset_id: str,
    asset_observation_ids: Sequence[str],
    caption_observation_ids: Sequence[str],
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the sole callback payload, deliberately limited to one page's ids."""

    assets = list(asset_observation_ids)
    captions = list(caption_observation_ids)
    request = {
        "page": page,
        "page_asset_id": page_asset_id,
        "asset_observation_ids": assets,
        "caption_observation_ids": captions,
        "candidate_observation_ids": assets + captions,
        "candidates": _candidate_records(candidates, assets + captions),
    }
    request["prompt"] = visual_relation_review_prompt(request)
    request["prompt_version"] = VISUAL_RELATION_REVIEW_PROMPT_VERSION
    return request


def _candidate_records(
    candidates: Sequence[Mapping[str, Any]], expected_ids: list[str]
) -> list[dict[str, Any]]:
    records = [dict(candidate) for candidate in candidates]
    if [record.get("observation_id") for record in records] != expected_ids:
        raise ValueError("visual review candidate records must match supplied endpoint ids")
    required = {"observation_id", "kind", "role_hint", "bbox", "text"}
    if any(set(record) != required for record in records):
        raise ValueError("visual review candidate records have invalid fields")
    return records


def normalize_visual_relation_review_response(
    value: Any,
    *,
    asset_observation_ids: Sequence[str],
    caption_observation_ids: Sequence[str],
) -> dict[str, Any] | None:
    """Accept only a complete, source-bounded model decision response."""

    if not isinstance(value, Mapping) or set(value) != {
        "groups",
        "unpaired_asset_observation_ids",
        "unpaired_caption_observation_ids",
    }:
        return None
    assets = set(asset_observation_ids)
    captions = set(caption_observation_ids)
    groups_value = value.get("groups")
    if not isinstance(groups_value, Sequence) or isinstance(groups_value, str | bytes):
        return None
    groups: list[dict[str, Any]] = []
    used_assets: set[str] = set()
    used_captions: set[str] = set()
    for group in groups_value:
        if not isinstance(group, Mapping) or set(group) != {
            "asset_observation_ids",
            "caption_observation_ids",
            "confidence",
        }:
            return None
        group_assets = _id_list(group.get("asset_observation_ids"))
        group_captions = _id_list(group.get("caption_observation_ids"))
        confidence = group.get("confidence")
        if (
            group_assets is None
            or group_captions is None
            or not group_assets
            or not group_captions
            or not set(group_assets) <= assets
            or not set(group_captions) <= captions
            or used_assets.intersection(group_assets)
            or used_captions.intersection(group_captions)
            or confidence not in {"low", "medium", "high"}
        ):
            return None
        used_assets.update(group_assets)
        used_captions.update(group_captions)
        groups.append(
            {
                "asset_observation_ids": group_assets,
                "caption_observation_ids": group_captions,
                "confidence": confidence,
            }
        )
    unpaired_assets = _id_list(value.get("unpaired_asset_observation_ids"))
    unpaired_captions = _id_list(value.get("unpaired_caption_observation_ids"))
    if (
        unpaired_assets is None
        or unpaired_captions is None
        or not set(unpaired_assets) <= assets - used_assets
        or not set(unpaired_captions) <= captions - used_captions
        or used_assets | set(unpaired_assets) != assets
        or used_captions | set(unpaired_captions) != captions
    ):
        return None
    return {
        "groups": groups,
        "unpaired_asset_observation_ids": unpaired_assets,
        "unpaired_caption_observation_ids": unpaired_captions,
    }


def _id_list(value: Any) -> list[str] | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    ids = list(value)
    if not all(isinstance(item, str) and item for item in ids) or len(ids) != len(set(ids)):
        return None
    return ids
