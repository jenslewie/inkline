"""Explicit cross-page footnote reconciliation."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, TypeGuard

from inkline.canonical.text_flow.reconcile.common import merge_records

_TOKEN_BOUNDARY = r"\s，,。.：:；;、—-"
_DOWN_WRAPPED = r"(?:（接下页）|\(接下页\)|【接下页】|\[接下页\])"
_UP_WRAPPED = r"(?:（接上页）|\(接上页\)|【接上页】|\[接上页\])"
_DOWN_SUFFIX = re.compile(
    rf"(?:\s*{_DOWN_WRAPPED}|^接下页|\s+接下页|(?<=[{_TOKEN_BOUNDARY}])接下页)\s*$"
)
_UP_PREFIX = re.compile(rf"^\s*(?:{_UP_WRAPPED}|接上页(?=$|[{_TOKEN_BOUNDARY}]))\s*")
_INDEPENDENT_MARKER = re.compile(
    r"^\s*(?:(?:译注|原注|编者注|作者注)[:：]|"
    r"\[\d{1,3}\]|［\d{1,3}］|【\d{1,3}】|〔\d{1,3}〕|"
    r"\(\d{1,3}\)|（\d{1,3}）|[⁰¹²³⁴⁵⁶⁷⁸⁹]+(?=[\s、.)）]|$)|"
    r"[①-⑳㉑-㊿❶-❿⓵-⓾]|[*†‡]|\d{1,3}(?=\D|$))"
)
_REFERENCE_ROLES = {"reference_text", "footnote_text"}
_STRUCTURAL_BOUNDARY_TYPES = {
    "caption",
    "figure",
    "heading",
    "image",
    "table",
    "table_block",
    "visual",
}


def reconcile_cross_page_footnotes(
    records: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return copied records with same-page and explicit cross-page footnotes reconciled."""

    reconciled = _reconcile_same_page_footnotes(deepcopy(records), page_layout)
    index = 0
    while index < len(reconciled):
        left = reconciled[index]
        right_index = _explicit_continuation_match(reconciled, index, page_layout)
        if right_index is None:
            index += 1
            continue
        right = reconciled[right_index]
        interruptions = reconciled[index + 1 : right_index]
        continuation_lane = _reference_lane_position(right, page_layout)
        if continuation_lane is None:
            index += 1
            continue
        _strip_structural_marker(left, _DOWN_SUFFIX, from_start=False)
        _strip_structural_marker(right, _UP_PREFIX, from_start=True)
        _normalize_reference_record_as_footnote(left)
        _normalize_reference_record_as_footnote(right)
        merge_records(
            left,
            right,
            reason="explicit_cross_page_footnote_continuation",
            joiner="\n",
            interruptions=interruptions,
            boundary_evidence={
                "left_marker": "接下页",
                "right_marker": "接上页",
                "lane": "page_foot_reference",
            },
        )
        del reconciled[right_index]
        _absorb_same_lane_tail(
            reconciled,
            left_index=index,
            tail_index=right_index,
            page_layout=page_layout,
            continuation_lane=continuation_lane,
        )
        # The merged right side may itself end with the next explicit marker.
        # Re-evaluate this same record before advancing to an unrelated record.
    return reconciled


def _reconcile_same_page_footnotes(
    records: list[dict[str, Any]],
    page_layout: dict[str, Any],
) -> list[dict[str, Any]]:
    index = 0
    while index + 1 < len(records):
        left = records[index]
        right = records[index + 1]
        evidence = _same_page_continuation_evidence(
            left,
            right,
            page_layout,
            records,
        )
        if evidence is None:
            index += 1
            continue
        merge_records(
            left,
            right,
            reason="same_page_footnote_continuation",
            joiner="\n",
            interruptions=[],
            boundary_evidence=evidence,
        )
        del records[index + 1]
    return records


