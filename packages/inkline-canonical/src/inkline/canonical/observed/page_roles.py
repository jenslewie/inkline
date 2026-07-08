from __future__ import annotations

from collections import Counter
from itertools import pairwise
from typing import Any

from inkline.canonical.observed.schema import validate_observed_document
from inkline.canonical.observed.text_unit_layout import audit_text_unit_layout
from inkline.canonical.observed.text_units import build_text_units

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
    profile_pages = _profile_pages(resolved_layout_audit)
    observations_by_page = _observations_by_page(document["observations"])
    pages = sorted(document["pages"], key=lambda page: int(page["page"]))
    page_numbers = [int(page["page"]) for page in pages]
    first_page = page_numbers[0] if page_numbers else 0
    last_page = page_numbers[-1] if page_numbers else 0
    first_numbered_page = _first_numbered_page(document["observations"])
    early_pages = _edge_page_set(page_numbers, from_start=True)
    late_pages = _edge_page_set(page_numbers, from_start=False)

    roles = []
    metrics_by_page: dict[int, dict[str, Any]] = {}
    for page in pages:
        page_number = int(page["page"])
        metrics = _page_metrics(page, observations_by_page.get(page_number, []))
        metrics_by_page[page_number] = metrics
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
    return _apply_book_level_scope_overrides(roles, metrics_by_page)


def page_roles_by_page(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(record["page"]): record for record in records}


