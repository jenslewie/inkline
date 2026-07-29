from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from itertools import pairwise
from typing import Any

from inkline.canonical.book_skeleton.validation import validate_book_skeleton_against_index
from inkline.canonical.observed.index import ObservedIndex, build_observed_index
from inkline.canonical.observed.schema import validate_observed_document
from inkline.canonical.observed.text_units import TEXT_UNIT_TYPES
from inkline.canonical.page_layout.validation import validate_page_layout_analysis
from inkline.canonical.page_review import validate_resolved_page_review
from inkline.canonical.schema import ValidationError
from inkline.canonical.text_flow.candidates import order_text_observations
from inkline.canonical.text_flow.contract import TEXT_FLOW_SCHEMA_NAME, TEXT_FLOW_SCHEMA_VERSION

TOP_LEVEL_FIELDS = {
    "metadata",
    "text_units",
    "ignored_observation_counts",
    "provenance",
}
METADATA_FIELDS = {"schema_name", "schema_version", "doc_id"}
PROVENANCE_FIELDS = {
    "observed_schema_name",
    "observed_schema_version",
    "skeleton_schema_name",
    "skeleton_schema_version",
    "page_review_schema_name",
    "page_review_schema_version",
    "page_layout_schema_name",
    "page_layout_schema_version",
    "included_pages",
    "excluded_pages",
    "direct_anchor_group_count",
}
UNIT_FIELDS = {
    "unit_id",
    "unit_type",
    "text",
    "page",
    "pages",
    "bbox",
    "spans",
    "observation_ids",
    "role_hints",
    "attrs",
    "parser_payloads",
}
LAYOUT_FRAGMENT_FIELDS = {
    "observation_id",
    "page",
    "classified_type",
    "status",
    "layout_form",
    "signals",
}
LAYOUT_FRAGMENT_STATUSES = {"resolved", "uncertain"}
MERGE_EVENT_REQUIRED_FIELDS = {
    "reason",
    "left_page",
    "right_page",
    "left_observation_ids",
    "right_observation_ids",
    "interrupting_observation_ids",
}
MERGE_EVENT_OPTIONAL_FIELDS = {"boundary_evidence"}


def validate_text_flow(flow: dict[str, Any]) -> None:
    """Validate the standalone TextFlow artifact contract."""

    if set(flow) != TOP_LEVEL_FIELDS:
        raise ValidationError("text_flow has invalid top-level fields")
    _validate_metadata(flow.get("metadata"))
    _validate_provenance(flow.get("provenance"))
    _validate_ignored_counts(flow.get("ignored_observation_counts"))
    _validate_units(flow.get("text_units"))


def validate_text_flow_against_sources(
    flow: dict[str, Any],
    observed_document: dict[str, Any],
    skeleton: dict[str, Any],
    page_review: dict[str, Any],
    page_layout: dict[str, Any],
    *,
    observed_index: ObservedIndex | None = None,
) -> None:
    """Validate TextFlow identities and boundaries against all declared evidence."""

    validate_text_flow(flow)
    validate_observed_document(observed_document)
    index = observed_index or build_observed_index(observed_document)
    _validate_index(index, observed_document)
    validate_book_skeleton_against_index(skeleton, index)
    validate_resolved_page_review(page_review)
    validate_page_layout_analysis(page_layout)
    _validate_source_doc_ids(flow, index, skeleton, page_review, page_layout)

    included_pages, excluded_pages = _review_page_sets(page_review, index.page_numbers)
    provenance = flow["provenance"]
    if provenance["included_pages"] != sorted(included_pages):
        raise ValidationError("text_flow provenance included_pages differs from PageReview")
    if provenance["excluded_pages"] != sorted(excluded_pages):
        raise ValidationError("text_flow provenance excluded_pages differs from PageReview")

    direct_anchor_ids = {
        observation_id
        for group in _direct_anchor_groups(skeleton, included_pages)
        for observation_id in group
    }
    _validate_units_against_observations(
        flow["text_units"],
        index.observations_by_id,
        included_pages,
        protected_observation_ids=direct_anchor_ids,
    )
    _validate_merge_events_against_observations(
        flow["text_units"],
        index.observations_by_id,
    )
    _validate_anchor_boundaries(flow, skeleton, included_pages)


def _validate_units_against_observations(
    units: list[dict[str, Any]],
    observations: Mapping[str, Mapping[str, Any]],
    included_pages: set[int],
    *,
    protected_observation_ids: set[str],
) -> None:
    ordered = order_text_observations(
        [dict(observation) for observation in observations.values()],
        protected_observation_ids=protected_observation_ids,
    )
    observation_order = {
        str(observation["observation_id"]): order for order, observation in enumerate(ordered)
    }
    seen_observations: set[str] = set()
    previous_unit_order = -1
    for unit_index, unit in enumerate(units):
        observation_ids = unit["observation_ids"]
        unit_observations: list[Mapping[str, Any]] = []
        unit_orders: list[int] = []
        for observation_id in observation_ids:
            observation = observations.get(observation_id)
            if observation is None:
                raise ValidationError(
                    f"text_flow.text_units[{unit_index}] references unknown observation"
                )
            if observation_id in seen_observations:
                raise ValidationError("text_flow observation ids must be assigned at most once")
            seen_observations.add(observation_id)
            unit_orders.append(observation_order[observation_id])
            unit_observations.append(observation)
        if unit_orders != sorted(unit_orders):
            raise ValidationError("text_flow unit observation ids must preserve source order")
        if unit_orders[0] <= previous_unit_order:
            raise ValidationError("text_flow units must preserve source start order")
        previous_unit_order = unit_orders[0]
        observation_pages = list(
            dict.fromkeys(int(observation["page"]) for observation in unit_observations)
        )
        if unit["pages"] != observation_pages or unit["page"] != observation_pages[0]:
            raise ValidationError(f"text_flow.text_units[{unit_index}] page provenance differs")
        if any(page not in included_pages for page in observation_pages):
            raise ValidationError(
                f"text_flow.text_units[{unit_index}] uses a page excluded by PageReview"
            )


def _validate_anchor_boundaries(
    flow: dict[str, Any], skeleton: dict[str, Any], included_pages: set[int]
) -> None:
    direct_groups = _direct_anchor_groups(skeleton, included_pages)
    if flow["provenance"]["direct_anchor_group_count"] != len(direct_groups):
        raise ValidationError("text_flow direct anchor count differs from Skeleton")
    unit_groups = [tuple(unit["observation_ids"]) for unit in flow["text_units"]]
    for group in direct_groups:
        if unit_groups.count(group) != 1:
            raise ValidationError("each direct Skeleton anchor must be one exact TextUnit")
    protected = {observation_id: group for group in direct_groups for observation_id in group}
    for unit in flow["text_units"]:
        groups = {protected[value] for value in unit["observation_ids"] if value in protected}
        if len(groups) > 1:
            raise ValidationError("TextUnit crosses distinct direct Skeleton anchors")


def _validate_merge_events_against_observations(
    units: list[dict[str, Any]],
    observations: Mapping[str, Mapping[str, Any]],
) -> None:
    for unit in units:
        for event in unit["attrs"].get("merge_events", []):
            left_page = int(event["left_page"])
            right_page = int(event["right_page"])
            left_source_pages = [
                int(observations[observation_id]["page"])
                for observation_id in event["left_observation_ids"]
            ]
            right_source_pages = {
                int(observations[observation_id]["page"])
                for observation_id in event["right_observation_ids"]
            }
            if (
                left_page not in left_source_pages
                or max(left_source_pages) != left_page
                or right_source_pages != {right_page}
            ):
                raise ValidationError("TextFlow merge event source page provenance differs")


def _validate_metadata(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != METADATA_FIELDS:
        raise ValidationError("text_flow metadata has invalid fields")
    if value.get("schema_name") != TEXT_FLOW_SCHEMA_NAME:
        raise ValidationError(f"text_flow metadata.schema_name must be {TEXT_FLOW_SCHEMA_NAME}")
    if value.get("schema_version") != TEXT_FLOW_SCHEMA_VERSION:
        raise ValidationError(
            f"text_flow metadata.schema_version must be {TEXT_FLOW_SCHEMA_VERSION}"
        )
    if not isinstance(value.get("doc_id"), str) or not value["doc_id"]:
        raise ValidationError("text_flow metadata.doc_id must be non-empty string")


def _validate_provenance(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != PROVENANCE_FIELDS:
        raise ValidationError("text_flow provenance has invalid fields")
    for field in PROVENANCE_FIELDS - {
        "included_pages",
        "excluded_pages",
        "direct_anchor_group_count",
    }:
        if not isinstance(value.get(field), str) or not value[field]:
            raise ValidationError(f"text_flow provenance.{field} must be non-empty string")
    for field in ("included_pages", "excluded_pages"):
        pages = value.get(field)
        if (
            not isinstance(pages, list)
            or pages != sorted(set(pages))
            or not all(isinstance(page, int) and page > 0 for page in pages)
        ):
            raise ValidationError(f"text_flow provenance.{field} must be ordered unique pages")
    if not isinstance(value.get("direct_anchor_group_count"), int):
        raise ValidationError("text_flow provenance.direct_anchor_group_count must be integer")


def _validate_ignored_counts(value: Any) -> None:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(count, int) or count < 0
        for key, count in value.items()
    ):
        raise ValidationError("text_flow ignored_observation_counts must be non-negative counts")


def _validate_units(value: Any) -> None:
    if not isinstance(value, list):
        raise ValidationError("text_flow text_units must be list")
    ids: list[str] = []
    for index, unit in enumerate(value):
        if not isinstance(unit, dict) or set(unit) != UNIT_FIELDS:
            raise ValidationError(f"text_flow.text_units[{index}] has invalid fields")
        expected_id = f"tu{index + 1:06d}"
        if unit.get("unit_id") != expected_id:
            raise ValidationError("text_flow unit ids must be ordered contiguous tu ids")
        ids.append(expected_id)
        if unit.get("unit_type") not in TEXT_UNIT_TYPES:
            raise ValidationError(f"text_flow.text_units[{index}].unit_type is invalid")
        if not isinstance(unit.get("text"), str):
            raise ValidationError(f"text_flow.text_units[{index}].text must be string")
        _validate_unit_collections(unit, index)
        _validate_layout_evidence(unit)
        _validate_adjacent_page_merge_events(unit, unit["attrs"])
    if len(ids) != len(set(ids)):
        raise ValidationError("text_flow unit ids must be unique")


def _validate_unit_collections(unit: dict[str, Any], index: int) -> None:
    if not isinstance(unit.get("page"), int):
        raise ValidationError(f"text_flow.text_units[{index}].page must be integer")
    pages = unit.get("pages")
    if not isinstance(pages, list) or not pages or pages != sorted(set(pages)):
        raise ValidationError(f"text_flow.text_units[{index}].pages must be ordered unique")
    observation_ids = unit.get("observation_ids")
    if (
        not isinstance(observation_ids, list)
        or not observation_ids
        or len(observation_ids) != len(set(observation_ids))
        or not all(isinstance(value, str) and value for value in observation_ids)
    ):
        raise ValidationError(
            f"text_flow.text_units[{index}].observation_ids must be non-empty unique strings"
        )
    for field in ("spans", "role_hints", "parser_payloads"):
        if not isinstance(unit.get(field), list):
            raise ValidationError(f"text_flow.text_units[{index}].{field} must be list")
    if not isinstance(unit.get("attrs"), dict):
        raise ValidationError(f"text_flow.text_units[{index}].attrs must be object")


def _validate_layout_evidence(unit: dict[str, Any]) -> None:
    if unit["unit_type"] not in {"paragraph", "display_block"}:
        return
    attrs = unit["attrs"]
    fragments = attrs.get("layout_fragments", [])
    if not isinstance(fragments, list) or not fragments:
        raise ValidationError("TextFlow layout fragment is invalid")
    for fragment in fragments:
        _validate_layout_fragment(fragment)
        if fragment["classified_type"] != unit["unit_type"]:
            raise ValidationError("TextFlow layout fragment type differs from final unit type")


def _validate_layout_fragment(fragment: Any) -> None:
    if not isinstance(fragment, Mapping) or set(fragment) != LAYOUT_FRAGMENT_FIELDS:
        raise ValidationError("TextFlow layout fragment is invalid")
    observation_id = fragment["observation_id"]
    page = fragment["page"]
    classified_type = fragment["classified_type"]
    status = fragment["status"]
    layout_form = fragment["layout_form"]
    signals = fragment["signals"]
    if not isinstance(observation_id, str) or not observation_id:
        raise ValidationError("TextFlow layout fragment is invalid")
    if type(page) is not int or page <= 0:
        raise ValidationError("TextFlow layout fragment is invalid")
    if not isinstance(classified_type, str) or not classified_type:
        raise ValidationError("TextFlow layout fragment is invalid")
    if not isinstance(status, str) or status not in LAYOUT_FRAGMENT_STATUSES:
        raise ValidationError("TextFlow layout fragment is invalid")
    if layout_form is not None and (not isinstance(layout_form, str) or not layout_form):
        raise ValidationError("TextFlow layout fragment is invalid")
    if not isinstance(signals, list) or not all(
        isinstance(signal, str) and signal for signal in signals
    ):
        raise ValidationError("TextFlow layout fragment is invalid")


def _validate_adjacent_page_merge_events(unit: dict[str, Any], attrs: dict[str, Any]) -> None:
    transitions = [
        (left_page, right_page)
        for left_page, right_page in pairwise(unit["pages"])
        if right_page == left_page + 1
    ]
    merge_events = attrs.get("merge_events", [])
    if not isinstance(merge_events, list):
        raise ValidationError("TextFlow requires one merge event per adjacent-page transition")
    event_transitions: list[tuple[int, int]] = []
    for event in merge_events:
        transition = _validated_merge_event_transition(event, unit)
        if transition[0] == transition[1]:
            if transition[0] not in unit["pages"]:
                raise ValidationError(
                    "TextFlow requires one merge event per adjacent-page transition"
                )
            continue
        event_transitions.append(transition)
    if Counter(event_transitions) != Counter(transitions):
        raise ValidationError("TextFlow requires one merge event per adjacent-page transition")


def _validated_merge_event_transition(event: Any, unit: dict[str, Any]) -> tuple[int, int]:
    if (
        not isinstance(event, Mapping)
        or not MERGE_EVENT_REQUIRED_FIELDS.issubset(event)
        or not set(event).issubset(MERGE_EVENT_REQUIRED_FIELDS | MERGE_EVENT_OPTIONAL_FIELDS)
        or not isinstance(event.get("reason"), str)
        or not event["reason"]
    ):
        raise ValidationError("TextFlow requires one merge event per adjacent-page transition")
    left_page = event["left_page"]
    right_page = event["right_page"]
    if (
        type(left_page) is not int
        or type(right_page) is not int
        or left_page <= 0
        or right_page <= 0
    ):
        raise ValidationError("TextFlow requires one merge event per adjacent-page transition")
    left_ids = _validated_merge_event_observation_ids(
        event["left_observation_ids"], allow_empty=False
    )
    right_ids = _validated_merge_event_observation_ids(
        event["right_observation_ids"], allow_empty=False
    )
    _validated_merge_event_observation_ids(event["interrupting_observation_ids"], allow_empty=True)
    if set(left_ids).intersection(right_ids) or not set(left_ids + right_ids).issubset(
        unit["observation_ids"]
    ):
        raise ValidationError("TextFlow requires one merge event per adjacent-page transition")
    boundary_evidence = event.get("boundary_evidence")
    if "boundary_evidence" in event and not isinstance(boundary_evidence, Mapping):
        raise ValidationError("TextFlow requires one merge event per adjacent-page transition")
    return left_page, right_page


def _validated_merge_event_observation_ids(value: Any, *, allow_empty: bool) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError("TextFlow requires one merge event per adjacent-page transition")
    return value


def _validate_index(index: ObservedIndex, document: dict[str, Any]) -> None:
    doc_id = str(document["metadata"]["doc_id"])
    if index.doc_id != doc_id:
        raise ValidationError("ObservedIndex and ObservedDocument doc_id values differ")


def _validate_source_doc_ids(
    flow: dict[str, Any],
    index: ObservedIndex,
    skeleton: dict[str, Any],
    page_review: dict[str, Any],
    page_layout: dict[str, Any],
) -> None:
    expected = index.doc_id
    sources = {
        "TextFlow": flow.get("metadata", {}),
        "BookSkeleton": skeleton.get("metadata", {}),
        "PageReview": page_review.get("metadata", {}),
        "PageLayoutAnalysis": page_layout.get("metadata", {}),
    }
    for name, metadata in sources.items():
        if metadata.get("doc_id") != expected:
            raise ValidationError(f"{name} and ObservedDocument doc_id values differ")


def _review_page_sets(
    page_review: dict[str, Any], page_numbers: tuple[int, ...]
) -> tuple[set[int], set[int]]:
    actions: dict[int, str] = {}
    for record in page_review["pages"]:
        page = int(record["page"])
        if page in actions:
            raise ValidationError(f"PageReview contains duplicate page {page}")
        actions[page] = str(record["text_flow_action"])
    expected = set(page_numbers)
    if set(actions) != expected:
        raise ValidationError("PageReview must contain exactly one record for every observed page")
    included = {page for page, action in actions.items() if action == "include"}
    return included, expected - included


def _direct_anchor_groups(
    skeleton: dict[str, Any], included_pages: set[int]
) -> list[tuple[str, ...]]:
    groups: list[tuple[str, ...]] = []
    owners: dict[str, tuple[str, ...]] = {}
    for entry in skeleton["toc_entries"]:
        anchor = entry.get("selected_start_anchor")
        if (
            not isinstance(anchor, Mapping)
            or anchor.get("resolution_method") != "observed_title_match"
            or int(anchor["page"]) not in included_pages
        ):
            continue
        group = tuple(str(value) for value in anchor.get("title_observation_ids") or [])
        if not group:
            continue
        for observation_id in group:
            owner = owners.get(observation_id)
            if owner is not None and owner != group:
                raise ValidationError("Skeleton direct anchor groups overlap")
            owners[observation_id] = group
        groups.append(group)
    return groups
