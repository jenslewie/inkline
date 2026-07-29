from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from inkline.canonical.observed.layout_geometry import (
    display_gap_threshold,
    display_signals,
    is_display_candidate,
    page_layout_profile_map,
    valid_bbox,
)
from inkline.canonical.page_layout.validation import validate_page_layout_analysis

BODY_CANDIDATE_TYPE = "body_text"


@dataclass(frozen=True)
class _SamePageRun:
    candidates: list[dict[str, Any]]
    previous: dict[str, Any] | None
    following: dict[str, Any] | None
    lane: str | None
    short_line_alignment: str | None
    status: str


def classify_text_candidates_by_layout(
    candidates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    *,
    page_layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return copied candidates with one layout_decision per candidate."""

    validate_page_layout_analysis(page_layout)
    classified = deepcopy(candidates)
    profiles = page_layout_profile_map(page_layout)
    book_profile = dict(page_layout["book_layout_profile"])
    for run in _same_page_runs(classified, profiles, book_profile):
        _classify_same_page_run(run, profiles, book_profile)
    _mark_non_body_decisions(classified)
    _mark_uncertain_body_decisions(
        classified,
        profiles,
        {int(page["page"]) for page in pages if isinstance(page.get("page"), int)},
    )
    layout_pages = list(page_layout["pages"])
    _apply_terminal_attributions(classified, layout_pages, profiles, book_profile)
    _apply_cross_page_display_runs(classified, layout_pages, profiles, book_profile)
    return classified


def _apply_terminal_attributions(
    candidates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> None:
    page_records = {int(page["page"]): page for page in pages}
    for run in _ordered_body_runs(candidates, profiles, book_profile):
        if not _is_terminal_right_aligned_run(run, page_records, book_profile):
            continue
        page = int(run.candidates[0]["page"])
        structural_boundary = _has_structural_following_page(page_records.get(page + 1))
        for candidate in run.candidates:
            decision = candidate["layout_decision"]
            decision["signals"] = [
                signal for signal in decision["signals"] if signal != "display_gap_after"
            ]
            if structural_boundary:
                decision["classified_type"] = "display_block"
                decision["layout_form"] = "attribution"
                decision["alignment"] = "right"
                decision["signals"].append("terminal_right_aligned_attribution")
            else:
                decision["classified_type"] = "paragraph"
                decision["layout_form"] = None
                decision["alignment"] = None
                decision["signals"].append(
                    "terminal_right_aligned_without_structural_boundary"
                )


def _is_terminal_right_aligned_run(
    run: _SamePageRun,
    page_records: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> bool:
    if run.status != "resolved" or run.lane != "right_set_off":
        return False
    page = int(run.candidates[0]["page"])
    if run.following is not None and int(run.following["page"]) == page:
        return False
    page_record = page_records.get(page)
    bbox = run.candidates[-1].get("bbox")
    if page_record is None or not valid_bbox(bbox):
        return False
    page_height = _page_height(page_record)
    if page_height is None or float(bbox[3]) < page_height * 0.78:
        return False
    return _terminal_preceding_gap(run, book_profile)


def _terminal_preceding_gap(
    run: _SamePageRun, book_profile: dict[str, Any]
) -> bool:
    previous = run.previous
    first_bbox = run.candidates[0].get("bbox")
    if (
        previous is None
        or int(previous["page"]) != int(run.candidates[0]["page"])
        or not valid_bbox(previous.get("bbox"))
        or not valid_bbox(first_bbox)
    ):
        return False
    normal_gap = _positive_float(book_profile.get("normal_gap_y"))
    threshold = normal_gap or display_gap_threshold(book_profile)
    return float(first_bbox[1]) - float(previous["bbox"][3]) >= threshold


def _has_structural_following_page(page_record: dict[str, Any] | None) -> bool:
    if page_record is None:
        return False
    role_signals = page_record.get("role_signals")
    role_counts = (
        role_signals.get("role_hint_counts") if isinstance(role_signals, dict) else None
    )
    return isinstance(role_counts, dict) and int(role_counts.get("title_text") or 0) > 0


def _apply_cross_page_display_runs(
    candidates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> None:
    runs = _ordered_body_runs(candidates, profiles, book_profile)
    accepted: list[tuple[_SamePageRun, _SamePageRun, dict[str, Any]]] = []
    for left, right in pairwise(runs):
        evidence = _joint_display_evidence(
            left,
            right,
            candidates,
            pages,
            book_profile,
        )
        if evidence is None:
            continue
        _promote_run_decision(left)
        _promote_run_decision(right)
        accepted.append((left, right, evidence))
    _write_transition_components(accepted)


def _ordered_body_runs(
    candidates: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> list[_SamePageRun]:
    return [
        run
        for run in _same_page_runs(candidates, profiles, book_profile)
        if run.status == "resolved"
        and run.candidates[0].get("candidate_type") == BODY_CANDIDATE_TYPE
    ]


def _joint_display_evidence(
    left: _SamePageRun,
    right: _SamePageRun,
    candidates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    book_profile: dict[str, Any],
) -> dict[str, Any] | None:
    left_page = int(left.candidates[0]["page"])
    right_page = int(right.candidates[0]["page"])
    if right_page != left_page + 1:
        return None
    if left.lane not in {"left_set_off", "right_set_off"} or left.lane != right.lane:
        return None
    if _layout_form(left) != _layout_form(right):
        return None
    if _has_protected_member(left) or _has_protected_member(right):
        return None
    page_records = {int(page["page"]): page for page in pages}
    if not _at_page_edge(left, page_records.get(left_page), bottom=True):
        return None
    if not _at_page_edge(right, page_records.get(right_page), bottom=False):
        return None
    threshold = display_gap_threshold(book_profile)
    if not _outer_separated(left.previous, left.candidates[0], threshold, before=True):
        return None
    if not _outer_separated(
        right.following, right.candidates[-1], threshold, before=False
    ):
        return None
    if not _has_only_recorded_page_foot_interruptions(
        left,
        right,
        candidates,
        page_records,
    ):
        return None
    return {
        "left_page": left_page,
        "right_page": right_page,
        "left_observation_ids": [
            str(candidate["observation_id"]) for candidate in left.candidates
        ],
        "right_observation_ids": [
            str(candidate["observation_id"]) for candidate in right.candidates
        ],
        "signals": [
            "left_page_bottom",
            "right_page_top",
            "compatible_set_off_lane",
            "combined_outer_display_gaps",
        ],
    }


def _has_protected_member(run: _SamePageRun) -> bool:
    return any(candidate.get("protected_anchor_group") for candidate in run.candidates)


def _at_page_edge(
    run: _SamePageRun,
    page_record: dict[str, Any] | None,
    *,
    bottom: bool,
) -> bool:
    if page_record is None:
        return False
    page_height = _page_height(page_record)
    edge_bbox = run.candidates[-1 if bottom else 0].get("bbox")
    if page_height is None or not valid_bbox(edge_bbox):
        return False
    if bottom:
        return float(edge_bbox[3]) >= page_height * 0.78
    return float(edge_bbox[1]) <= page_height * 0.22


def _page_height(page_record: dict[str, Any]) -> float | None:
    page_size = page_record.get("page_size")
    if not isinstance(page_size, dict):
        return None
    return _positive_float(page_size.get("height"))


def _has_only_recorded_page_foot_interruptions(
    left: _SamePageRun,
    right: _SamePageRun,
    candidates: list[dict[str, Any]],
    page_records: dict[int, dict[str, Any]],
) -> bool:
    indexes = {
        str(candidate["observation_id"]): index
        for index, candidate in enumerate(candidates)
    }
    left_end = indexes[str(left.candidates[-1]["observation_id"])]
    right_start = indexes[str(right.candidates[0]["observation_id"])]
    interruptions = candidates[left_end + 1 : right_start]
    if not interruptions:
        return True
    left_page = int(left.candidates[0]["page"])
    page_record = page_records.get(left_page)
    page_height = _page_height(page_record) if page_record is not None else None
    return page_height is not None and all(
        candidate.get("candidate_type") == "footnote"
        and int(candidate["page"]) == left_page
        and valid_bbox(candidate.get("bbox"))
        and float(candidate["bbox"][1]) >= page_height * 0.75
        for candidate in interruptions
    )


def _promote_run_decision(run: _SamePageRun) -> None:
    for candidate in run.candidates:
        decision = candidate["layout_decision"]
        decision["classified_type"] = "display_block"
        decision["layout_form"] = _layout_form(run)
        decision["alignment"] = _layout_alignment(run)


def _write_transition_components(
    accepted: list[tuple[_SamePageRun, _SamePageRun, dict[str, Any]]],
) -> None:
    components: list[tuple[list[_SamePageRun], list[dict[str, Any]]]] = []
    for left, right, evidence in accepted:
        if components and components[-1][0][-1] is left:
            components[-1][0].append(right)
            components[-1][1].append(evidence)
        else:
            components.append(([left, right], [evidence]))
    for runs, transitions in components:
        for run in runs:
            for candidate in run.candidates:
                candidate["layout_decision"]["cross_page_transitions"] = deepcopy(
                    transitions
                )


def _same_page_runs(
    candidates: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> list[_SamePageRun]:
    grouped: list[tuple[tuple[Any, ...], list[dict[str, Any]], int]] = []
    for index, candidate in enumerate(candidates):
        key = _run_key(candidate, profiles, book_profile)
        if grouped and grouped[-1][0] == key:
            grouped[-1][1].append(candidate)
        else:
            grouped.append((key, [candidate], index))

    runs: list[_SamePageRun] = []
    for key, members, start in grouped:
        end = start + len(members)
        runs.append(
            _SamePageRun(
                candidates=members,
                previous=candidates[start - 1] if start else None,
                following=candidates[end] if end < len(candidates) else None,
                lane=key[5],
                short_line_alignment=key[6],
                status=key[2],
            )
        )
    return runs


def _run_key(
    candidate: dict[str, Any],
    profiles: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> tuple[Any, ...]:
    page = int(candidate["page"])
    candidate_type = str(candidate.get("candidate_type") or "")
    profile = profiles.get(page)
    status = _candidate_status(candidate, profile)
    lane = _horizontal_lane(candidate, profile, book_profile) if status == "resolved" else None
    alignment = (
        _short_line_alignment(candidate, lane, profile, book_profile)
        if status == "resolved"
        else None
    )
    attrs = candidate.get("attrs")
    structural_boundary = attrs.get("layout_role") if isinstance(attrs, dict) else None
    uncertainty_identity = str(candidate["observation_id"]) if status == "uncertain" else None
    return (
        page,
        candidate_type,
        status,
        tuple(candidate.get("protected_anchor_group") or ()),
        structural_boundary,
        lane,
        alignment,
        uncertainty_identity,
    )


def _candidate_status(
    candidate: dict[str, Any], profile: dict[str, Any] | None
) -> str:
    if candidate.get("candidate_type") != BODY_CANDIDATE_TYPE:
        return "resolved"
    if not valid_bbox(candidate.get("bbox")) or profile is None:
        return "uncertain"
    return "resolved"


def _horizontal_lane(
    candidate: dict[str, Any],
    profile: dict[str, Any] | None,
    book_profile: dict[str, Any],
) -> str | None:
    bbox = candidate.get("bbox")
    if profile is None or not valid_bbox(bbox):
        return None
    signals = display_signals(bbox, profile, book_profile, {})
    if "right_aligned_attribution" in signals:
        return "right_set_off"
    body_width = float(profile["body_width"])
    left_inset = float(bbox[0]) - float(profile["body_left"])
    indent_unit = _indent_unit(book_profile, body_width)
    if not _is_short_line(candidate, book_profile) and _has_set_off_signal(signals):
        return "left_set_off"
    if left_inset >= indent_unit * 1.2:
        return "left_set_off"
    if left_inset >= max(12.0, indent_unit * 0.45):
        return "body_indent"
    return "body"


def _short_line_alignment(
    candidate: dict[str, Any],
    lane: str | None,
    profile: dict[str, Any] | None,
    book_profile: dict[str, Any],
) -> str | None:
    bbox = candidate.get("bbox")
    if profile is None or not valid_bbox(bbox) or not _is_short_line(candidate, book_profile):
        return None
    if lane == "right_set_off":
        return "right"
    body_center = (float(profile["body_left"]) + float(profile["body_right"])) / 2.0
    bbox_center = (float(bbox[0]) + float(bbox[2])) / 2.0
    if abs(bbox_center - body_center) <= max(24.0, float(profile["body_width"]) * 0.04):
        return "center"
    return "left"


def _is_short_line(candidate: dict[str, Any], book_profile: dict[str, Any]) -> bool:
    attrs = candidate.get("attrs")
    metrics_by_observation = (
        attrs.get("text_line_metrics_by_observation") if isinstance(attrs, dict) else None
    )
    if isinstance(metrics_by_observation, dict):
        metrics = metrics_by_observation.get(str(candidate.get("observation_id")))
        if isinstance(metrics, dict) and isinstance(metrics.get("line_count"), int):
            return int(metrics["line_count"]) == 1
    bbox = candidate.get("bbox")
    if not valid_bbox(bbox):
        return False
    line_height = _positive_float(book_profile.get("line_height"))
    threshold = max(48.0, (line_height or 24.0) * 1.25)
    return float(bbox[3]) - float(bbox[1]) <= threshold


def _classify_same_page_run(
    run: _SamePageRun,
    profiles: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> None:
    first = run.candidates[0]
    if first.get("candidate_type") != BODY_CANDIDATE_TYPE or run.status == "uncertain":
        return
    profile = profiles[int(first["page"])]
    threshold = display_gap_threshold(book_profile)
    separated_before = _outer_separated(run.previous, first, threshold, before=True)
    separated_after = _outer_separated(run.following, run.candidates[-1], threshold, before=False)
    member_signals = [
        display_signals(
            candidate["bbox"],
            profile,
            book_profile,
            {
                "display_gap_before": separated_before and index == 0,
                "display_gap_after": separated_after and index == len(run.candidates) - 1,
            },
        )
        for index, candidate in enumerate(run.candidates)
    ]
    display = _run_is_display(run, member_signals, separated_before, separated_after)
    run_ids = [str(candidate["observation_id"]) for candidate in run.candidates]
    for candidate, signals in zip(run.candidates, member_signals, strict=True):
        if display and not is_display_candidate(signals):
            signals.append("set_off_run_outer_display_gap")
        candidate["layout_decision"] = _layout_decision(
            classified_type="display_block" if display else "paragraph",
            status="resolved",
            layout_form=_layout_form(run) if display else None,
            alignment=_layout_alignment(run) if display else None,
            signals=signals,
            profile_source=str(profile.get("profile_source") or "local"),
            run_ids=run_ids,
        )


def _outer_separated(
    outside: dict[str, Any] | None,
    edge: dict[str, Any],
    threshold: float,
    *,
    before: bool,
) -> bool:
    if outside is None or int(outside["page"]) != int(edge["page"]):
        return True
    outside_bbox = outside.get("bbox")
    edge_bbox = edge.get("bbox")
    if not valid_bbox(outside_bbox) or not valid_bbox(edge_bbox):
        return False
    gap = (
        float(edge_bbox[1]) - float(outside_bbox[3])
        if before
        else float(outside_bbox[1]) - float(edge_bbox[3])
    )
    return gap >= threshold


def _run_is_display(
    run: _SamePageRun,
    member_signals: list[list[str]],
    separated_before: bool,
    separated_after: bool,
) -> bool:
    if run.lane not in {"left_set_off", "right_set_off"}:
        return False
    if any(is_display_candidate(signals) for signals in member_signals):
        return True
    return separated_before and separated_after and any(
        _has_set_off_signal(signals) for signals in member_signals
    )


def _layout_form(run: _SamePageRun) -> str:
    if run.lane == "right_set_off":
        return "attribution"
    if run.short_line_alignment is not None:
        return "short_line_group"
    return "set_off_prose"


def _layout_alignment(run: _SamePageRun) -> str:
    return run.short_line_alignment or "left"


def _mark_non_body_decisions(candidates: list[dict[str, Any]]) -> None:
    for candidate in candidates:
        if candidate.get("candidate_type") == BODY_CANDIDATE_TYPE:
            continue
        candidate["layout_decision"] = _layout_decision(
            classified_type=str(candidate["candidate_type"]),
            status="resolved",
            layout_form=None,
            alignment=None,
            signals=["explicit_structural_role"],
            profile_source=None,
            run_ids=[str(candidate["observation_id"])],
        )


def _mark_uncertain_body_decisions(
    candidates: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    page_numbers: set[int],
) -> None:
    for candidate in candidates:
        if candidate.get("candidate_type") != BODY_CANDIDATE_TYPE:
            continue
        if "layout_decision" in candidate:
            continue
        signals: list[str] = []
        if int(candidate["page"]) not in page_numbers:
            signals.append("missing_page")
        if not valid_bbox(candidate.get("bbox")):
            signals.append("missing_bbox")
        if int(candidate["page"]) not in profiles:
            signals.append("missing_page_profile")
        candidate["layout_decision"] = _layout_decision(
            classified_type="paragraph",
            status="uncertain",
            layout_form=None,
            alignment=None,
            signals=signals,
            profile_source=None,
            run_ids=[str(candidate["observation_id"])],
        )


def _layout_decision(
    *,
    classified_type: str,
    status: str,
    layout_form: str | None,
    alignment: str | None,
    signals: list[str],
    profile_source: str | None,
    run_ids: list[str],
) -> dict[str, Any]:
    return {
        "classified_type": classified_type,
        "status": status,
        "layout_form": layout_form,
        "alignment": alignment,
        "signals": signals,
        "profile_source": profile_source,
        "same_page_run_observation_ids": run_ids,
        "cross_page_transitions": [],
    }


def _has_set_off_signal(signals: list[str]) -> bool:
    return bool(
        set(signals)
        & {
            "narrower_than_body_lane",
            "inset_from_body_lane",
            "left_inset_set_off_text",
            "slightly_inset_tall_block",
            "book_indent_set_off_text",
            "right_aligned_attribution",
        }
    )


def _indent_unit(book_profile: dict[str, Any], body_width: float) -> float:
    return _positive_float(book_profile.get("indent_unit")) or max(24.0, body_width * 0.04)


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
