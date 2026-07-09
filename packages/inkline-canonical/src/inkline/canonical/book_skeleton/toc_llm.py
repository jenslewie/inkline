from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.book_skeleton.contract import BOOK_SKELETON_ENTRY_ROLES
from inkline.canonical.schema import ValidationError

LLM_TOC_ENTRY_REQUIRED_FIELDS = {
    "entry_index",
    "raw_title",
    "title",
    "display_title",
    "raw_label",
    "label",
    "level",
    "parent_entry_index",
    "role",
}


def normalize_llm_toc_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError(f"llm toc entry {index} must be object")
        _validate_required_fields(item, index)
        entry = {
            "entry_index": _entry_index(item, index),
            "raw_title": _required_string(item, "raw_title", index),
            "title": _required_string(item, "title", index),
            "display_title": _required_string(item, "display_title", index),
            "raw_label": _optional_string(item, "raw_label", index),
            "label": _optional_string(item, "label", index),
            "level": _level(item, index),
            "parent_entry_index": _parent_entry_index(item, index),
            "role": _role(item, index),
            "candidate_start_pages": [],
            "selected_start_page": None,
            "attrs": deepcopy(item.get("attrs") or {}),
        }
        entries.append(entry)
    _validate_parent_refs(entries)
    return entries


def book_skeleton_toc_llm_prompt(input_data: dict[str, Any]) -> str:
    return (
        "You extract a book table of contents into a strict JSON contract.\n"
        "Read the TOC visual structure carefully: indentation, numbering, wrapping, and grouping "
        "are evidence for level and parent_entry_index.\n\n"
        "Return strict JSON only, with this shape:\n"
        "{\n"
        '  "toc_entries": [\n'
        "    {\n"
        '      "entry_index": 0,\n'
        '      "raw_title": "",\n'
        '      "title": "",\n'
        '      "display_title": "",\n'
        '      "raw_label": null,\n'
        '      "label": null,\n'
        '      "level": 1,\n'
        '      "parent_entry_index": null,\n'
        '      "role": "front_matter"\n'
        "    }\n"
        "  ],\n"
        '  "uncertain_entries": []\n'
        "}\n\n"
        "Field contract:\n"
        "- entry_index: integer starting at 0, continuous in TOC reading order.\n"
        "- raw_title: original visible TOC title text, preserving visual/OCR spacing when useful.\n"
        "- title: normalized title without structural label. For '第一章 启示预言的传统', "
        "title is '启示预言的传统'.\n"
        "- display_title: complete display title, usually label plus title.\n"
        "- raw_label: original visible structural label such as '第 一 章', '附 录', or null.\n"
        "- label: normalized structural label such as '第一章', '附录', '专题1', or null.\n"
        "- level: TOC hierarchy level starts at 1. 1 means top-level; 2 means child of a "
        "level-1 entry; 3 means child of a level-2 entry. Never start at 0.\n"
        "- parent_entry_index: null for level-1 entries; otherwise the entry_index of the "
        "nearest parent entry that appears earlier in reading order.\n"
        "- role: one of front_matter, body, back_matter, unknown.\n\n"
        "Role definitions:\n"
        "- front_matter: content before the main body, such as foreword, preface, "
        "acknowledgements, dedication, editorial notes, or introductory front matter.\n"
        "- body: the main chapters and the conclusion when it closes the main argument.\n"
        "- back_matter: content after the main body, such as appendix, notes, bibliography, "
        "references, further reading, chronology, index, publisher afterword, or copyright pages.\n"
        "- unknown: use only when the TOC visual evidence is insufficient. Do not guess.\n\n"
        "Hard rules:\n"
        "- Do not output physical PDF page numbers.\n"
        "- Do not output selected_start_page, selected_page, candidate_start_pages, candidate_pages, "
        "printed_start_page, or printed page numbers.\n"
        "- Do not invent entries that are not visible in the TOC.\n"
        "- Do not split one wrapped TOC title into multiple entries.\n"
        "- Do not merge two visually separate TOC entries unless they are clearly one title wrapped "
        "across lines.\n"
        "- Use null, not an empty string, when label or parent_entry_index is absent.\n"
        "- All required fields must be present on every entry.\n\n"
        f"Input JSON:\n{_json_dumps(input_data)}"
    )


def _validate_required_fields(item: dict[str, Any], index: int) -> None:
    missing = sorted(LLM_TOC_ENTRY_REQUIRED_FIELDS - set(item))
    if missing:
        raise ValidationError(f"llm toc entry {index} missing fields: {', '.join(missing)}")


def _entry_index(item: dict[str, Any], expected_index: int) -> int:
    value = item.get("entry_index")
    if not isinstance(value, int) or value != expected_index:
        raise ValidationError(f"llm toc entry {expected_index}.entry_index must equal list index")
    return value


def _required_string(item: dict[str, Any], field: str, index: int) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"llm toc entry {index}.{field} must be non-empty string")
    return value.strip()


def _optional_string(item: dict[str, Any], field: str, index: int) -> str | None:
    value = item.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"llm toc entry {index}.{field} must be string or null")
    value = value.strip()
    return value or None


def _level(item: dict[str, Any], index: int) -> int:
    value = item.get("level")
    if not isinstance(value, int) or value < 1:
        raise ValidationError(f"llm toc entry {index}.level must be integer starting at 1")
    return value


def _parent_entry_index(item: dict[str, Any], index: int) -> int | None:
    value = item.get("parent_entry_index")
    if value is None:
        return None
    if not isinstance(value, int) or value >= index or value < 0:
        raise ValidationError(
            f"llm toc entry {index}.parent_entry_index must point to an earlier entry"
        )
    return value


def _role(item: dict[str, Any], index: int) -> str:
    value = item.get("role")
    if value not in BOOK_SKELETON_ENTRY_ROLES:
        raise ValidationError(f"llm toc entry {index}.role is invalid: {value}")
    return str(value)


def _validate_parent_refs(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        index = int(entry["entry_index"])
        level = int(entry["level"])
        parent_index = entry["parent_entry_index"]
        if level == 1 and parent_index is not None:
            raise ValidationError(f"llm toc entry {index}.parent_entry_index must be null at level 1")
        if level > 1 and parent_index is None:
            raise ValidationError(f"llm toc entry {index}.parent_entry_index is required below level 1")
        if parent_index is not None and int(entries[parent_index]["level"]) >= level:
            raise ValidationError(
                f"llm toc entry {index}.parent_entry_index must point to a lower-level parent"
            )


def _json_dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2)
