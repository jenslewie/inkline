from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, cast

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
    _promote_trailing_page_reference_blocks(classified, list(page_layout["pages"]))
    for run in _same_page_runs(classified, profiles, book_profile):
        _classify_same_page_run(run, profiles, book_profile)
    _mark_non_body_decisions(classified)
    _mark_uncertain_body_decisions(
        classified,
        profiles,
        {int(page["page"]) for page in pages if isinstance(page.get("page"), int)},
    )
    _apply_title_cluster_groups(classified, list(page_layout["pages"]))
    layout_pages = list(page_layout["pages"])
    _apply_terminal_attributions(classified, layout_pages, profiles, book_profile)
    _apply_terminal_mixed_alignment_short_line_clusters(
        classified,
        profiles,
        book_profile,
    )
    _apply_cross_page_display_runs(classified, layout_pages, profiles, book_profile)
    return classified


def _promote_trailing_page_reference_blocks(
    candidates: list[dict[str, Any]],
    page_records: list[dict[str, Any]],
) -> None:
    """Promote parser-supported trailing reference blocks to page footnotes."""

    page_heights = {
        int(record["page"]): _page_height(record)
        for record in page_records
        if isinstance(record, dict) and isinstance(record.get("page"), int)
    }
    grouped: dict[int, list[dict[str, Any]]] = {}
    for candidate in candidates:
        grouped.setdefault(int(candidate["page"]), []).append(candidate)
    for page_candidates in grouped.values():
        reference_start = next(
            (
                index
                for index, candidate in enumerate(page_candidates)
                if _reference_list_candidate(candidate)
            ),
            None,
        )
        if reference_start is None:
            continue
        body = page_candidates[:reference_start]
        references = page_candidates[reference_start:]
        page = int(references[0]["page"])
        height = page_heights.get(page)
        if (
            not body
            or not all(_reference_list_candidate(candidate) for candidate in references)
            or not all(valid_bbox(candidate.get("bbox")) for candidate in references)
            or not any(
                candidate.get("candidate_type") == BODY_CANDIDATE_TYPE
                and valid_bbox(candidate.get("bbox"))
                for candidate in body
            )
            or height is None
            or float(references[0]["bbox"][1]) < height * 0.5
            or not _parser_markers_cover_reference_block(references)
        ):
            continue
        body_bottom = max(
            float(candidate["bbox"][3])
            for candidate in body
            if candidate.get("candidate_type") == BODY_CANDIDATE_TYPE
            and valid_bbox(candidate.get("bbox"))
        )
        if body_bottom > float(references[0]["bbox"][1]):
            continue
        run_ids = [str(candidate["observation_id"]) for candidate in references]
        for candidate in references:
            candidate["candidate_type"] = "footnote"
            candidate["classification_signals"] = [
                "parser_marked_trailing_page_reference_block"
            ]
            candidate["classification_run_ids"] = run_ids


def _reference_list_candidate(candidate: dict[str, Any]) -> bool:
    return (
        candidate.get("candidate_type") == "list_item"
        and candidate.get("role_hint") == "reference_text"
    )


def _parser_markers_cover_reference_block(
    candidates: list[dict[str, Any]],
) -> bool:
    marker_sequences = {
        tuple(str(marker) for marker in markers)
        for candidate in candidates
        if (
            isinstance((raw := candidate.get("parser_payload")), dict)
            and isinstance((payload := raw.get("raw")), dict)
            and isinstance(
                (markers := payload.get("_middle_page_inline_markers")),
                list,
            )
            and markers
        )
    }
    return len(marker_sequences) == 1 and len(next(iter(marker_sequences), ())) == len(
        candidates
    )


def _apply_title_cluster_groups(
    candidates: list[dict[str, Any]],
    page_records: list[dict[str, Any]],
) -> None:
    title_cluster_pages = {
        int(record["page"])
        for record in page_records
        if isinstance(record, dict)
        and isinstance(record.get("coverage"), dict)
        and record["coverage"].get("profile_status") == "title_cluster"
    }
    for page in title_cluster_pages:
        members = [
            candidate
            for candidate in candidates
            if int(candidate["page"]) == page
            and candidate.get("candidate_type") in {BODY_CANDIDATE_TYPE, "heading"}
        ]
        page_candidates = [candidate for candidate in candidates if int(candidate["page"]) == page]
        if not 2 <= len(members) <= 4 or len(members) != len(page_candidates):
            continue
        run_ids = [str(candidate["observation_id"]) for candidate in members]
        for candidate in members:
            decision = candidate["layout_decision"]
            decision["classified_type"] = "heading"
            decision["status"] = "resolved"
            decision["layout_form"] = None
            decision["alignment"] = None
            decision["signals"] = ["title_cluster_page"]
            decision["same_page_run_observation_ids"] = run_ids


def _apply_terminal_mixed_alignment_short_line_clusters(
    candidates: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> None:
    runs = _ordered_body_runs(candidates, profiles, book_profile)
    for left, right in pairwise(runs):
        left_page = int(left.candidates[0]["page"])
        right_page = int(right.candidates[0]["page"])
        right_following = right.following
        if (
            left_page != right_page
            or left.following is not right.candidates[0]
            or left.lane not in {"body_indent", "left_set_off"}
            or right.lane != "right_set_off"
            or left.short_line_alignment != "left"
            or right.short_line_alignment != "right"
            or not _terminal_preceding_gap(left, book_profile)
            or not _terminal_preceding_gap(right, book_profile)
            or not _strong_short_line_cluster(
                left,
                required_signals={"narrower_than_body_lane", "left_inset_set_off_text"},
            )
            or not _strong_short_line_cluster(
                right,
                required_signals={"narrower_than_body_lane", "right_aligned_attribution"},
            )
            or not _is_terminal_right_aligned_run(right)
            or _has_protected_member(left)
            or _has_protected_member(right)
            or (right_following is not None and int(right_following["page"]) == right_page)
        ):
            continue
        for candidate in right.candidates:
            decision = candidate["layout_decision"]
            decision["signals"] = [
                signal
                for signal in decision["signals"]
                if not signal.startswith("terminal_right_aligned_without_")
            ]
        for run in (left, right):
            _promote_run_decision(run)
            for candidate in run.candidates:
                candidate["layout_decision"]["signals"].append(
                    "terminal_mixed_alignment_short_line_cluster"
                )


def _strong_short_line_cluster(
    run: _SamePageRun,
    *,
    required_signals: set[str],
) -> bool:
    if len(run.candidates) < 2 or run.short_line_alignment is None:
        return False
    return all(
        required_signals.issubset(candidate["layout_decision"]["signals"])
        for candidate in run.candidates
    )


def _apply_terminal_attributions(
    candidates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> None:
    page_records = {int(page["page"]): page for page in pages}
    for run in _ordered_body_runs(candidates, profiles, book_profile):
        if not _is_terminal_right_aligned_run(run):
            continue
        page = int(run.candidates[0]["page"])
        page_bottom = _at_page_edge(run, page_records.get(page), bottom=True)
        preceding_gap = _terminal_preceding_gap(run, book_profile)
        structural_boundary = _has_structural_following_boundary(
            candidates,
            page + 1,
            page_records.get(page + 1),
        )
        for candidate in run.candidates:
            decision = candidate["layout_decision"]
            decision["signals"] = [
                signal for signal in decision["signals"] if signal != "display_gap_after"
            ]
            if page_bottom and preceding_gap and structural_boundary:
                decision["classified_type"] = "display_block"
                decision["layout_form"] = "attribution"
                decision["alignment"] = "right"
                decision["signals"].append("terminal_right_aligned_attribution")
            else:
                decision["classified_type"] = "paragraph"
                decision["layout_form"] = None
                decision["alignment"] = None
                if not page_bottom:
                    decision["signals"].append("terminal_right_aligned_without_page_bottom")
                if not preceding_gap:
                    decision["signals"].append("terminal_right_aligned_without_preceding_outer_gap")
                if not structural_boundary:
                    decision["signals"].append("terminal_right_aligned_without_structural_boundary")


def _is_terminal_right_aligned_run(
    run: _SamePageRun,
) -> bool:
    if run.status != "resolved" or run.lane != "right_set_off":
        return False
    page = int(run.candidates[0]["page"])
    return run.following is None or int(run.following["page"]) != page


def _terminal_preceding_gap(run: _SamePageRun, book_profile: dict[str, Any]) -> bool:
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


def _has_structural_following_boundary(
    candidates: list[dict[str, Any]],
    page: int,
    page_record: dict[str, Any] | None,
) -> bool:
    if page_record is None:
        return False
    page_height = _page_height(page_record)
    following = [candidate for candidate in candidates if int(candidate["page"]) == page]
    if page_height is None or not following:
        return False
    first = following[0]
    bbox = first.get("bbox")
    attrs = first.get("attrs")
    return (
        first.get("candidate_type") == "heading"
        and first.get("role_hint") == "title_text"
        and valid_bbox(bbox)
        and float(bbox[1]) <= page_height * 0.22
        and not (isinstance(attrs, dict) and attrs.get("layout_role") == "caption_candidate")
    )


def _apply_cross_page_display_runs(
    candidates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    profiles: dict[int, dict[str, Any]],
    book_profile: dict[str, Any],
) -> None:
    runs = _coalesce_cross_page_display_runs(
        _ordered_body_runs(candidates, profiles, book_profile),
        book_profile,
    )
    compatible: list[tuple[_SamePageRun, _SamePageRun, dict[str, Any]]] = []
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
        compatible.append((left, right, evidence))
    _apply_transition_components(compatible, book_profile)


def _coalesce_cross_page_display_runs(
    runs: list[_SamePageRun],
    book_profile: dict[str, Any],
) -> list[_SamePageRun]:
    """Join a page-edge short fragment to its same-page set-off prose continuation."""

    result: list[_SamePageRun] = []
    gap_limit = max(
        18.0,
        (_positive_float(book_profile.get("normal_gap_y")) or 0.0) * 2.0,
    )
    for run in runs:
        if result and _coalescible_set_off_runs(result[-1], run, gap_limit):
            previous = result[-1]
            result[-1] = _SamePageRun(
                candidates=[*previous.candidates, *run.candidates],
                previous=previous.previous,
                following=run.following,
                lane="left_set_off",
                short_line_alignment=None,
                status="resolved",
            )
        else:
            result.append(run)
    return result


def _coalescible_set_off_runs(
    left: _SamePageRun,
    right: _SamePageRun,
    gap_limit: float,
) -> bool:
    left_bbox = left.candidates[-1].get("bbox")
    right_bbox = right.candidates[0].get("bbox")
    return (
        int(left.candidates[0]["page"]) == int(right.candidates[0]["page"])
        and {left.lane, right.lane}.issubset({"body_indent", "left_set_off"})
        and "left_set_off" in {left.lane, right.lane}
        and (left.short_line_alignment is not None or right.short_line_alignment is not None)
        and not _has_protected_member(left)
        and not _has_protected_member(right)
        and valid_bbox(left_bbox)
        and valid_bbox(right_bbox)
        and 0.0 <= float(right_bbox[1]) - float(left_bbox[3]) <= gap_limit
    )


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
    if not _at_page_bottom_content_boundary(
        left,
        right,
        candidates,
        page_records,
    ):
        return None
    if not _at_page_edge(right, page_records.get(right_page), bottom=False):
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
        "left_observation_ids": [str(candidate["observation_id"]) for candidate in left.candidates],
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


def _at_page_bottom_content_boundary(
    left: _SamePageRun,
    right: _SamePageRun,
    candidates: list[dict[str, Any]],
    page_records: dict[int, dict[str, Any]],
) -> bool:
    left_page = int(left.candidates[0]["page"])
    page_record = page_records.get(left_page)
    if _at_page_edge(left, page_record, bottom=True):
        return True
    if page_record is None:
        return False
    page_height = _page_height(page_record)
    edge_bbox = left.candidates[-1].get("bbox")
    if page_height is None or not valid_bbox(edge_bbox):
        return False
    interruptions = _candidates_between(left, right, candidates)
    footnote_bboxes = [
        cast(list[float], candidate.get("bbox"))
        for candidate in interruptions
        if candidate.get("candidate_type") == "footnote"
        and int(candidate["page"]) == left_page
        and valid_bbox(candidate.get("bbox"))
    ]
    return (
        len(footnote_bboxes) == len(interruptions)
        and bool(footnote_bboxes)
        and float(edge_bbox[3]) < min(float(bbox[1]) for bbox in footnote_bboxes)
        and min(float(bbox[1]) for bbox in footnote_bboxes) >= page_height * 0.70
        and max(float(bbox[3]) for bbox in footnote_bboxes) >= page_height * 0.85
    )


def _candidates_between(
    left: _SamePageRun,
    right: _SamePageRun,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    indexes = {
        str(candidate["observation_id"]): index for index, candidate in enumerate(candidates)
    }
    left_end = indexes[str(left.candidates[-1]["observation_id"])]
    right_start = indexes[str(right.candidates[0]["observation_id"])]
    return candidates[left_end + 1 : right_start]


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
    interruptions = _candidates_between(left, right, candidates)
    if not interruptions:
        return True
    left_page = int(left.candidates[0]["page"])
    page_record = page_records.get(left_page)
    page_height = _page_height(page_record) if page_record is not None else None
    return page_height is not None and all(
        candidate.get("candidate_type") == "footnote"
        and int(candidate["page"]) == left_page
        and valid_bbox(candidate.get("bbox"))
        and float(candidate["bbox"][1]) >= page_height * 0.70
        for candidate in interruptions
    )


def _promote_run_decision(run: _SamePageRun) -> None:
    run_ids = [str(candidate["observation_id"]) for candidate in run.candidates]
    for candidate in run.candidates:
        decision = candidate["layout_decision"]
        decision["classified_type"] = "display_block"
        decision["layout_form"] = _layout_form(run)
        decision["alignment"] = _layout_alignment(run)
        decision["same_page_run_observation_ids"] = run_ids


def _apply_transition_components(
    compatible: list[tuple[_SamePageRun, _SamePageRun, dict[str, Any]]],
    book_profile: dict[str, Any],
) -> None:
    components: list[tuple[list[_SamePageRun], list[dict[str, Any]]]] = []
    for left, right, evidence in compatible:
        if components and components[-1][0][-1] is left:
            components[-1][0].append(right)
            components[-1][1].append(evidence)
        else:
            components.append(([left, right], [evidence]))
    for runs, transitions in components:
        if not _has_recorded_component_outer_gaps(runs, book_profile):
            continue
        for run in runs:
            _promote_run_decision(run)
            for candidate in run.candidates:
                candidate["layout_decision"]["cross_page_transitions"] = deepcopy(transitions)


def _has_recorded_component_outer_gaps(
    runs: list[_SamePageRun], book_profile: dict[str, Any]
) -> bool:
    threshold = display_gap_threshold(book_profile)
    first = runs[0]
    last = runs[-1]
    return _recorded_outer_separated(
        first.previous,
        first.candidates[0],
        threshold,
        before=True,
    ) and _recorded_outer_separated(
        last.following,
        last.candidates[-1],
        threshold,
        before=False,
    )


def _recorded_outer_separated(
    outside: dict[str, Any] | None,
    edge: dict[str, Any],
    threshold: float,
    *,
    before: bool,
) -> bool:
    if outside is None or int(outside["page"]) != int(edge["page"]):
        return False
    return _outer_separated(outside, edge, threshold, before=before)


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


def _candidate_status(candidate: dict[str, Any], profile: dict[str, Any] | None) -> str:
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
    return (
        separated_before
        and separated_after
        and any(_has_set_off_signal(signals) for signals in member_signals)
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
            signals=list(candidate.get("classification_signals") or [])
            or ["explicit_structural_role"],
            profile_source=None,
            run_ids=list(candidate.get("classification_run_ids") or [])
            or [str(candidate["observation_id"])],
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
