"""Parser-neutral structural candidates for separate note-system review."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from inkline.canonical.note_system.contract import (
    NOTE_SYSTEM_REVIEW_SCHEMA_NAME,
    NOTE_SYSTEM_REVIEW_SCHEMA_VERSION,
)
from inkline.canonical.note_system.llm import (
    NOTE_SYSTEM_REVIEW_PROMPT_VERSION,
    build_note_system_review_request,
)
from inkline.canonical.note_system.validation import validate_note_system_review_against_sources
from inkline.canonical.observed.index import ObservedIndex

ReviewCallback = Callable[[dict[str, Any]], Any]


def build_note_system_review(
    observed_index: ObservedIndex,
    page_layout: Mapping[str, Any],
    skeleton: Mapping[str, Any],
    page_review: Mapping[str, Any],
    page_assets: Mapping[str, Any],
    *,
    review_callback: ReviewCallback | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Build unpromoted structural candidates, optionally accepting bounded model decisions."""

    assets_by_page = _assets_by_page(page_assets)
    candidates = _structural_candidates(observed_index, skeleton, page_review)
    evidence: list[dict[str, Any]] = []
    systems: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    next_evidence = next_system = next_candidate = 1
    for candidate in candidates:
        if candidate["is_explicit_page_footnote"] and review_callback is None:
            evidence_id = f"nse{next_evidence:06d}"
            next_evidence += 1
            evidence.append(_evidence(evidence_id, candidate, "structural_rule", [], None))
            systems.append(
                {
                    "note_system_id": f"ns{next_system:06d}",
                    "kind": "page_footnote",
                    "definition_ranges": [[candidate["pages"][0], candidate["pages"][0]]],
                    "reference_scope": "page",
                    "marker_styles": ["unknown"],
                    "reset_policy": "page",
                    "evidence_ids": [evidence_id],
                    "confidence": "high",
                }
            )
            next_system += 1
            continue
        response = None
        page_asset_ids = [
            assets_by_page[page] for page in candidate["pages"] if page in assets_by_page
        ]
        if review_callback is not None and model_name and page_asset_ids:
            request = build_note_system_review_request(
                pages=candidate["pages"],
                observation_ids=candidate["observation_ids"],
                skeleton_entry_indexes=candidate["skeleton_entry_indexes"],
                page_asset_ids=page_asset_ids,
                observations=[
                    observed_index.observations_by_id[observation_id]
                    for observation_id in candidate["observation_ids"]
                ],
            )
            try:
                response = _normalize_response(review_callback(request), candidate)
            except Exception:
                response = None
        if response:
            for decision in response:
                evidence_id = f"nse{next_evidence:06d}"
                next_evidence += 1
                system_candidate = _candidate_for_system(candidate, decision)
                evidence.append(
                    _evidence(
                        evidence_id,
                        system_candidate,
                        "bounded_multimodal_review",
                        page_asset_ids,
                        model_name,
                    )
                )
                systems.append(
                    {
                        "note_system_id": f"ns{next_system:06d}",
                        **decision,
                        "evidence_ids": [evidence_id],
                    }
                )
                next_system += 1
            continue
        evidence_id = f"nse{next_evidence:06d}"
        next_evidence += 1
        if response == []:
            evidence.append(
                _evidence(
                    evidence_id,
                    candidate,
                    "bounded_multimodal_review",
                    page_asset_ids,
                    model_name,
                )
            )
        else:
            evidence.append(_evidence(evidence_id, candidate, "structural_rule", [], None))
        unresolved.append(
            {
                "candidate_id": f"nsc{next_candidate:06d}",
                "pages": candidate["pages"],
                "observation_ids": candidate["observation_ids"],
                "evidence_ids": [evidence_id],
                "reason": _unresolved_reason(review_callback, response, page_asset_ids),
            }
        )
        next_candidate += 1
    review = {
        "metadata": {
            "schema_name": NOTE_SYSTEM_REVIEW_SCHEMA_NAME,
            "schema_version": NOTE_SYSTEM_REVIEW_SCHEMA_VERSION,
            "doc_id": observed_index.doc_id,
        },
        "evidence": evidence,
        "note_systems": systems,
        "unresolved_system_candidates": unresolved,
    }
    validate_note_system_review_against_sources(
        review, observed_index, page_layout, skeleton, page_review, page_assets
    )
    return review