def _profile_pages(layout_audit: dict[str, Any]) -> set[int]:
    return {
        int(record["page"])
        for record in layout_audit.get("page_layout_profiles", [])
        if isinstance(record, dict)
        and isinstance(record.get("page"), int)
        and record.get("profile_scope") == "page"
    }


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
    body_zone_footnote_regions = [
        observation
        for observation in text_regions
        if observation.get("role_hint") == "footnote_text"
        and _bbox_top(observation["bbox"]) < height * 0.7
    ]
    return {
        "kind_counts": Counter(str(observation.get("kind") or "") for observation in content),
        "role_hint_counts": Counter(
            str(observation.get("role_hint") or "") for observation in content
        ),
        "content_count": len(content),
        "text_count": len(text_regions),
        "visual_count": len(visual_regions),
        "body_zone_footnote_count": len(body_zone_footnote_regions),
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
        return _record(
            page,
            "blank_page",
            _blank_page_flow_scope(
                is_early_page=is_early_page,
                is_late_page=is_late_page,
                is_unnumbered_prelude=is_unnumbered_prelude,
            ),
            ["no_content_observations"],
        )

    if is_unnumbered_prelude:
        return _unnumbered_prelude_record(
            page,
            metrics,
            has_body_profile=has_body_profile,
            is_first_page=is_first_page,
        )

    structure_record = _explicit_structure_record(page, metrics)
    if structure_record is not None:
        return structure_record

    visual_record = _visual_or_last_page_record(
        page,
        metrics,
        has_body_profile=has_body_profile,
        is_first_page=is_first_page,
        is_last_page=is_last_page,
        is_early_page=is_early_page,
        is_late_page=is_late_page,
    )
    if visual_record is not None:
        return visual_record

    text_record = _text_flow_role_record(
        page,
        metrics,
        has_body_profile=has_body_profile,
        is_early_page=is_early_page,
    )
    if text_record is not None:
        return text_record

    if (is_early_page or is_late_page) and _is_text_without_body_profile(metrics):
        return _edge_text_role_record(page, is_early_page=is_early_page)

    return _record(page, "unknown", "unknown", ["no_body_profile"])


def _explicit_structure_record(page: int, metrics: dict[str, Any]) -> dict[str, Any] | None:
    if _has_toc_hint(metrics):
        return _record(page, "toc_page", "front_matter", ["toc_hint"])

    if _has_note_section_hint(metrics):
        return _record(
            page,
            "note_section_candidate",
            "body",
            ["note_section_hint"],
        )

    return None


def _visual_or_last_page_record(
    page: int,
    metrics: dict[str, Any],
    *,
    has_body_profile: bool,
    is_first_page: bool,
    is_last_page: bool,
    is_early_page: bool,
    is_late_page: bool,
) -> dict[str, Any] | None:
    if _is_visual_page_candidate(metrics):
        return _visual_role_record(
            page,
            signal=_visual_page_signal(metrics),
            is_first_page=is_first_page,
            is_last_page=is_last_page,
            is_early_page=is_early_page,
            is_late_page=is_late_page,
        )

    if is_last_page and not is_first_page and metrics["visual_count"] > 0:
        signals = ["last_page_visual_content"]
        signals.append("body_profile" if has_body_profile else "no_body_profile")
        return _record(page, "back_cover_candidate", "back_matter", signals)

    return None


def _text_flow_role_record(
    page: int,
    metrics: dict[str, Any],
    *,
    has_body_profile: bool,
    is_early_page: bool,
) -> dict[str, Any] | None:
    if has_body_profile:
        signals = ["body_profile"]
        if _is_visual_verifier_candidate(metrics):
            signals.append("visual_verifier_candidate")
        return _record(page, "text_flow_page", "body", signals)

    if _is_sparse_centered_text(metrics):
        signals = ["sparse_centered_text", "no_body_profile"]
        if is_early_page:
            signals.insert(0, "early_page")
        return _record(
            page,
            "title_like_page",
            "front_matter" if is_early_page else "body",
            signals,
        )

    if _has_text_flow_hint(metrics):
        signals = ["text_flow_hint", "no_body_profile"]
        if _is_visual_verifier_candidate(metrics):
            signals.append("visual_verifier_candidate")
        return _record(
            page,
            "text_flow_candidate",
            "body",
            signals,
        )

    return None


def _blank_page_flow_scope(
    *,
    is_early_page: bool,
    is_late_page: bool,
    is_unnumbered_prelude: bool,
) -> str:
    if is_unnumbered_prelude or is_early_page:
        return "front_matter"
    if is_late_page:
        return "back_matter"
    return "body"


def _unnumbered_prelude_record(
    page: int,
    metrics: dict[str, Any],
    *,
    has_body_profile: bool,
    is_first_page: bool,
) -> dict[str, Any]:
    profile_signal = "body_profile" if has_body_profile else "no_body_profile"
    if _has_toc_hint(metrics):
        return _record(
            page,
            "toc_page",
            "front_matter",
            ["unnumbered_prelude", "toc_hint", profile_signal],
        )
    if _has_note_section_hint(metrics):
        return _record(
            page,
            "note_section_candidate",
            "body",
            ["unnumbered_prelude", "note_section_hint", profile_signal],
        )
    if metrics["visual_count"]:
        return _record(
            page,
            "cover_page" if is_first_page else "front_visual_page",
            "front_matter",
            ["unnumbered_prelude", "visual_content", profile_signal],
        )
    if not has_body_profile and _is_sparse_centered_text(metrics):
        return _record(
            page,
            "front_visual_page",
            "front_matter",
            ["unnumbered_prelude", "decorative_title_like", profile_signal],
        )
    return _record(
        page,
        "front_matter_page",
        "front_matter",
        ["unnumbered_prelude", "text_content", profile_signal],
    )


def _visual_role_record(
    page: int,
    *,
    signal: str,
    is_first_page: bool,
    is_last_page: bool,
    is_early_page: bool,
    is_late_page: bool,
) -> dict[str, Any]:
    signals = [signal, "no_body_profile"]
    if is_early_page:
        signals.append("early_page")
    if is_late_page:
        signals.append("late_page")
    if is_first_page:
        return _record(page, "cover_page", "front_matter", signals)
    if is_early_page:
        return _record(page, "front_visual_page", "front_matter", signals)
    if is_last_page:
        return _record(page, "back_cover_candidate", "back_matter", signals)
    return _record(page, "visual_page", "body", signals)


def _edge_text_role_record(page: int, *, is_early_page: bool) -> dict[str, Any]:
    scope = "front_matter" if is_early_page else "back_matter"
    return _record(
        page,
        "bibliographic_like_page",
        scope,
        ["text_without_body_profile", "edge_page"],
    )


def _apply_book_level_scope_overrides(
    records: list[dict[str, Any]], metrics_by_page: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    updated = [dict(record) for record in records]
    _apply_front_matter_prefix(updated, metrics_by_page)
    _apply_visual_page_runs(updated, metrics_by_page)
    _apply_note_cluster_gaps(updated, metrics_by_page)
    _apply_contiguous_known_flow_scopes(updated)
    return updated


def _apply_front_matter_prefix(
    records: list[dict[str, Any]], metrics_by_page: dict[int, dict[str, Any]]
) -> None:
    toc_indexes = [
        index
        for index, record in enumerate(records)
        if _has_toc_hint(metrics_by_page.get(int(record["page"]), {}))
    ]
    if not toc_indexes:
        return
    body_start_index = _first_body_start_after_toc(records, metrics_by_page, toc_indexes[0])
    if body_start_index is None:
        return
    for index in range(body_start_index):
        if records[index]["page_role"] == "blank_page":
            continue
        metrics = metrics_by_page.get(int(records[index]["page"]), {})
        if _has_toc_hint(metrics):
            _replace_record(
                records,
                index,
                "toc_page",
                "front_matter",
                ["book_front_prefix", "toc_hint"],
            )
        elif records[index]["flow_scope"] == "body":
            _replace_record(
                records,
                index,
                "front_matter_page",
                "front_matter",
                ["book_front_prefix", "before_body_anchor"],
            )


def _first_body_start_after_toc(
    records: list[dict[str, Any]],
    metrics_by_page: dict[int, dict[str, Any]],
    first_toc_index: int,
) -> int | None:
    for index in range(first_toc_index + 1, len(records)):
        if _is_body_start_candidate(metrics_by_page.get(int(records[index]["page"]), {})):
            return index
    return None


def _apply_visual_page_runs(
    records: list[dict[str, Any]], metrics_by_page: dict[int, dict[str, Any]]
) -> None:
    for start, end in _visual_page_runs(records, metrics_by_page):
        for index in range(start, end):
            if records[index]["flow_scope"] != "body":
                continue
            metrics = metrics_by_page.get(int(records[index]["page"]), {})
            if (metrics.get("visual_count") or 0) <= 0:
                continue
            if records[index]["page_role"] in {"note_section_candidate", "blank_page"}:
                continue
            signals = list(records[index].get("signals") or [])
            if "visual_run" not in signals:
                signals.insert(0, "visual_run")
            _replace_record(records, index, "visual_page", "body", signals)


def _visual_page_runs(
    records: list[dict[str, Any]], metrics_by_page: dict[int, dict[str, Any]]
) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, record in enumerate(records):
        metrics = metrics_by_page.get(int(record["page"]), {})
        if _is_visual_run_page(metrics):
            if start is None:
                start = index
            continue
        if start is not None and index - start >= 4:
            runs.append((start, index))
        start = None
    if start is not None and len(records) - start >= 4:
        runs.append((start, len(records)))
    return runs


def _apply_note_cluster_gaps(
    records: list[dict[str, Any]], metrics_by_page: dict[int, dict[str, Any]]
) -> None:
    note_indexes = [
        index
        for index, record in enumerate(records)
        if record.get("page_role") == "note_section_candidate"
    ]
    for previous, current in pairwise(note_indexes):
        gap = current - previous - 1
        if gap <= 0 or gap > 3:
            continue
        for index in _fillable_note_cluster_gap_indexes(
            records, metrics_by_page, previous + 1, current
        ):
            signals = list(records[index].get("signals") or [])
            if "note_cluster_gap" not in signals:
                signals.insert(0, "note_cluster_gap")
            _replace_record(records, index, "note_section_candidate", "body", signals)


def _fillable_note_cluster_gap_indexes(
    records: list[dict[str, Any]],
    metrics_by_page: dict[int, dict[str, Any]],
    start: int,
    end: int,
) -> list[int]:
    indexes = []
    for index in range(start, end):
        if not _can_fill_note_cluster_gap_record(records[index], metrics_by_page):
            break
        indexes.append(index)
    return indexes


def _can_fill_note_cluster_gap_record(
    record: dict[str, Any], metrics_by_page: dict[int, dict[str, Any]]
) -> bool:
    blocked_roles = {
        "cover_page",
        "front_visual_page",
        "visual_page",
        "back_cover_candidate",
        "toc_page",
    }
    metrics = metrics_by_page.get(int(record["page"]), {})
    kind_counts = metrics.get("kind_counts") or {}
    return (
        (record.get("flow_scope") == "body" or record.get("page_role") == "blank_page")
        and record.get("page_role") not in blocked_roles
        and (metrics.get("visual_count") or 0) == 0
        and (kind_counts.get("table_region") or 0) == 0
    )


def _apply_contiguous_known_flow_scopes(records: list[dict[str, Any]]) -> None:
    body_indexes = [
        index for index, record in enumerate(records) if record.get("flow_scope") == "body"
    ]
    if not body_indexes:
        return
    first_body = body_indexes[0]
    last_body = body_indexes[-1]
    for index in range(first_body):
        if records[index].get("flow_scope") == "back_matter":
            _set_record_scope(records, index, "front_matter")
    for index in range(first_body, last_body + 1):
        if records[index].get("flow_scope") in {"front_matter", "back_matter"}:
            _set_record_scope(
                records,
                index,
                "body",
                page_role=_body_scope_page_role(records[index]),
            )
    for index in range(last_body + 1, len(records)):
        if records[index].get("flow_scope") == "front_matter":
            _set_record_scope(records, index, "back_matter")


def _set_record_scope(
    records: list[dict[str, Any]],
    index: int,
    flow_scope: str,
    *,
    page_role: str | None = None,
) -> None:
    current = records[index]
    signals = list(current.get("signals") or [])
    if "book_scope_continuity" not in signals:
        signals.append("book_scope_continuity")
    records[index] = _record(
        int(current["page"]),
        page_role or str(current["page_role"]),
        flow_scope,
        signals,
    )


def _body_scope_page_role(record: dict[str, Any]) -> str:
    if record.get("page_role") in {
        "back_cover_candidate",
        "cover_page",
        "front_visual_page",
    }:
        return "visual_page"
    return str(record["page_role"])


def _replace_record(
    records: list[dict[str, Any]],
    index: int,
    page_role: str,
    flow_scope: str,
    signals: list[str],
) -> None:
    current = records[index]
    records[index] = _record(
        int(current["page"]),
        page_role,
        flow_scope,
        signals,
    )


def _record(
    page: int,
    page_role: str,
    flow_scope: str,
    signals: list[str],
) -> dict[str, Any]:
    return {
        "page": page,
        "page_role": page_role,
        "flow_scope": flow_scope,
        "signals": signals,
    }


def _is_sparse_centered_text(metrics: dict[str, Any]) -> bool:
    return (
        1 <= metrics["text_count"] <= 4
        and metrics["visual_count"] == 0
        and _has_title_like_hint(metrics)
        and metrics["text_area_ratio"] <= SPARSE_TEXT_AREA_RATIO
        and metrics["centered_text_ratio"] >= 0.5
    )


def _is_text_without_body_profile(metrics: dict[str, Any]) -> bool:
    return (
        metrics["text_count"] > 0
        and metrics["visual_count"] == 0
        and metrics["text_area_ratio"] <= 0.45
    )


def _is_visual_page_candidate(metrics: dict[str, Any]) -> bool:
    if (metrics.get("visual_count") or 0) <= 0:
        return False
    if metrics["visual_area_ratio"] >= VISUAL_DOMINANT_RATIO:
        return True
    if metrics["text_count"] == 0 and metrics["visual_area_ratio"] >= 0.1:
        return True
    if metrics["visual_count"] >= 2 and metrics["visual_area_ratio"] >= 0.45:
        return True
    return metrics["text_area_ratio"] <= 0.02 and metrics["visual_area_ratio"] >= 0.15


def _is_visual_verifier_candidate(metrics: dict[str, Any]) -> bool:
    return (
        (metrics.get("visual_count") or 0) > 0
        and 0.25 <= metrics["visual_area_ratio"] < VISUAL_DOMINANT_RATIO
        and 1 <= metrics["text_count"] <= 4
        and metrics["text_area_ratio"] <= 0.18
    )


def _is_visual_run_page(metrics: dict[str, Any]) -> bool:
    return (
        (metrics.get("visual_count") or 0) > 0
        and metrics["text_count"] <= 8
        and metrics["visual_area_ratio"] >= 0.15
    )


def _visual_page_signal(metrics: dict[str, Any]) -> str:
    if metrics["visual_area_ratio"] >= VISUAL_DOMINANT_RATIO:
        return "visual_dominant"
    return "visual_sparse_text"


def _has_toc_hint(metrics: dict[str, Any]) -> bool:
    role_hint_counts = metrics.get("role_hint_counts") or {}
    return bool(role_hint_counts.get("toc_text"))


def _has_title_like_hint(metrics: dict[str, Any]) -> bool:
    role_hint_counts = metrics.get("role_hint_counts") or {}
    return bool(role_hint_counts.get("title_text"))


def _has_note_section_hint(metrics: dict[str, Any]) -> bool:
    content_count = metrics.get("content_count") or 0
    if content_count <= 0:
        return False
    return (metrics.get("body_zone_footnote_count") or 0) / content_count >= 0.5


def _is_body_start_candidate(metrics: dict[str, Any]) -> bool:
    role_hint_counts = metrics.get("role_hint_counts") or {}
    return (role_hint_counts.get("title_text") or 0) >= 2 and (
        role_hint_counts.get("body_text") or 0
    ) > 0


def _has_text_flow_hint(metrics: dict[str, Any]) -> bool:
    role_hint_counts = metrics["role_hint_counts"]
    return bool(
        role_hint_counts.get("body_text")
        or role_hint_counts.get("list_text")
        or role_hint_counts.get("reference_text")
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


def _bbox_top(bbox: list[float]) -> float:
    return float(bbox[1])


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )
