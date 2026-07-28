from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any

from inkline.canonical import (
    CanonicalArtifactBundle,
    build_book_skeleton_from_index,
    build_observed_index,
    build_page_layout_analysis,
    build_page_review_plan,
    build_text_flow,
    classify_observed_page_roles,
    validate_book_skeleton_against_index,
    validate_observed_document,
    validate_page_layout_analysis,
    validate_resolved_page_review,
    validate_text_flow_against_sources,
)
from inkline.canonical.observed.index import ObservedIndex
from inkline.workflow.artifact_store import ArtifactStore
from inkline.workflow.stage import Stage, run_stages

SkeletonBuilder = Callable[..., dict[str, Any]]
PageReviewBuilder = Callable[..., dict[str, Any]]
PageAssetsBuilder = Callable[..., dict[str, Any] | None]


def canonical_artifact_stages(
    *,
    skeleton_builder: SkeletonBuilder | None = None,
    page_review_builder: PageReviewBuilder | None = None,
    page_assets_builder: PageAssetsBuilder | None = None,
) -> tuple[Stage, ...]:
    """Declare the canonical DAG without executing any stage."""

    return (
        Stage(
            "observed_index",
            ("observed",),
            "observed_index",
            lambda observed: build_observed_index(observed),
            _validate_observed_index,
        ),
        Stage(
            "skeleton",
            ("observed", "observed_index"),
            "skeleton",
            skeleton_builder or _build_skeleton,
            _validate_skeleton,
        ),
        Stage(
            "page_layout",
            ("observed", "observed_index"),
            "page_layout",
            _build_page_layout,
            validate_page_layout_analysis,
        ),
        Stage(
            "page_review",
            ("observed", "skeleton", "page_layout"),
            "page_review",
            page_review_builder or _build_page_review,
            _validate_page_review_artifact,
        ),
        Stage(
            "text_flow",
            ("observed", "observed_index", "skeleton", "page_review", "page_layout"),
            "text_flow",
            _build_text_flow_if_resolved,
            _validate_optional_text_flow,
        ),
        Stage(
            "page_assets",
            ("observed", "page_review"),
            "page_assets",
            page_assets_builder or _build_page_assets,
            _validate_page_assets,
        ),
    )


def build_canonical_artifacts(
    observed_document: dict[str, Any],
    *,
    artifact_store: ArtifactStore | None = None,
    stages: Sequence[Stage] | None = None,
    on_stage_complete: Callable[[str, Any], None] | None = None,
) -> CanonicalArtifactBundle:
    """Build one coherent artifact bundle from a validated ObservedDocument."""

    validate_observed_document(observed_document)
    artifacts = run_stages(
        {"observed": observed_document},
        stages or canonical_artifact_stages(),
        artifact_store=artifact_store,
        on_stage_complete=on_stage_complete,
    )
    _validate_artifact_relationships(artifacts)
    return CanonicalArtifactBundle(
        observed=observed_document,
        observed_index=artifacts["observed_index"],
        skeleton=artifacts["skeleton"],
        page_layout=artifacts["page_layout"],
        page_review=artifacts["page_review"],
        text_flow=artifacts["text_flow"],
        page_assets=artifacts["page_assets"],
    )


def _build_skeleton(observed: dict[str, Any], observed_index: ObservedIndex) -> dict[str, Any]:
    del observed
    return build_book_skeleton_from_index(observed_index)


def _build_page_layout(observed: dict[str, Any], observed_index: ObservedIndex) -> dict[str, Any]:
    return build_page_layout_analysis(observed, observed_index)


def _build_page_review(
    observed: dict[str, Any], skeleton: dict[str, Any], page_layout: dict[str, Any]
) -> dict[str, Any]:
    page_roles = classify_observed_page_roles(observed, page_layout=page_layout)
    return build_page_review_plan(observed, skeleton, page_roles)


def _build_text_flow_if_resolved(
    observed: dict[str, Any],
    observed_index: ObservedIndex,
    skeleton: dict[str, Any],
    page_review: dict[str, Any],
    page_layout: dict[str, Any],
) -> dict[str, Any] | None:
    if not _page_review_is_resolved(page_review):
        return None
    return build_text_flow(
        observed,
        skeleton,
        page_review,
        page_layout,
        observed_index=observed_index,
    )


def _build_page_assets(observed: dict[str, Any], page_review: dict[str, Any]) -> dict[str, Any]:
    del page_review
    return deepcopy(observed.get("assets") or {})


def _validate_observed_index(index: Any) -> None:
    if not isinstance(index, ObservedIndex):
        raise TypeError("observed_index stage must produce ObservedIndex")


def _validate_skeleton(skeleton: Any) -> None:
    if not isinstance(skeleton, dict):
        raise TypeError("skeleton stage must produce object")


def _validate_page_review_artifact(page_review: Any) -> None:
    if not isinstance(page_review, dict) or not isinstance(page_review.get("pages"), list):
        raise TypeError("page_review stage must produce page records")
    if _page_review_is_resolved(page_review):
        validate_resolved_page_review(page_review)


def _validate_optional_text_flow(text_flow: Any) -> None:
    if text_flow is not None and not isinstance(text_flow, dict):
        raise TypeError("text_flow stage must produce object or None")


def _validate_page_assets(page_assets: Any) -> None:
    if page_assets is not None and not isinstance(page_assets, dict):
        raise TypeError("page_assets stage must produce object or None")


def _validate_artifact_relationships(artifacts: dict[str, Any]) -> None:
    observed = artifacts["observed"]
    index = artifacts["observed_index"]
    skeleton = artifacts["skeleton"]
    page_layout = artifacts["page_layout"]
    page_review = artifacts["page_review"]
    validate_book_skeleton_against_index(skeleton, index)
    doc_id = index.doc_id
    if page_layout.get("metadata", {}).get("doc_id") != doc_id:
        raise ValueError("PageLayoutAnalysis and ObservedDocument doc_id values differ")
    if page_review.get("metadata", {}).get("doc_id") != doc_id:
        raise ValueError("PageReview and ObservedDocument doc_id values differ")
    review_pages = [record.get("page") for record in page_review.get("pages") or []]
    if review_pages != list(index.page_numbers):
        raise ValueError("PageReview must contain every observed page exactly once in order")
    text_flow = artifacts["text_flow"]
    if text_flow is not None:
        validate_text_flow_against_sources(
            text_flow,
            observed,
            skeleton,
            page_review,
            page_layout,
            observed_index=index,
        )


def _page_review_is_resolved(page_review: dict[str, Any]) -> bool:
    candidates = set(page_review.get("candidate_pages") or [])
    records = {
        record.get("page"): record
        for record in page_review.get("pages") or []
        if isinstance(record, dict)
    }
    return all(
        records.get(page, {}).get("llm_review_status") == "sent_and_resolved"
        and records.get(page, {}).get("text_flow_action") != "needs_review"
        for page in candidates
    )


def validate_bundle_text_flow(bundle: CanonicalArtifactBundle) -> None:
    if bundle.text_flow is None:
        raise ValueError("canonical artifact bundle has unresolved PageReview")
    validate_book_skeleton_against_index(bundle.skeleton, bundle.observed_index)
    validate_text_flow_against_sources(
        bundle.text_flow,
        bundle.observed,
        bundle.skeleton,
        bundle.page_review,
        bundle.page_layout,
        observed_index=bundle.observed_index,
    )