def _same_page_continuation_evidence(
    left: dict[str, Any],
    right: dict[str, Any],
    page_layout: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    page = _last_page(left)
    if (
        left.get("unit_type") != "footnote"
        or right.get("unit_type") != "footnote"
        or page is None
        or _first_page(right) != page
        or _last_page(right) != page
        or not _INDEPENDENT_MARKER.search(str(left.get("text") or ""))
        or _INDEPENDENT_MARKER.search(str(right.get("text") or ""))
        or not _in_reference_lane(left, page_layout, require_page_foot=False)
        or not _in_reference_lane(right, page_layout, require_page_foot=False)
        or not _compatible_reference_lanes(left, right, page_layout)
        or _page_markers_account_for_each_footnote(records, page)
    ):
        return None
    left_bbox = _bbox_on_page(left, page)
    right_bbox = _bbox_on_page(right, page)
    if not _valid_bbox(left_bbox) or not _valid_bbox(right_bbox):
        return None
    gap = float(right_bbox[1]) - float(left_bbox[3])
    left_height = float(left_bbox[3]) - float(left_bbox[1])
    right_height = float(right_bbox[3]) - float(right_bbox[1])
    gap_limit = max(8.0, min(24.0, min(left_height, right_height) * 0.35))
    if gap < -2.0 or gap > gap_limit:
        return None
    return {
        "lane": "same_page_reference",
        "vertical_gap": gap,
        "vertical_gap_limit": gap_limit,
        "right_has_independent_marker": False,
    }


def _page_markers_account_for_each_footnote(
    records: list[dict[str, Any]],
    page: int,
) -> bool:
    markers: list[str] = []
    footnote_count = 0
    for record in records:
        if _first_page(record) != page:
            continue
        if record.get("unit_type") == "footnote":
            footnote_count += 1
            continue
        attrs = record.get("attrs")
        note_refs = attrs.get("note_refs") if isinstance(attrs, dict) else None
        for note_ref in note_refs or []:
            marker = note_ref.get("marker") if isinstance(note_ref, dict) else None
            if isinstance(marker, str) and marker and marker not in markers:
                markers.append(marker)
    return footnote_count > 0 and len(markers) >= footnote_count


def _explicit_continuation_match(
    records: list[dict[str, Any]],
    left_index: int,
    page_layout: dict[str, Any],
) -> int | None:
    left = records[left_index]
    if not _has_structural_marker(left, _DOWN_SUFFIX) or not _reference_record(left):
        return None
    left_page = _last_page(left)
    if left_page is None or not _in_reference_lane(left, page_layout, require_page_foot=True):
        return None
    right_page = left_page + 1
    for index in range(left_index + 1, len(records)):
        record = records[index]
        record_page = _first_page(record)
        if record_page is None or record_page < right_page:
            continue
        if record_page > right_page:
            return None
        if not _has_structural_marker(record, _UP_PREFIX):
            continue
        if (
            not _reference_record(record)
            or not _in_reference_lane(record, page_layout, require_page_foot=False)
            or not _compatible_reference_lanes(left, record, page_layout)
        ):
            return None
        return index
    return None


def _absorb_same_lane_tail(
    records: list[dict[str, Any]],
    *,
    left_index: int,
    tail_index: int,
    page_layout: dict[str, Any],
    continuation_lane: tuple[float, float],
) -> None:
    left = records[left_index]
    continuation_page = _last_page(left)
    while tail_index < len(records):
        tail = records[tail_index]
        if not _tail_member(
            tail,
            continuation_page,
            page_layout,
            continuation_lane,
        ):
            return
        _normalize_reference_record_as_footnote(tail)
        merge_records(
            left,
            tail,
            reason="same_lane_footnote_tail_absorption",
            joiner="\n",
            interruptions=[],
            boundary_evidence={"lane": "page_foot_reference"},
        )
        del records[tail_index]


def _tail_member(
    record: dict[str, Any],
    continuation_page: int | None,
    page_layout: dict[str, Any],
    continuation_lane: tuple[float, float],
) -> bool:
    if continuation_page is None or _first_page(record) != continuation_page:
        return False
    if str(record.get("unit_type") or "") in _STRUCTURAL_BOUNDARY_TYPES:
        return False
    if not _reference_record(record) or not _in_reference_lane(
        record, page_layout, require_page_foot=False
    ):
        return False
    lane = _reference_lane_position(record, page_layout)
    if lane is None or not _compatible_lane_positions(continuation_lane, lane):
        return False
    text = str(record.get("text") or "")
    if _INDEPENDENT_MARKER.search(text):
        return False
    return not _DOWN_SUFFIX.search(text) and not _UP_PREFIX.search(text)


def _reference_record(record: dict[str, Any]) -> bool:
    if record.get("unit_type") == "footnote":
        return True
    roles = record.get("role_hints")
    return isinstance(roles, list) and bool(_REFERENCE_ROLES & {str(role) for role in roles})


def _in_reference_lane(
    record: dict[str, Any],
    page_layout: dict[str, Any],
    *,
    require_page_foot: bool,
) -> bool:
    position = _reference_lane_position(record, page_layout)
    if position is None:
        return False
    if not require_page_foot:
        return True
    page = _last_page(record)
    page_record = _page_record(page_layout, page)
    bbox = _bbox_on_page(record, page)
    if page_record is None or not _valid_bbox(bbox):
        return False
    body_lane = page_record.get("body_lane")
    if not isinstance(body_lane, dict):
        return False
    page_height = _page_height(page_record, body_lane)
    return page_height is not None and float(bbox[1]) >= page_height * 0.75


def _compatible_reference_lanes(
    left: dict[str, Any],
    right: dict[str, Any],
    page_layout: dict[str, Any],
) -> bool:
    left_lane = _reference_lane_position(left, page_layout)
    right_lane = _reference_lane_position(right, page_layout)
    return (
        left_lane is not None
        and right_lane is not None
        and _compatible_lane_positions(left_lane, right_lane)
    )


def _compatible_lane_positions(
    anchor: tuple[float, float],
    candidate: tuple[float, float],
) -> bool:
    anchor_side = _lane_anchor(anchor)
    candidate_side = _lane_anchor(candidate)
    if anchor_side != candidate_side:
        return False
    left_delta = abs(anchor[0] - candidate[0])
    right_delta = abs(anchor[1] - candidate[1])
    if anchor_side == "left":
        return left_delta <= 0.12
    if anchor_side == "right":
        return right_delta <= 0.15
    return left_delta <= 0.12 and right_delta <= 0.15


def _lane_anchor(position: tuple[float, float]) -> str:
    left_inset, right_inset = position
    if abs(left_inset) <= 0.12:
        return "left"
    if abs(right_inset) <= 0.15:
        return "right"
    return "inset"


def _reference_lane_position(
    record: dict[str, Any], page_layout: dict[str, Any]
) -> tuple[float, float] | None:
    page = _last_page(record)
    bbox = _bbox_on_page(record, page)
    page_record = _page_record(page_layout, page)
    if page_record is None or not _valid_bbox(bbox):
        return None
    body_lane = page_record.get("body_lane")
    if not isinstance(body_lane, dict):
        return None
    body_left = _float(body_lane.get("body_left"))
    body_right = _float(body_lane.get("body_right"))
    if body_left is None or body_right is None or body_right <= body_left:
        return None
    body_width = body_right - body_left
    width = float(bbox[2]) - float(bbox[0])
    overlap = max(
        0.0,
        min(float(bbox[2]), body_right) - max(float(bbox[0]), body_left),
    )
    if width <= 0 or overlap / width < 0.7:
        return None
    return (
        (float(bbox[0]) - body_left) / body_width,
        (body_right - float(bbox[2])) / body_width,
    )


def _bbox_on_page(record: dict[str, Any], page: int | None) -> list[float] | None:
    if page is None:
        return None
    bbox = record.get("bbox")
    if record.get("page") == page and _valid_bbox(bbox):
        return bbox
    spans = record.get("spans")
    span_bboxes = [
        span["bbox"]
        for span in spans or []
        if isinstance(span, dict) and span.get("page") == page and _valid_bbox(span.get("bbox"))
    ]
    if span_bboxes:
        return [
            min(float(bbox[0]) for bbox in span_bboxes),
            min(float(bbox[1]) for bbox in span_bboxes),
            max(float(bbox[2]) for bbox in span_bboxes),
            max(float(bbox[3]) for bbox in span_bboxes),
        ]
    return None


def _strip_structural_marker(
    record: dict[str, Any],
    pattern: re.Pattern[str],
    *,
    from_start: bool,
) -> None:
    text = str(record.get("text") or "")
    record["text"] = pattern.sub("", text, count=1)
    attrs = record.get("attrs")
    inline_runs = attrs.get("inline_runs") if isinstance(attrs, dict) else None
    if not isinstance(inline_runs, list):
        return
    inline_text = "".join(
        str(run.get("text") or "") for run in inline_runs if isinstance(run, dict)
    )
    stripped = pattern.sub("", inline_text, count=1)
    removed = len(inline_text) - len(stripped)
    if removed <= 0:
        return
    _remove_inline_text(inline_runs, removed, from_start=from_start)


def _remove_inline_text(inline_runs: list[Any], removed: int, *, from_start: bool) -> None:
    ordered = inline_runs if from_start else list(reversed(inline_runs))
    remaining = removed
    for run in ordered:
        if remaining <= 0:
            return
        if not isinstance(run, dict) or not isinstance(run.get("text"), str):
            continue
        text = run["text"]
        count = min(remaining, len(text))
        run["text"] = text[count:] if from_start else text[: len(text) - count]
        remaining -= count


def _has_structural_marker(record: dict[str, Any], pattern: re.Pattern[str]) -> bool:
    return pattern.search(str(record.get("text") or "")) is not None


def _normalize_reference_record_as_footnote(record: dict[str, Any]) -> None:
    record["unit_type"] = "footnote"


def _page_record(page_layout: dict[str, Any], page: int | None) -> dict[str, Any] | None:
    if page is None:
        return None
    pages = page_layout.get("pages")
    if not isinstance(pages, list):
        return None
    return next(
        (record for record in pages if isinstance(record, dict) and record.get("page") == page),
        None,
    )


def _page_height(page_record: dict[str, Any], body_lane: dict[str, Any]) -> float | None:
    page_size = page_record.get("page_size")
    value = page_size.get("height") if isinstance(page_size, dict) else None
    return _float(value) or _float(body_lane.get("page_height"))


def _first_page(record: dict[str, Any]) -> int | None:
    pages = record.get("pages")
    value = pages[0] if isinstance(pages, list) and pages else record.get("page")
    return int(value) if isinstance(value, int) else None


def _last_page(record: dict[str, Any]) -> int | None:
    pages = record.get("pages")
    value = pages[-1] if isinstance(pages, list) and pages else record.get("page")
    return int(value) if isinstance(value, int) else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_bbox(value: Any) -> TypeGuard[list[float]]:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )
