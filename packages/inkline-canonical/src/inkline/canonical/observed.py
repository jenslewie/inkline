from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.schema import ValidationError

OBSERVED_SCHEMA_NAME = "inkline_observed_document"
OBSERVED_SCHEMA_VERSION = "0.1-shadow"

OBSERVATION_KINDS = {
    "text_region",
    "image_region",
    "table_region",
    "page_marker",
    "footnote_region",
}

OBSERVATION_ROLE_HINTS = {
    "body_text",
    "title_text",
    "list_text",
    "reference_text",
    "footnote_text",
    "caption_text",
    "toc_text",
    "page_number",
    "header",
    "footer",
    "unknown",
}

REQUIRED_TOP_LEVEL_FIELDS = {
    "metadata": dict,
    "pages": list,
    "observations": list,
    "assets": dict,
}

REQUIRED_METADATA_FIELDS = (
    "schema_name",
    "schema_version",
    "doc_id",
    "title",
    "language",
    "source_file",
    "parser_name",
    "parser_mode",
)

REQUIRED_PAGE_FIELDS = {
    "page": int,
    "width": int | float,
    "height": int | float,
    "attrs": dict,
}

REQUIRED_OBSERVATION_FIELDS = {
    "observation_id": str,
    "kind": str,
    "text": str,
    "page": int,
    "spans": list,
    "role_hint": str,
    "attrs": dict,
    "parser_payload": dict,
}

REQUIRED_NULLABLE_OBSERVATION_FIELDS = ("bbox",)


def make_observed_document(
    metadata: dict[str, Any],
    pages: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    assets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = {
        "metadata": {**metadata},
        "pages": deepcopy(pages),
        "observations": deepcopy(observations),
        "assets": deepcopy(assets) if assets is not None else {},
    }
    document["metadata"].setdefault("schema_name", OBSERVED_SCHEMA_NAME)
    document["metadata"].setdefault("schema_version", OBSERVED_SCHEMA_VERSION)
    validate_observed_document(document)
    return document


def make_observed_page(
    page: int,
    *,
    width: float,
    height: float,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "page": page,
        "width": width,
        "height": height,
        "attrs": deepcopy(attrs) if attrs is not None else {},
    }


def make_observation(
    observation_id: str,
    kind: str,
    *,
    text: str = "",
    page: int,
    bbox: list[float] | None = None,
    spans: list[dict[str, Any]] | None = None,
    role_hint: str = "unknown",
    attrs: dict[str, Any] | None = None,
    parser_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "kind": kind,
        "text": text,
        "page": page,
        "bbox": deepcopy(bbox),
        "spans": deepcopy(spans) if spans is not None else [],
        "role_hint": role_hint,
        "attrs": deepcopy(attrs) if attrs is not None else {},
        "parser_payload": deepcopy(parser_payload) if parser_payload is not None else {},
    }


def validate_observed_document(document: dict[str, Any]) -> None:
    _validate_top_level(document)
    _validate_metadata(document["metadata"])
    pages = _validate_pages(document["pages"])
    _validate_observations(document["observations"], pages)


def _validate_top_level(document: dict[str, Any]) -> None:
    for field, expected_type in REQUIRED_TOP_LEVEL_FIELDS.items():
        value = document.get(field)
        if not isinstance(value, expected_type):
            raise ValidationError(f"{field} must be {expected_type.__name__}")


def _validate_metadata(metadata: dict[str, Any]) -> None:
    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata:
            raise ValidationError(f"metadata.{field} is required")
    if metadata.get("schema_name") != OBSERVED_SCHEMA_NAME:
        raise ValidationError(f"metadata.schema_name must be {OBSERVED_SCHEMA_NAME}")
    if metadata.get("schema_version") != OBSERVED_SCHEMA_VERSION:
        raise ValidationError(f"metadata.schema_version must be {OBSERVED_SCHEMA_VERSION}")


def _validate_pages(pages: list[dict[str, Any]]) -> set[int]:
    seen: set[int] = set()
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise ValidationError(f"pages[{index}] must be object")
        for field, expected_type in REQUIRED_PAGE_FIELDS.items():
            value = page.get(field)
            if not isinstance(value, expected_type):
                raise ValidationError(f"pages[{index}].{field} is invalid")
        page_number = page["page"]
        if page_number in seen:
            raise ValidationError(f"duplicate page: {page_number}")
        seen.add(page_number)
    return seen


def _validate_observations(
    observations: list[dict[str, Any]], pages: set[int]
) -> None:
    observation_ids: set[str] = set()
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValidationError(f"observations[{index}] must be object")
        for field, expected_type in REQUIRED_OBSERVATION_FIELDS.items():
            value = observation.get(field)
            if not isinstance(value, expected_type):
                raise ValidationError(f"observations[{index}].{field} is invalid")
        for field in REQUIRED_NULLABLE_OBSERVATION_FIELDS:
            if field not in observation:
                raise ValidationError(f"observations[{index}].{field} is required")
        observation_id = observation["observation_id"]
        if observation_id in observation_ids:
            raise ValidationError(f"duplicate observation_id: {observation_id}")
        observation_ids.add(observation_id)
        if observation["kind"] not in OBSERVATION_KINDS:
            raise ValidationError(f"observations[{index}].kind is invalid: {observation['kind']}")
        if observation["role_hint"] not in OBSERVATION_ROLE_HINTS:
            raise ValidationError(
                f"observations[{index}].role_hint is invalid: {observation['role_hint']}"
            )
        if observation["page"] not in pages:
            raise ValidationError(f"observations[{index}].page does not exist")
        _validate_bbox(observation["bbox"], index)


def _validate_bbox(bbox: Any, index: int) -> None:
    if bbox is None:
        return
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValidationError(f"observations[{index}].bbox must be null or four numbers")
    if not all(isinstance(value, int | float) for value in bbox):
        raise ValidationError(f"observations[{index}].bbox must be null or four numbers")
