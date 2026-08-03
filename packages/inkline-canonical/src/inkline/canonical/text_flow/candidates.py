from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, TypeGuard

from inkline.canonical.observed.schema import validate_observed_document

BODY_CANDIDATE_TYPE = "body_text"
CANDIDATE_TYPES = {"heading", BODY_CANDIDATE_TYPE, "list_item", "footnote"}


def build_text_candidates(
    document: dict[str, Any],
    *,
    included_pages: set[int],
    anchor_groups_by_observation_id: dict[str, tuple[str, ...]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return ordered atomic text candidates and ignored observation counts."""

    validate_observed_document(document)
    observations = [
        observation
        for observation in document["observations"]
        if int(observation["page"]) in included_pages
    ]
    ordered = order_text_observations(
        observations,
        protected_observation_ids=set(anchor_groups_by_observation_id),
    )
    caption_title_ids = _caption_title_observation_ids(ordered, document["pages"])
    candidates: list[dict[str, Any]] = []
    ignored: Counter[str] = Counter()
    for observation in ordered:
        candidate_type = _candidate_type(
            observation,
            caption_title_ids,
            anchor_groups_by_observation_id,
        )
        if candidate_type is None:
            ignored[str(observation["kind"])] += 1
            continue
        candidates.append(
            _candidate_from_observation(
                observation,
                candidate_type,
                anchor_groups_by_observation_id.get(str(observation["observation_id"])),
                is_caption_title=str(observation["observation_id"]) in caption_title_ids,
            )
        )
    return candidates, dict(sorted(ignored.items()))


def order_text_observations(
    observations: list[dict[str, Any]],
    *,
    protected_observation_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    protected = protected_observation_ids or set()
    ordered = sorted(
        observations,
        key=lambda observation: (
            int(observation["page"]),
            _reading_order(observation),
            _bbox_top(observation.get("bbox")),
            _bbox_left(observation.get("bbox")),
            str(observation["observation_id"]),
        ),
    )
    index = 0
    while index < len(ordered):
        if ordered[index].get("role_hint") != "title_text":
            index += 1
            continue
        slot = (int(ordered[index]["page"]), _reading_order(ordered[index]))
        end = index + 1
        while (
            end < len(ordered)
            and ordered[end].get("role_hint") == "title_text"
            and (int(ordered[end]["page"]), _reading_order(ordered[end])) == slot
        ):
            end += 1
        ordered[index:end] = sorted(
            ordered[index:end],
            key=lambda observation: 0 if str(observation["observation_id"]) in protected else 1,
        )
        index = end
    return ordered


def _caption_title_observation_ids(
    observations: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> set[str]:
    image_bboxes = _region_bboxes(observations, {"image_region"})
    page_sizes = _page_sizes(pages)
    ids: set[str] = set()
    text_observations_by_page: dict[int, list[dict[str, Any]]] = {}
    for observation in observations:
        if observation.get("kind") in {"text_region", "footnote_region"}:
            text_observations_by_page.setdefault(int(observation["page"]), []).append(observation)

    for page, text_observations in text_observations_by_page.items():
        visuals = image_bboxes.get(page) or []
        if not visuals:
            continue
        page_size = page_sizes.get(page, {})
        for index, observation in enumerate(text_observations[:-1]):
            if observation.get("role_hint") != "title_text":
                continue
            if _near_visual_region(observation, image_bboxes) and len(text_observations) > 1:
                ids.add(str(observation["observation_id"]))
                continue
            following = text_observations[index + 1]
            if following.get("role_hint") != "body_text":
                continue
            if not _caption_text_group(observation, following):
                continue
            if _visual_text_group(observation, following, visuals) or (
                _visual_dominant_annotation_page(text_observations, visuals, page_size)
            ):
                ids.add(str(observation["observation_id"]))
    return ids


def _candidate_type(
    observation: dict[str, Any],
    caption_title_ids: set[str],
    anchor_groups_by_observation_id: dict[str, tuple[str, ...]],
) -> str | None:
    observation_id = str(observation["observation_id"])
    if observation_id in anchor_groups_by_observation_id:
        return "heading"
    role_hint = observation["role_hint"]
    if role_hint == "title_text":
        return BODY_CANDIDATE_TYPE if observation_id in caption_title_ids else "heading"
    if role_hint == "body_text":
        return BODY_CANDIDATE_TYPE
    if role_hint in {"list_text", "reference_text"}:
        return "list_item"
    if observation["kind"] == "footnote_region" or role_hint == "footnote_text":
        return "footnote"
    return None


def _candidate_from_observation(
    observation: dict[str, Any],
    candidate_type: str,
    protected_anchor_group: tuple[str, ...] | None,
    *,
    is_caption_title: bool,
) -> dict[str, Any]:
    attrs = _candidate_attrs(observation)
    if is_caption_title and protected_anchor_group is None:
        attrs["layout_role"] = "caption_candidate"
    return {
        "observation_id": str(observation["observation_id"]),
        "candidate_type": candidate_type,
        "text": str(observation.get("text") or ""),
        "page": observation["page"],
        "bbox": deepcopy(observation.get("bbox")),
        "spans": _observation_spans(observation),
        "role_hint": observation["role_hint"],
        "attrs": attrs,
        "parser_payload": deepcopy(observation.get("parser_payload") or {}),
        "protected_anchor_group": list(protected_anchor_group)
        if protected_anchor_group is not None
        else None,
    }


def _candidate_attrs(observation: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    observation_attrs = observation.get("attrs")
    if not isinstance(observation_attrs, Mapping):
        return attrs
    text_line_metrics = observation_attrs.get("text_line_metrics")
    if isinstance(text_line_metrics, Mapping):
        attrs["text_line_metrics_by_observation"] = {
            str(observation["observation_id"]): deepcopy(text_line_metrics)
        }
    for field in ("inline_runs", "note_refs"):
        value = observation_attrs.get(field)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            attrs[field] = deepcopy(value)
    return attrs


def _observation_spans(observation: dict[str, Any]) -> list[dict[str, Any]]:
    spans = observation.get("spans")
    if isinstance(spans, Sequence) and not isinstance(spans, str | bytes) and spans:
        return [dict(span) for span in spans if isinstance(span, Mapping)]
    bbox = observation.get("bbox")
    if _valid_bbox(bbox):
        return [{"page": observation["page"], "bbox": deepcopy(bbox)}]
    return []


def _page_sizes(pages: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    return {
        int(page["page"]): {"width": float(page["width"]), "height": float(page["height"])}
        for page in pages
        if isinstance(page.get("page"), int)
        and isinstance(page.get("width"), int | float)
        and isinstance(page.get("height"), int | float)
    }


def _region_bboxes(
    observations: list[dict[str, Any]], kinds: set[str]
) -> dict[int, list[list[float]]]:
    grouped: dict[int, list[list[float]]] = {}
    for observation in observations:
        if observation.get("kind") not in kinds:
            continue
        bbox = observation.get("bbox")
        if _valid_bbox(bbox):
            grouped.setdefault(int(observation["page"]), []).append(
                [float(value) for value in bbox]
            )
    return grouped


def _caption_text_group(title: dict[str, Any], following: dict[str, Any]) -> bool:
    title_bbox = title.get("bbox")
    following_bbox = following.get("bbox")
    if not _valid_bbox(title_bbox) or not _valid_bbox(following_bbox):
        return False
    return 0 <= _vertical_gap(title_bbox, following_bbox) <= max(
        40.0, _height(title_bbox) * 2.0
    ) and (
        _horizontal_overlap_ratio(title_bbox, following_bbox) >= 0.5
        or _left_delta(title_bbox, following_bbox) <= 32.0
    )


def _visual_text_group(
    title: dict[str, Any],
    following: dict[str, Any],
    visual_bboxes: list[list[float]],
) -> bool:
    group_bbox = _union_bbox(title["bbox"], following["bbox"])
    return any(_near_visual_bbox(group_bbox, visual_bbox) for visual_bbox in visual_bboxes)


def _visual_dominant_annotation_page(
    text_observations: list[dict[str, Any]],
    visual_bboxes: list[list[float]],
    page_size: dict[str, float],
) -> bool:
    if len(visual_bboxes) >= 3:
        return True
    page_width = float(page_size.get("width") or 0.0)
    if page_width <= 0:
        return False
    body_widths = [
        _width(observation["bbox"])
        for observation in text_observations
        if observation.get("role_hint") == "body_text" and _valid_bbox(observation.get("bbox"))
    ]
    return bool(body_widths) and max(body_widths) <= page_width * 0.45


def _reading_order(observation: dict[str, Any]) -> int:
    attrs = observation.get("attrs") if isinstance(observation.get("attrs"), Mapping) else {}
    value = attrs.get("reading_order")  # pyright: ignore[reportOptionalMemberAccess]
    return int(value) if isinstance(value, int) else 999999


def _valid_bbox(value: Any) -> TypeGuard[Sequence[float]]:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, str | bytes)
        and len(value) == 4
        and all(isinstance(number, int | float) for number in value)
    )


def _bbox_top(value: Any) -> float:
    return float(value[1]) if _valid_bbox(value) else 999999.0


def _bbox_left(value: Any) -> float:
    return float(value[0]) if _valid_bbox(value) else 999999.0


def _vertical_gap(left: Sequence[float], right: Sequence[float]) -> float:
    return float(right[1]) - float(left[3])


def _left_delta(left: Sequence[float], right: Sequence[float]) -> float:
    return abs(float(left[0]) - float(right[0]))


def _height(bbox: Sequence[float]) -> float:
    return float(bbox[3]) - float(bbox[1])


def _width(bbox: Sequence[float]) -> float:
    return float(bbox[2]) - float(bbox[0])


def _horizontal_overlap_ratio(left: Sequence[float], right: Sequence[float]) -> float:
    overlap = max(0.0, min(float(left[2]), float(right[2])) - max(float(left[0]), float(right[0])))
    width = min(float(left[2]) - float(left[0]), float(right[2]) - float(right[0]))
    if width <= 0:
        return 0.0
    return overlap / width


def _near_visual_region(
    observation: dict[str, Any],
    visual_bboxes: dict[int, list[list[float]]],
) -> bool:
    bbox = observation.get("bbox")
    if observation.get("role_hint") != "title_text" or not _valid_bbox(bbox):
        return False
    text_bbox = [float(value) for value in bbox]
    for visual_bbox in visual_bboxes.get(int(observation["page"]), []):
        if _near_visual_bbox(text_bbox, visual_bbox):
            return True
    return False


def _near_visual_bbox(text_bbox: list[float], visual_bbox: list[float]) -> bool:
    vertical_gap = max(
        float(visual_bbox[1]) - float(text_bbox[3]),
        float(text_bbox[1]) - float(visual_bbox[3]),
        0.0,
    )
    horizontal_gap = max(
        float(visual_bbox[0]) - float(text_bbox[2]),
        float(text_bbox[0]) - float(visual_bbox[2]),
        0.0,
    )
    return vertical_gap <= 64.0 and (
        _horizontal_overlap_ratio(text_bbox, visual_bbox) >= 0.5 or horizontal_gap <= 96.0
    )


def _union_bbox(left: list[float], right: list[float]) -> list[float]:
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]
