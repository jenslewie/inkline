from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from inkline.canonical.observed.schema import validate_observed_document
from inkline.canonical.schema import ValidationError


@dataclass(frozen=True)
class ObservedIndex:
    """Read-only lookup topology over one validated ObservedDocument."""

    doc_id: str
    metadata: Mapping[str, Any]
    page_numbers: tuple[int, ...]
    pages_by_number: Mapping[int, Mapping[str, Any]]
    observations_by_id: Mapping[str, Mapping[str, Any]]
    observation_ids_by_page: Mapping[int, tuple[str, ...]]
    assets_by_id: Mapping[str, Mapping[str, Any]]


def build_observed_index(document: dict[str, Any]) -> ObservedIndex:
    """Index validated source records without copying or interpreting them."""

    validate_observed_document(document)
    pages_by_number = {
        int(page["page"]): page for page in sorted(document["pages"], key=lambda item: item["page"])
    }
    observations_by_id = {
        str(observation["observation_id"]): observation for observation in document["observations"]
    }
    observation_ids_by_page: dict[int, list[str]] = {
        page_number: [] for page_number in pages_by_number
    }
    for observation_id, observation in observations_by_id.items():
        observation_ids_by_page[int(observation["page"])].append(observation_id)
    assets_by_id = _index_assets(document["assets"])
    return ObservedIndex(
        doc_id=str(document["metadata"]["doc_id"]),
        metadata=MappingProxyType(document["metadata"]),
        page_numbers=tuple(pages_by_number),
        pages_by_number=MappingProxyType(pages_by_number),
        observations_by_id=MappingProxyType(observations_by_id),
        observation_ids_by_page=MappingProxyType(
            {
                page_number: tuple(observation_ids)
                for page_number, observation_ids in observation_ids_by_page.items()
            }
        ),
        assets_by_id=MappingProxyType(assets_by_id),
    )


def _index_assets(assets: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in _asset_records(assets):
        asset_id = record.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            continue
        if asset_id in indexed:
            raise ValidationError(f"duplicate asset_id: {asset_id}")
        indexed[asset_id] = record
    return indexed


def _asset_records(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if "asset_id" in value:
            yield value
            return
        for nested in value.values():
            yield from _asset_records(nested)
        return
    if isinstance(value, list | tuple):
        for nested in value:
            yield from _asset_records(nested)
