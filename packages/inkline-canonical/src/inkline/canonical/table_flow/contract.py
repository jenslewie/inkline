from __future__ import annotations

from typing import Any

TABLE_FLOW_SCHEMA_NAME = "inkline_table_flow"
TABLE_FLOW_SCHEMA_VERSION = "0.1-shadow"

REQUIRED_TOP_LEVEL_FIELDS: dict[str, type[Any]] = {
    "metadata": dict,
    "tables": list,
    "unresolved_table_observation_runs": list,
    "excluded_table_observation_runs": list,
}

REQUIRED_TABLE_FIELDS: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "table_id": str,
    "html": str,
    "text": str,
    "pages": list,
    "spans": list,
    "observation_ids": list,
    "primary_observation_id": str,
    "caption_observation_ids": list,
    "caption_texts": list,
    "footnote_texts": list,
    "attrs": dict,
}
