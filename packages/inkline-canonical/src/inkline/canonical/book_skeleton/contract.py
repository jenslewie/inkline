from __future__ import annotations

from typing import Any

BOOK_SKELETON_SCHEMA_NAME = "inkline_book_skeleton"
BOOK_SKELETON_SCHEMA_VERSION = "0.1-shadow"

BOOK_SKELETON_ENTRY_ROLES = {"front_matter", "body", "back_matter", "unknown"}
BOOK_SKELETON_ENTRY_ROLE_ORDER = {"front_matter": 0, "body": 1, "back_matter": 2}

REQUIRED_TOP_LEVEL_FIELDS: dict[str, type[Any]] = {
    "metadata": dict,
    "toc_pages": list,
    "toc_entries": list,
    "boundaries": dict,
    "llm": dict,
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
    "shadow_source_schema_name",
    "shadow_source_schema_version",
)

REQUIRED_ENTRY_FIELDS: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "entry_index": int,
    "display_title": str,
    "level": int,
    "parent_entry_index": (int, type(None)),
    "role": str,
    "candidate_start_pages": list,
    "selected_start_page": (int, type(None)),
    "attrs": dict,
}

REQUIRED_BOUNDARY_FIELDS = {
    "first_body_entry_index",
    "first_body_page",
    "last_body_entry_index",
    "last_body_page",
    "first_back_matter_entry_index",
    "first_back_matter_page",
}
