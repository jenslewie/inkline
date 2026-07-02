from __future__ import annotations

from collections import Counter
from typing import Any

from inkline.canonical.observed import validate_observed_document
from inkline.canonical.text_unit_layout import audit_text_unit_layout
from inkline.canonical.text_units import build_text_units

VISUAL_KINDS = {"image_region", "table_region"}
TEXT_KINDS = {"text_region", "footnote_region"}
CONTENT_KINDS = VISUAL_KINDS | TEXT_KINDS

VISUAL_DOMINANT_RATIO = 0.55
SPARSE_TEXT_AREA_RATIO = 0.12
CENTER_TOLERANCE_RATIO = 0.18


def classify_observed_page_roles(
    document: dict[str, Any],
    *,
    layout_audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    validate_observed_document(document)
    resolved_layout_audit = (
        layout_audit if layout_audit is not None else _build_layout_audit(document)
    )
    profile_pages = {
        int(record["page"])
        for record in resolved_layout_audit.get("page_profiles", [])
        if isinstance(record, dict) and isinstance(record.get("page"), int)
    }
    observations_by_page = _observations_by_page(document["observations"])
    pages = sorted(document["pages"], key=lambda page: int(page["page"]))
    page_numbers = [int(page["page"]) for page in pages]
    first_page = page_numbers[0] if page_numbers else 0
    last_page = page_numbers[-1] if page_numbers else 0
    first_numbered_page = _first_numbered_page(document["observations"])
    early_pages = _edge_page_set(page_numbers, from_start=True)
    late_pages = _edge_page_set(page_numbers, from_start=False)

    roles = []
    for page in pages:
        page_number = int(page["page"])
        metrics = _page_metrics(page, observations_by_page.get(page_number, []))
        roles.append(
            _page_role_record(
                page_number,
                metrics,
                has_body_profile=page_number in profile_pages,
                is_first_page=page_number == first_page,
                is_last_page=page_number == last_page,
                is_early_page=page_number in early_pages,
                is_late_page=page_number in late_pages,
                is_unnumbered_prelude=(
                    first_numbered_page is not None and page_number < first_numbered_page
                ),
            )
        )
    return roles


def page_roles_by_page(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(record["page"]): record for record in records}


def _build_layout_audit(document: dict[str, Any]) -> dict[str, Any]:
    text_units, _ignored_counts = build_text_units(document)
    return audit_text_unit_layout(text_units, document["pages"], document["observations"])


def _observations_by_page(
    observations: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for observation in observations:
        grouped.setdefault(int(observation["page"]), []).append(observation)
    return grouped


def _first_numbered_page(observations: list[dict[str, Any]]) -> int | None:
    numbered_pages = [
        int(observation["page"])
        for observation in observations
        if observation.get("role_hint") == "page_number"
    ]
    return min(numbered_pages) if numbered_pages else None


def _edge_page_set(page_numbers: list[int], *, from_start: bool) -> set[int]:
    if not page_numbers:
        return set()
    edge_count = min(24, max(4, round(len(page_numbers) * 0.05)))
    ordered = page_numbers if from_start else list(reversed(page_numbers))
    return set(ordered[:edge_count])


def _page_metrics(page: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    width = float(page["width"])
    height = float(page["height"])
    page_area = width * height
    content = [
        observation
        for observation in observations
        if observation.get("kind") in CONTENT_KINDS and _valid_bbox(observation.get("bbox"))
    ]
    text_regions = [observation for observation in content if observation.get("kind") in TEXT_KINDS]
    visual_regions = [
        observation for observation in content if observation.get("kind") in VISUAL_KINDS
    ]
    return {
        "kind_counts": Counter(str(observation.get("kind") or "") for observation in content),
        "role_hint_counts": Counter(
            str(observation.get("role_hint") or "") for observation in content
        ),
        "content_count": len(content),
        "text_count": len(text_regions),
        "visual_count": len(visual_regions),
        "visual_area_ratio": _area_ratio(visual_regions, page_area),
        "text_area_ratio": _area_ratio(text_regions, page_area),
        "centered_text_ratio": _centered_text_ratio(text_regions, width),
    }


def _page_role_record(
    page: int,
    metrics: dict[str, Any],
    *,
    has_body_profile: bool,
    is_first_page: bool,
    is_last_page: bool,
    is_early_page: bool,
    is_late_page: bool,
    is_unnumbered_prelude: bool,
) -> dict[str, Any]:
    if metrics["content_count"] == 0:
        return _record(page, "blank_page", "non_content", False, False, ["no_content_observations"])

    if is_unnumbered_prelude:
        return _unnumbered_prelude_record(
            page,
            metrics,
            has_body_profile=has_body_profile,
            is_first_page=is_first_page,
        )

    if has_body_profile:
        return _record(page, "body", "body", True, True, ["body_profile"])

    if metrics["visual_area_ratio"] >= VISUAL_DOMINANT_RATIO:
        return _visual_role_record(
            page,
            is_first_page=is_first_page,
            is_last_page=is_last_page,
            is_early_page=is_early_page,
            is_late_page=is_late_page,
        )

    if is_early_page and _is_sparse_centered_text(metrics):
        return _record(
            page,
            "title_like_page",
            "front_matter",
            True,
            False,
            ["early_page", "sparse_centered_text", "no_body_profile"],
        )

    if _has_text_flow_hint(metrics):
        return _record(
            page,
            "body_candidate",
            "body",
            True,
            True,
            ["text_flow_hint", "no_body_profile"],
        )

    if (is_early_page or is_late_page) and _is_text_without_body_profile(metrics):
        return _edge_text_role_record(page, is_early_page=is_early_page)

    return _record(page, "unknown", "unknown", True, False, ["no_body_profile"])


def _unnumbered_prelude_record(
    page: int,
    metrics: dict[str, Any],
    *,
    has_body_profile: bool,
    is_first_page: bool,
) -> dict[str, Any]:
    profile_signal = "body_profile" if has_body_profile else "no_body_profile"
    if metrics["visual_count"]:
        return _record(
            page,
            "cover_page" if is_first_page else "cover_spread",
            "front_matter",
            True,
            False,
            ["unnumbered_prelude", "visual_content", profile_signal],
        )
    if not has_body_profile and _is_sparse_centered_text(metrics):
        return _record(
            page,
            "title_like_page",
            "front_matter",
            True,
            False,
            ["unnumbered_prelude", "sparse_centered_text", profile_signal],
        )
    return _record(
        page,
        "front_matter_page",
        "front_matter",
        True,
        False,
        ["unnumbered_prelude", "text_content", profile_signal],
    )


def _visual_role_record(
    page: int,
    *,
    is_first_page: bool,
    is_last_page: bool,
    is_early_page: bool,
    is_late_page: bool,
) -> dict[str, Any]:
    signals = ["visual_dominant", "no_body_profile"]
    if is_early_page:
        signals.append("early_page")
    if is_late_page:
        signals.append("late_page")
    if is_first_page:
        return _record(page, "cover_page", "front_matter", True, False, signals)
    if is_early_page:
        return _record(page, "cover_spread", "front_matter", True, False, signals)
    if is_last_page or is_late_page:
        return _record(page, "back_cover_candidate", "back_matter", True, False, signals)
    return _record(page, "visual_page", "visual_insert", True, False, signals)


def _edge_text_role_record(page: int, *, is_early_page: bool) -> dict[str, Any]:
    scope = "front_matter" if is_early_page else "back_matter"
    return _record(
        page,
        "bibliographic_like_page",
        scope,
        True,
        False,
        ["text_without_body_profile", "edge_page"],
    )


def _record(
    page: int,
    page_role: str,
    flow_scope: str,
    include_in_epub: bool,
    include_in_rag: bool,
    signals: list[str],
) -> dict[str, Any]:
    return {
        "page": page,
        "page_role": page_role,
        "flow_scope": flow_scope,
        "include_in_epub": include_in_epub,
        "include_in_rag": include_in_rag,
        "signals": signals,
    }


def _is_sparse_centered_text(metrics: dict[str, Any]) -> bool:
    return (
        1 <= metrics["text_count"] <= 4
        and metrics["visual_count"] == 0
        and metrics["text_area_ratio"] <= SPARSE_TEXT_AREA_RATIO
        and metrics["centered_text_ratio"] >= 0.5
    )


def _is_text_without_body_profile(metrics: dict[str, Any]) -> bool:
    return (
        metrics["text_count"] > 0
        and metrics["visual_count"] == 0
        and metrics["text_area_ratio"] <= 0.45
    )


def _has_text_flow_hint(metrics: dict[str, Any]) -> bool:
    role_hint_counts = metrics["role_hint_counts"]
    return bool(
        role_hint_counts.get("body_text")
        or role_hint_counts.get("list_text")
        or role_hint_counts.get("footnote_text")
    )


def _area_ratio(observations: list[dict[str, Any]], page_area: float) -> float:
    if page_area <= 0:
        return 0.0
    area = sum(_bbox_area(observation["bbox"]) for observation in observations)
    return round(min(area / page_area, 1.0), 4)


def _centered_text_ratio(observations: list[dict[str, Any]], page_width: float) -> float:
    if not observations or page_width <= 0:
        return 0.0
    tolerance = page_width * CENTER_TOLERANCE_RATIO
    page_center = page_width / 2.0
    centered = 0
    for observation in observations:
        bbox = observation["bbox"]
        center = (float(bbox[0]) + float(bbox[2])) / 2.0
        if abs(center - page_center) <= tolerance:
            centered += 1
    return centered / len(observations)


def _bbox_area(bbox: list[float]) -> float:
    width = max(float(bbox[2]) - float(bbox[0]), 0.0)
    height = max(float(bbox[3]) - float(bbox[1]), 0.0)
    return width * height


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )
