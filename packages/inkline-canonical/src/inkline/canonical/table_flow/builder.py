from __future__ import annotations

from collections.abc import Sequence
from html import unescape
from html.parser import HTMLParser
from typing import Any, Mapping

from inkline.canonical.observed import ObservedIndex, validate_observed_document
from inkline.canonical.page_review import validate_resolved_page_review
from inkline.canonical.table_flow.contract import (
    TABLE_FLOW_SCHEMA_NAME,
    TABLE_FLOW_SCHEMA_VERSION,
)
from inkline.canonical.table_flow.validation import validate_table_flow_against_sources


def build_table_flow(
    observed_document: dict[str, Any],
    observed_index: ObservedIndex,
    page_review: dict[str, Any],
) -> dict[str, Any]:
    """Materialize tables that PageReview admits to the structured reading flow."""

    validate_observed_document(observed_document)
    validate_resolved_page_review(page_review)
    records = sorted(
        (
            observation
            for observation in observed_index.observations_by_id.values()
            if observation["kind"] == "table_region"
        ),
        key=_observation_order,
    )
    caption_ids_by_parent = _caption_ids_by_parent(observed_index)
    tables: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    current: list[Mapping[str, Any]] = []

    for observation in records:
        table_attrs = _normalized_table_attrs(observation)
        if table_attrs is None:
            if current:
                tables.append(_materialize_table(current, len(tables) + 1, caption_ids_by_parent))
                current = []
            unresolved.append(_unresolved_run([observation], "missing_normalized_table_content"))
            continue
        if table_attrs["html"].strip():
            if current:
                tables.append(_materialize_table(current, len(tables) + 1, caption_ids_by_parent))
            current = [observation]
            continue
        if current and int(observation["page"]) == int(current[-1]["page"]) + 1:
            current.append(observation)
            continue
        if current:
            tables.append(_materialize_table(current, len(tables) + 1, caption_ids_by_parent))
            current = []
        _append_unresolved_continuation(unresolved, observation)

    if current:
        tables.append(_materialize_table(current, len(tables) + 1, caption_ids_by_parent))

    included_pages = {
        int(record["page"])
        for record in page_review["pages"]
        if record["text_flow_action"] == "include"
    }
    tables, unresolved, excluded = _apply_page_review(
        tables,
        unresolved,
        included_pages,
    )
    table_flow = {
        "metadata": {
            "schema_name": TABLE_FLOW_SCHEMA_NAME,
            "schema_version": TABLE_FLOW_SCHEMA_VERSION,
            "doc_id": observed_index.doc_id,
        },
        "tables": tables,
        "unresolved_table_observation_runs": unresolved,
        "excluded_table_observation_runs": excluded,
    }
    validate_table_flow_against_sources(
        table_flow,
        observed_document,
        observed_index,
        page_review,
    )
    return table_flow


def _apply_page_review(
    tables: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    included_pages: set[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    admitted: list[dict[str, Any]] = []
    remaining_unresolved: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for table in tables:
        pages = set(table["pages"])
        if pages <= included_pages:
            table["table_id"] = f"tbl{len(admitted) + 1:06d}"
            admitted.append(table)
        elif pages.isdisjoint(included_pages):
            excluded.append(
                {
                    "observation_ids": list(table["observation_ids"]),
                    "pages": list(table["pages"]),
                    "reason": "excluded_by_page_review",
                }
            )
        else:
            remaining_unresolved.append(
                {
                    "observation_ids": list(table["observation_ids"]),
                    "pages": list(table["pages"]),
                    "reason": "page_review_splits_table_candidate",
                }
            )
    for run in unresolved:
        if set(run["pages"]).isdisjoint(included_pages):
            excluded.append(
                {
                    **run,
                    "reason": "excluded_by_page_review",
                }
            )
        else:
            remaining_unresolved.append(run)
    return admitted, remaining_unresolved, excluded


def _observation_order(observation: Mapping[str, Any]) -> tuple[int, int, str]:
    attrs = observation.get("attrs")
    reading_order = attrs.get("reading_order") if isinstance(attrs, Mapping) else None
    return (
        int(observation["page"]),
        int(reading_order) if isinstance(reading_order, int) else 1_000_000,
        str(observation["observation_id"]),
    )


def _normalized_table_attrs(observation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    attrs = observation.get("attrs")
    table = attrs.get("table") if isinstance(attrs, Mapping) else None
    if not isinstance(table, Mapping):
        return None
    html = table.get("html")
    is_continuation = table.get("is_continuation")
    if not isinstance(html, str) or not isinstance(is_continuation, bool):
        return None
    if is_continuation != (not html.strip()):
        return None
    return table


def _caption_ids_by_parent(index: ObservedIndex) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for observation in index.observations_by_id.values():
        attrs = observation.get("attrs")
        if not isinstance(attrs, Mapping) or attrs.get("source_kind") != "table_caption":
            continue
        parent = attrs.get("visual_parent_observation_id")
        if isinstance(parent, str) and parent:
            result.setdefault(parent, []).append(str(observation["observation_id"]))
    return result


def _materialize_table(
    observations: list[Mapping[str, Any]],
    index: int,
    caption_ids_by_parent: dict[str, list[str]],
) -> dict[str, Any]:
    primary = observations[0]
    primary_attrs = _normalized_table_attrs(primary)
    assert primary_attrs is not None
    observation_ids = [str(observation["observation_id"]) for observation in observations]
    caption_observation_ids = list(
        dict.fromkeys(
            caption_id
            for observation_id in observation_ids
            for caption_id in caption_ids_by_parent.get(observation_id, [])
        )
    )
    caption_texts = _unique_texts(
        text
        for observation in observations
        for text in _table_text_list(observation, "caption_texts")
    )
    footnote_texts = _unique_texts(
        text
        for observation in observations
        for text in _table_text_list(observation, "footnote_texts")
    )
    html = str(primary_attrs["html"])
    return {
        "table_id": f"tbl{index:06d}",
        "html": html,
        "text": _html_table_to_text(html),
        "pages": sorted({int(observation["page"]) for observation in observations}),
        "spans": [
            {
                "observation_id": str(observation["observation_id"]),
                "page": int(observation["page"]),
                "bbox": _materialized_bbox(observation.get("bbox")),
            }
            for observation in observations
        ],
        "observation_ids": observation_ids,
        "primary_observation_id": str(primary["observation_id"]),
        "caption_observation_ids": caption_observation_ids,
        "caption_texts": caption_texts,
        "footnote_texts": footnote_texts,
        "attrs": {
            "table_type": primary_attrs.get("table_type"),
            "nest_level": primary_attrs.get("nest_level"),
        },
    }


def _table_text_list(observation: Mapping[str, Any], key: str) -> list[str]:
    table = _normalized_table_attrs(observation)
    values = table.get(key) if table is not None else None
    if not isinstance(values, Sequence) or isinstance(values, str | bytes):
        return []
    return [value for value in values if isinstance(value, str) and value]


def _materialized_bbox(value: Any) -> list[Any] | None:
    """Copy frozen source geometry into the JSON-list artifact boundary."""

    return list(value) if value is not None else None


def _unique_texts(values: Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _append_unresolved_continuation(
    unresolved: list[dict[str, Any]],
    observation: Mapping[str, Any],
) -> None:
    page = int(observation["page"])
    if (
        unresolved
        and unresolved[-1]["reason"] == "continuation_without_primary"
        and page == int(unresolved[-1]["pages"][-1]) + 1
    ):
        unresolved[-1]["observation_ids"].append(str(observation["observation_id"]))
        unresolved[-1]["pages"].append(page)
        return
    unresolved.append(_unresolved_run([observation], "continuation_without_primary"))


def _unresolved_run(
    observations: list[Mapping[str, Any]],
    reason: str,
) -> dict[str, Any]:
    return {
        "observation_ids": [str(observation["observation_id"]) for observation in observations],
        "pages": sorted({int(observation["page"]) for observation in observations}),
        "reason": reason,
    }


class _TableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.append(unescape("".join(self._cell_parts).strip()))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)


def _html_table_to_text(html: str) -> str:
    parser = _TableTextParser()
    parser.feed(html)
    return "\n".join("\t".join(row) for row in parser.rows)
