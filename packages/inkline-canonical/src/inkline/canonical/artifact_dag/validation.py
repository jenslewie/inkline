from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from inkline.canonical.schema import ValidationError

CONFIDENCES = {"high", "medium", "low"}
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_exact_fields(value: Any, fields: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(f"{path} has invalid fields")
    return value


def validate_metadata(
    value: Any, *, schema_name: str, schema_version: str, path: str
) -> dict[str, Any]:
    metadata = validate_exact_fields(
        value, {"schema_name", "schema_version", "doc_id"}, path
    )
    if metadata["schema_name"] != schema_name:
        raise ValidationError(f"{path}.schema_name is invalid")
    if metadata["schema_version"] != schema_version:
        raise ValidationError(f"{path}.schema_version is invalid")
    validate_non_empty_string(metadata["doc_id"], f"{path}.doc_id")
    return metadata


def validate_non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{path} must be non-empty string")
    return value


def validate_nullable_string(value: Any, path: str) -> str | None:
    if value is not None:
        return validate_non_empty_string(value, path)
    return None


def validate_id_list(value: Any, path: str, *, required: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (required and not value)
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError(f"{path} must contain unique non-empty ids")
    return value


def validate_pages(value: Any, path: str, *, required: bool = False) -> list[int]:
    if (
        not isinstance(value, list)
        or (required and not value)
        or not all(type(page) is int and page > 0 for page in value)
        or value != sorted(set(value))
    ):
        raise ValidationError(f"{path} must contain ordered unique positive pages")
    return value


def validate_ranges(value: Any, path: str, *, required: bool = False) -> list[list[int]]:
    if not isinstance(value, list) or (required and not value):
        raise ValidationError(f"{path} must contain page ranges")
    previous_end = 0
    for index, page_range in enumerate(value):
        if (
            not isinstance(page_range, list)
            or len(page_range) != 2
            or not all(type(page) is int and page > 0 for page in page_range)
            or page_range[0] > page_range[1]
            or page_range[0] <= previous_end
        ):
            raise ValidationError(f"{path}[{index}] is invalid")
        previous_end = page_range[1]
    return value


def validate_bbox(value: Any, path: str, *, nullable: bool = False) -> list[float] | None:
    if value is None and nullable:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(type(coordinate) in {int, float} for coordinate in value)
        or float(value[0]) > float(value[2])
        or float(value[1]) > float(value[3])
    ):
        raise ValidationError(f"{path} is invalid")
    return [float(coordinate) for coordinate in value]


def validate_choice(value: Any, choices: set[str], path: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValidationError(f"{path} is invalid")
    return value


def validate_confidence(value: Any, path: str) -> str:
    return validate_choice(value, CONFIDENCES, path)


def validate_ordered_ids(
    records: Any, *, id_field: str, prefix: str, path: str
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        raise ValidationError(f"{path} must be list")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValidationError(f"{path}[{index}] must be object")
        if record.get(id_field) != f"{prefix}{index + 1:06d}":
            raise ValidationError(f"{path} ids must be ordered contiguous {prefix} ids")
    return records


def validate_string_choices(value: Any, choices: set[str], path: str) -> list[str]:
    values = validate_id_list(value, path, required=True)
    if not set(values) <= choices:
        raise ValidationError(f"{path} contains invalid value")
    return values


def validate_doc_ids(expected: str, sources: Mapping[str, Any]) -> None:
    for name, source in sources.items():
        metadata = source.get("metadata") if isinstance(source, dict) else None
        actual = metadata.get("doc_id") if isinstance(metadata, dict) else None
        if actual != expected:
            raise ValidationError(f"{name} doc_id differs from target artifact")


def validate_reason(value: Any, path: str) -> str:
    reason = validate_non_empty_string(value, path)
    if not _IDENTIFIER.fullmatch(reason):
        raise ValidationError(f"{path} must be a stable identifier")
    return reason