def _unresolved_reason(
    review_callback: ReviewCallback | None,
    response: list[dict[str, Any]] | None,
    page_asset_ids: Sequence[str],
) -> str:
    if review_callback is None or not page_asset_ids:
        return "model_not_run"
    if response == []:
        return "model_did_not_confirm_system"
    return "model_unavailable_or_invalid"


def _candidate_for_system(
    candidate: Mapping[str, Any], decision: Mapping[str, Any]
) -> dict[str, Any]:
    definition_pages = {
        page
        for start, end in decision["definition_ranges"]
        for page in range(start, end + 1)
    }
    return {
        "pages": sorted(definition_pages),
        "observation_ids": list(candidate["observation_ids"]),
        "skeleton_entry_indexes": list(candidate["skeleton_entry_indexes"]),
    }


def _structural_candidates(
    observed_index: ObservedIndex, skeleton: Mapping[str, Any], page_review: Mapping[str, Any]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for page in sorted(_eligible_pages(page_review)):
        observation_ids = [
            observation_id
            for observation_id in observed_index.observation_ids_by_page.get(page, ())
            if _is_note_definition(observed_index.observations_by_id[observation_id])
        ]
        if observation_ids:
            candidates.append(
                {
                    "pages": [page],
                    "observation_ids": observation_ids,
                    "skeleton_entry_indexes": _skeleton_indexes_for_page(skeleton, page),
                    "is_explicit_page_footnote": True,
                }
            )
    return candidates


def _is_note_definition(observation: Mapping[str, Any]) -> bool:
    return (
        observation.get("kind") == "footnote_region"
        or observation.get("role_hint") == "footnote_text"
    )


def _eligible_pages(page_review: Mapping[str, Any]) -> set[int]:
    return {
        record["page"]
        for record in page_review.get("pages", ())
        if isinstance(record, Mapping)
        and type(record.get("page")) is int
        and record["page"] > 0
        and record.get("text_flow_action") != "needs_review"
    }


def _skeleton_indexes_for_page(skeleton: Mapping[str, Any], page: int) -> list[int]:
    return [
        record["entry_index"]
        for record in skeleton.get("toc_entries", ())
        if isinstance(record, Mapping)
        and type(record.get("entry_index")) is int
        and record.get("page") == page
    ]


def _assets_by_page(page_assets: Mapping[str, Any]) -> dict[int, str]:
    values: dict[int, str] = {}
    for item in page_assets.get("images", ()):
        source = item.get("source") if isinstance(item, Mapping) else None
        page = source.get("page") if isinstance(source, Mapping) else None
        image_id = item.get("image_id") if isinstance(item, Mapping) else None
        if type(page) is int and isinstance(image_id, str) and image_id:
            values.setdefault(page, image_id)
    return values


def _evidence(
    evidence_id: str,
    candidate: Mapping[str, Any],
    decision_source: str,
    page_asset_ids: Sequence[str],
    model_name: str | None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "observation_ids": list(candidate["observation_ids"]),
        "pages": list(candidate["pages"]),
        "skeleton_entry_indexes": list(candidate["skeleton_entry_indexes"]),
        "decision_source": decision_source,
        "page_asset_ids": list(page_asset_ids),
        "model_name": model_name,
        "prompt_version": NOTE_SYSTEM_REVIEW_PROMPT_VERSION if model_name is not None else None,
    }


def _normalize_response(response: Any, candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    expected = {
        "kind",
        "definition_ranges",
        "reference_scope",
        "marker_styles",
        "reset_policy",
        "confidence",
    }
    if (
        not isinstance(response, Mapping)
        or set(response) != {"systems"}
        or not isinstance(response["systems"], Sequence)
        or isinstance(response["systems"], str | bytes)
    ):
        raise ValueError("note-system response is invalid")
    normalized: list[dict[str, Any]] = []
    for value in response["systems"]:
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("note-system response system is invalid")
        ranges = value["definition_ranges"]
        if not isinstance(ranges, Sequence) or isinstance(ranges, str | bytes):
            raise ValueError("note-system response ranges are invalid")
        pages = {
            page
            for pair in ranges
            if isinstance(pair, Sequence)
            and len(pair) == 2
            and all(type(page) is int for page in pair)
            for page in range(pair[0], pair[1] + 1)
        }
        if not pages or not pages <= set(candidate["pages"]):
            raise ValueError("note-system response escapes candidate pages")
        normalized.append({key: _mutable(value[key]) for key in expected})
    return normalized


def _mutable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_mutable(nested) for nested in value]
    return value
