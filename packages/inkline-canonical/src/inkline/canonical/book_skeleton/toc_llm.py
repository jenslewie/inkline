from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.book_skeleton.contract import BOOK_SKELETON_ENTRY_ROLES
from inkline.canonical.schema import ValidationError

LLM_TOC_ENTRY_REQUIRED_FIELDS = {
    "entry_index",
    "display_title",
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
            "display_title": _required_string(item, "display_title", index),
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
        "The attached TOC images, supplied in preceding messages, are in ascending physical PDF "
        "page order and appear in the same order as input toc_pages. Read every image from top to "
        "bottom before moving to the next image. Output entries in that same TOC reading order: "
        "every entry on an earlier image must appear before every entry on a later image.\n\n"
        "Return strict JSON only, with this shape:\n"
        "{\n"
        '  "toc_entries": [\n'
        "    {\n"
        '      "entry_index": 0,\n'
        '      "display_title": "",\n'
        '      "level": 1,\n'
        '      "parent_entry_index": null,\n'
        '      "role": "front_matter"\n'
        "    }\n"
        "  ],\n"
        '  "uncertain_entries": []\n'
        "}\n\n"
        "Field contract:\n"
        "- entry_index: integer starting at 0, continuous in TOC reading order.\n"
        "- display_title: complete TOC entry title as it should be displayed. Keep structural "
        "numbering or prefixes inside this field, for example '第一章 启示预言的传统', "
        "'专题1 阿玛尔那信札', or '附录1 关于人数的一个问题'.\n"
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
        "- Do not split display_title into raw_title, title, raw_label, or label.\n"
        "- Do not insert spaces between Chinese characters inside names or words in display_title. "
        "Use '第一章 楼兰：中亚的十字路口', not '第一章 楼 兰：中亚的十字路口'.\n"
        "- Preserve compact Chinese words in display_title. Use '缩写', '年表', and '致谢', "
        "not '缩 写', '年 表', or '致 谢'.\n"
        "- Preserve the numbering glyphs visible in the TOC. In particular, use decimal chapter "
        "numbers when the image shows decimal digits: Use '第1章', not '第Ⅰ章' or '第I章'.\n"
        "- Keep a single separator space between a structural prefix and the title when the TOC "
        "visually separates them. Use '第一章 楼兰：中亚的十字路口', not "
        "'第一章楼兰：中亚的十字路口'.\n"
        "- Use visual alignment and indentation for hierarchy. If a back_matter entry is visually "
        "aligned with top-level chapters or the conclusion, set level=1 and parent_entry_index=null. "
        "Do not make it a child of the final body entry merely because it follows the body.\n"
        "- Treat visual indentation as decisive for hierarchy. If an entry is visibly indented under "
        "the preceding nearest less-indented entry, make it that entry's child even when the semantic "
        "relationship is unclear.\n"
        "- Assign parent_entry_index only when the TOC visually indents the child under an earlier "
        "entry. Entries with the same left alignment must have the same level, even when adjacent "
        "entries look related as tables, lists, notes, sources, chronology, or other back matter.\n"
        "- Do not output selected_start_page, selected_page, candidate_start_pages, candidate_pages, "
        "printed_start_page, or printed page numbers.\n"
        "- Do not invent entries that are not visible in the TOC.\n"
        "- Do not emit a TOC page heading as a toc_entry. A page heading such as '目录' or "
        "'Contents' labels the TOC itself; emit only the book entries listed below it.\n"
        "- Do not split one wrapped TOC title into multiple entries.\n"
        "- A slash-separated run where every segment ends with a parenthesized decimal page number, "
        "such as A(191)/B(193) represents two TOC entries. Split every segment; use their visual "
        "indentation to assign level and parent_entry_index.\n"
        "- Do not merge two visually separate TOC entries unless they are clearly one title wrapped "
        "across lines.\n"
        "- Do not reorder or group TOC entries by role, title kind, or printed page number.\n"
        "- If the TOC contains body entries, an entry after a body entry in TOC reading order must "
        "not be classified as front_matter.\n"
        "- Use null, not an empty string, when parent_entry_index is absent.\n"
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
