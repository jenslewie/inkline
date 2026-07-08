from __future__ import annotations

import json
import re
from collections import Counter
from copy import deepcopy
from typing import Any

from inkline.canonical.observed import validate_observed_document
from inkline.canonical.schema import ValidationError

BOOK_SKELETON_SCHEMA_NAME = "inkline_book_skeleton"
BOOK_SKELETON_SCHEMA_VERSION = "0.1-shadow"

BOOK_SKELETON_ENTRY_ROLES = {"front_matter", "body", "back_matter", "unknown"}
BOOK_SKELETON_ENTRY_ROLE_ORDER = {"front_matter": 0, "body": 1, "back_matter": 2}

TEXT_KINDS = {"text_region", "footnote_region", "page_marker"}
VISUAL_TITLE_KINDS = {"image_region", "table_region"}
TITLE_LOCATION_ROLE_HINTS = {"title_text"}
TITLE_LOCATION_EXCLUDED_ROLE_HINTS = {
    "footnote_text",
    "reference_text",
    "page_number",
    "header",
    "footer",
    "caption_text",
}
TOC_ENTRY_RE = re.compile(
    r"^\s*(?P<title>.+?)\s*(?:[/／.·•…\-\s]+)?(?P<page>[ivxlcdmIVXLCDM\d]+)\s*$"
)
TOC_ENTRY_PART_RE = re.compile(
    r"\s*(?P<title>.+?)\s+(?P<page>[ivxlcdmIVXLCDM\d]+)(?=\s+\S|$)"
)
TOC_PART_LABEL_RE = re.compile(r"^(?P<label>第[一二三四五六七八九十百千万\d]+部分)\s+(?P<title>.+)$")
TOC_CHAPTER_LABEL_RE = re.compile(r"^(?P<label>第[一二三四五六七八九十百千万\d]+[章节])\s+(?P<title>.+)$")
TOC_TOPIC_LABEL_RE = re.compile(r"^(?P<label>专题\s*\d+)\s+(?P<title>.+)$")
TOC_APPENDIX_NUMBER_LABEL_RE = re.compile(r"^(?P<label>附录\s*\d+)\s+(?P<title>.+)$")
TOC_APPENDIX_LABEL_RE = re.compile(r"^(?P<label>附录)\s+(?P<title>.+)$")
TOC_NUMBER_LABEL_RE = re.compile(r"^(?P<label>[0-9]+|[IVXLCDM]+|[ivxlcdm]+)\s+(?P<title>.+)$")
BODY_TITLE_RE = re.compile(r"^(?:第[一二三四五六七八九十百千万\d]+(?:章节|部分|[章节部卷篇])|序章)")
NUMERIC_BODY_TITLE_RE = re.compile(r"^\d{1,3}\s+\S")
GENERIC_TITLES_REQUIRING_TITLE_HINT = {"注释", "索引", "参考文献", "参考书目"}
TOP_LEVEL_UNLABELED_TITLES = {
    "前言",
    "序言",
    "引言",
    "致谢",
    "说明",
    "结论",
    "注释",
    "参考书目",
    "参考文献",
    "索引",
    "出版后记",
    "扩展阅读",
    "大事年表",
    "古代地中海各文明年代图表",
}

REQUIRED_TOP_LEVEL_FIELDS = {
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

REQUIRED_ENTRY_FIELDS = {
    "entry_index": int,
    "raw_title": str,
    "title": str,
    "display_title": str,
    "raw_label": str | type(None),
    "label": str | type(None),
    "level": int,
    "parent_entry_index": int | type(None),
    "role": str,
    "candidate_start_pages": list,
    "selected_start_page": int | type(None),
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


def build_book_skeleton_from_observed(
    document: dict[str, Any],
    *,
    llm_classification: dict[str, Any] | None = None,
    llm_model: str | None = None,
    llm_source: str | None = None,
) -> dict[str, Any]:
    validate_observed_document(document)
    page_records = _page_records(document)
    toc_pages = _detect_toc_pages(page_records)
    toc_text = "\n".join(_observed_page_text(document, page) for page in toc_pages)
    entries = _parse_toc_entries(toc_text)
    _infer_toc_levels(entries)
    _assign_toc_hierarchy(entries)
    for entry in entries:
        candidates = _locate_toc_entry_pages(page_records, entry, exclude_pages=toc_pages)
        entry["candidate_start_pages"] = candidates
        entry["selected_start_page"] = None
    _apply_structural_roles(entries)
    llm_summary = _apply_llm_classification(
        entries,
        llm_classification=llm_classification,
        llm_model=llm_model,
        llm_source=llm_source,
    )
    _apply_role_level_guardrails(entries)
    _assign_toc_hierarchy(entries)
    _select_monotonic_start_pages(entries)
    _prune_candidate_start_pages_to_toc_intervals(entries)
    skeleton = {
        "metadata": _metadata(document),
        "toc_pages": toc_pages,
        "toc_entries": entries,
        "boundaries": _boundaries(entries, llm_classification=llm_classification),
        "llm": llm_summary,
    }
    validate_book_skeleton(skeleton)
    return skeleton


def build_book_skeleton_toc_llm_input(document: dict[str, Any]) -> dict[str, Any]:
    validate_observed_document(document)
    page_records = _page_records(document)
    toc_pages = _detect_toc_pages(page_records)
    toc_text = "\n".join(_observed_page_text(document, page) for page in toc_pages)
    entries = _parse_toc_entries(toc_text)
    _infer_toc_levels(entries)
    _assign_toc_hierarchy(entries)
    toc_entries = []
    for entry in entries:
        toc_entries.append(
            {
                "entry_index": entry["entry_index"],
                "title": entry["title"],
                "display_title": entry["display_title"],
                "raw_label": entry["raw_label"],
                "label": entry["label"],
                "level": entry["level"],
                "parent_entry_index": entry["parent_entry_index"],
                "candidate_start_pages": _locate_toc_entry_pages(
                    page_records, entry, exclude_pages=toc_pages
                )[:5],
            }
        )
    return {
        "mode": "toc_llm",
        "metadata": _metadata(document),
        "page_count": len(document["pages"]),
        "toc_pages": toc_pages,
        "toc_entries": toc_entries,
        "expected_output": {
            "entry_roles": [
                {"entry_index": 0, "role": "front_matter|body|back_matter|unknown"}
            ],
            "first_body_entry_index": 0,
            "last_body_entry_index": 0,
            "first_back_matter_entry_index": None,
            "uncertain_entries": [{"entry_index": 0, "title": "", "reason": ""}],
        },
    }


def book_skeleton_toc_llm_prompt(input_data: dict[str, Any]) -> str:
    return (
        "You classify a book skeleton from table-of-contents entries.\n"
        "Use entry_index, display_title, label, level, and title to decide entry roles. "
        "Do not infer or output physical "
        "PDF page numbers; candidate_start_pages are rule-layer evidence only.\n\n"
        "Definitions:\n"
        "- front_matter: content before the main body, such as foreword, preface, acknowledgements, "
        "dedication, editorial notes, or introductory front matter.\n"
        "- body: the main chapters and conclusion of the book.\n"
        "- back_matter: content after the main body, including appendix, notes, bibliography, "
        "references, further reading, chronology, index, publisher afterword, and copyright pages.\n\n"
        "Return strict JSON matching expected_output. Every toc_entries item should have one "
        "entry_roles item. Use null when there is no back matter.\n\n"
        f"Input JSON:\n{_json_dumps(input_data)}"
    )


def validate_book_skeleton(skeleton: dict[str, Any]) -> None:
    for field, expected_type in REQUIRED_TOP_LEVEL_FIELDS.items():
        value = skeleton.get(field)
        if not isinstance(value, expected_type):
            raise ValidationError(f"{field} must be {expected_type.__name__}")
    _validate_metadata(skeleton["metadata"])
    _validate_toc_pages(skeleton["toc_pages"])
    _validate_toc_entries(skeleton["toc_entries"])
    _validate_boundaries(skeleton["boundaries"], len(skeleton["toc_entries"]))
    _validate_llm(skeleton["llm"])


def audit_book_skeleton(skeleton: dict[str, Any]) -> dict[str, Any]:
    entries = [entry for entry in skeleton.get("toc_entries", []) if isinstance(entry, dict)]
    issues = _audit_toc_entry_issues(entries)
    role_counts = Counter(str(entry.get("role") or "") for entry in entries)
    located_count = sum(
        1 for entry in entries if isinstance(entry.get("selected_start_page"), int)
    )
    label_ocr_correction_count = sum(
        1
        for entry in entries
        if isinstance(entry.get("attrs"), dict) and "label_correction" in entry["attrs"]
    )
    return {
        "summary": {
            "toc_entry_count": len(entries),
            "located_entry_count": located_count,
            "unlocated_entry_count": len(entries) - located_count,
            "label_ocr_correction_count": label_ocr_correction_count,
            "issue_count": len(issues),
            "role_counts": dict(role_counts),
            "boundaries": deepcopy(skeleton.get("boundaries") or {}),
        },
        "issues": issues,
    }


def _metadata(document: dict[str, Any]) -> dict[str, Any]:
    source = document["metadata"]
    return {
        "schema_name": BOOK_SKELETON_SCHEMA_NAME,
        "schema_version": BOOK_SKELETON_SCHEMA_VERSION,
        "doc_id": str(source.get("doc_id") or ""),
        "title": str(source.get("title") or ""),
        "language": str(source.get("language") or ""),
        "source_file": str(source.get("source_file") or ""),
        "parser_name": str(source.get("parser_name") or ""),
        "parser_mode": str(source.get("parser_mode") or ""),
        "shadow_source_schema_name": str(source.get("schema_name") or ""),
        "shadow_source_schema_version": str(source.get("schema_version") or ""),
    }


def _page_records(document: dict[str, Any]) -> list[dict[str, Any]]:
    observations_by_page: dict[int, list[dict[str, Any]]] = {}
    for observation in document["observations"]:
        observations_by_page.setdefault(int(observation["page"]), []).append(observation)
    records = []
    for page in sorted(document["pages"], key=lambda item: int(item["page"])):
        page_number = int(page["page"])
        observations = observations_by_page.get(page_number, [])
        text_observations = [
            observation for observation in observations if observation.get("kind") in TEXT_KINDS
        ]
        title_location_observations = [
            observation
            for observation in text_observations
            if _is_title_location_observation(observation)
        ]
        visual_title_observations = [
            observation
            for observation in observations
            if observation.get("kind") in VISUAL_TITLE_KINDS
            and str(observation.get("text") or "").strip()
        ]
        role_hint_counts = Counter(str(observation.get("role_hint") or "") for observation in observations)
        records.append(
            {
                "page": page_number,
                "role_hint_counts": dict(role_hint_counts),
                "text": _page_text(text_observations),
                "content_text": _page_text(
                    [
                        *_title_context_observations(
                            text_observations, title_location_observations
                        ),
                        *visual_title_observations,
                    ]
                ),
                "title_text": _page_text(
                    [
                        observation
                        for observation in text_observations
                        if observation.get("role_hint") == "title_text"
                    ]
                ),
                "has_toc_hint": any(
                    observation.get("role_hint") == "toc_text"
                    for observation in text_observations
                ),
            }
        )
    return records


def _title_context_observations(
    text_observations: list[dict[str, Any]],
    title_location_observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not title_location_observations:
        return []
    title_location_ids = {id(observation) for observation in title_location_observations}
    context = []
    for observation in text_observations:
        role_hint = str(observation.get("role_hint") or "")
        text = str(observation.get("text") or "").strip()
        if id(observation) in title_location_ids or (
            role_hint in {"body_text", "list_text"} and _is_short_title_context_line(text)
        ):
            context.append(observation)
    return context


def _is_short_title_context_line(text: str) -> bool:
    return 0 < len(_normalize_title(text)) <= 36


def _is_title_location_observation(observation: dict[str, Any]) -> bool:
    role_hint = str(observation.get("role_hint") or "")
    if observation.get("kind") == "page_marker":
        return False
    if role_hint in TITLE_LOCATION_EXCLUDED_ROLE_HINTS:
        return False
    return role_hint in TITLE_LOCATION_ROLE_HINTS


def _page_text(observations: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(observation.get("text") or "").strip()
        for observation in observations
        if str(observation.get("text") or "").strip()
    )


def _detect_toc_pages(page_records: list[dict[str, Any]]) -> list[int]:
    pages: set[int] = set()
    for record in page_records:
        text = str(record.get("text") or "")
        toc_like_lines = _toc_like_line_count(text)
        has_toc_title = "目录" in text[:120]
        if (record.get("has_toc_hint") and (has_toc_title or toc_like_lines >= 3)) or (
            has_toc_title and toc_like_lines >= 2
        ):
            pages.add(int(record["page"]))
    if not pages:
        return []
    records_by_page = {int(record["page"]): record for record in page_records}
    for page in sorted(pages):
        next_page = page + 1
        while next_page in records_by_page:
            text = str(records_by_page[next_page].get("text") or "")
            if _toc_like_line_count(text) < 2:
                break
            pages.add(next_page)
            next_page += 1
    return sorted(pages)


def _toc_like_line_count(text: str) -> int:
    return sum(
        len(_parse_toc_line_entries(line.strip()))
        for line in text.splitlines()
    )


def _observed_page_text(document: dict[str, Any], page_number: int) -> str:
    return "\n".join(
        str(observation.get("text") or "").strip()
        for observation in document["observations"]
        if int(observation.get("page") or 0) == page_number
        and observation.get("kind") in TEXT_KINDS
        and str(observation.get("text") or "").strip()
    )


def _parse_toc_entries(text: str) -> list[dict[str, Any]]:
    entries = []
    for line in _logical_toc_lines(text):
        if line == "目录":
            continue
        for item in _parse_toc_line_entries(line):
            entries.append(_toc_entry(len(entries), item))
    return entries


def _logical_toc_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    logical_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line == "目录":
            logical_lines.append(line)
            index += 1
            continue
        if _is_toc_running_header_line(line):
            index += 1
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if next_line and _is_toc_page_token(next_line) and not _parse_toc_line_entries(line):
            logical_lines.append(f"{line} {next_line}")
            index += 2
            continue
        if next_line and _should_join_toc_continuation(line, next_line):
            logical_lines.append(_join_toc_continuation(line, next_line))
            index += 2
            continue
        logical_lines.append(line)
        index += 1
    return logical_lines


def _is_toc_page_token(line: str) -> bool:
    return re.fullmatch(r"[ivxlcdmIVXLCDM\d]+", line.strip()) is not None


def _is_toc_running_header_line(line: str) -> bool:
    text = line.strip()
    if re.fullmatch(r"(?:目录\s*)?[/／]?\s*[ivxlcdmIVXLCDM\d]+\s*(?:[/／]\s*)?", text):
        return True
    if re.match(r"^[/／]\s*\S+", text):
        return True
    return re.match(r"^[ivxlcdm]{2,}\s+\S+", text) is not None and TOC_ENTRY_RE.match(text) is None


def _should_join_toc_continuation(line: str, next_line: str) -> bool:
    if _parse_toc_line_entries(line):
        return False
    if _looks_like_standalone_toc_heading(line):
        return False
    return bool(_parse_toc_line_entries(next_line))


def _join_toc_continuation(line: str, next_line: str) -> str:
    if _ends_with_cjk(line) and _starts_with_cjk(next_line):
        return f"{line}{next_line}"
    return f"{line} {next_line}"


def _ends_with_cjk(text: str) -> bool:
    return re.search(r"[\u3400-\u9fff]$", text.strip()) is not None


def _starts_with_cjk(text: str) -> bool:
    return re.match(r"^[\u3400-\u9fff]", text.strip()) is not None


def _looks_like_standalone_toc_heading(line: str) -> bool:
    return TOC_PART_LABEL_RE.match(line) is not None


def _parse_toc_line_entries(line: str) -> list[dict[str, str | None]]:
    normalized_line = _normalize_toc_line(line)
    matches = list(TOC_ENTRY_PART_RE.finditer(normalized_line))
    if not matches and _looks_like_standalone_toc_heading(normalized_line):
        return [_toc_entry_parts(normalized_line)]
    if _should_parse_as_single_toc_entry(normalized_line, matches):
        match = TOC_ENTRY_RE.match(normalized_line)
        if match is None:
            return []
        title = _clean_toc_title(match.group("title"))
        if not title or _is_noise_toc_title(title):
            return []
        return [_toc_entry_parts(title)]
    items = []
    raw_items = [
        {
            "title": _clean_toc_title(match.group("title")),
            "page": match.group("page"),
        }
        for match in matches
    ]
    _recover_glued_numeric_labels(raw_items)
    for raw_item in raw_items:
        title = raw_item["title"]
        if title and not _is_noise_toc_title(title):
            items.append(_toc_entry_parts(title))
    return items


def _recover_glued_numeric_labels(items: list[dict[str, str]]) -> None:
    for index in range(len(items) - 1):
        current = _toc_entry_parts(items[index]["title"])
        next_item = items[index + 1]
        next_parts = _toc_entry_parts(next_item["title"])
        if next_parts["label"] is not None:
            continue
        expected_label = _next_numeric_label(current["label"])
        if expected_label is None:
            continue
        page_token = items[index]["page"]
        suffix = _expected_label_suffix(page_token, expected_label)
        if suffix is None:
            continue
        next_item["title"] = f"{expected_label} {next_item['title']}"
        items[index]["page"] = page_token[: -len(suffix)]


def _expected_label_suffix(page_token: str, expected_label: str) -> str | None:
    if len(page_token) <= len(expected_label):
        return None
    if page_token.endswith(expected_label):
        return expected_label
    ocr_suffix = expected_label.replace("1", "I")
    if ocr_suffix != expected_label and len(page_token) > len(ocr_suffix) and page_token.endswith(ocr_suffix):
        return ocr_suffix
    return None


def _next_numeric_label(label: Any) -> str | None:
    if not isinstance(label, str) or not label.isdigit():
        return None
    return str(int(label) + 1)


def _should_parse_as_single_toc_entry(line: str, matches: list[re.Match[str]]) -> bool:
    if len(matches) <= 1:
        return True
    whole_line_match = TOC_ENTRY_RE.match(line)
    if whole_line_match is not None:
        title = _clean_toc_title(whole_line_match.group("title"))
        if _has_non_numeric_toc_label(title):
            return True
    first = matches[0]
    title = _clean_toc_title(first.group("title"))
    page_token = first.group("page")
    return title in {"附录", "Appendix", "appendix"} and len(page_token) == 1


def _has_non_numeric_toc_label(title: str) -> bool:
    return any(
        pattern.match(title) is not None
        for pattern in (
            TOC_PART_LABEL_RE,
            TOC_CHAPTER_LABEL_RE,
            TOC_TOPIC_LABEL_RE,
            TOC_APPENDIX_NUMBER_LABEL_RE,
            TOC_APPENDIX_LABEL_RE,
        )
    )


def _toc_entry_parts(raw_title: str) -> dict[str, Any]:
    raw_label, label, title, level, attrs = _split_toc_label(raw_title)
    display_title = f"{label} {title}" if label else title
    return {
        "raw_title": raw_title,
        "title": title,
        "display_title": display_title,
        "raw_label": raw_label,
        "label": label,
        "level": level,
        "attrs": attrs,
    }


def _split_toc_label(raw_title: str) -> tuple[str | None, str | None, str, int, dict[str, Any]]:
    for pattern, level in (
        (TOC_PART_LABEL_RE, 1),
        (TOC_CHAPTER_LABEL_RE, 1),
        (TOC_TOPIC_LABEL_RE, 1),
        (TOC_APPENDIX_NUMBER_LABEL_RE, 1),
        (TOC_APPENDIX_LABEL_RE, 1),
        (TOC_NUMBER_LABEL_RE, 2),
    ):
        match = pattern.match(raw_title)
        if match is None:
            continue
        raw_label = match.group("label")
        label, attrs = _normalize_toc_label(raw_label)
        return raw_label, label, match.group("title").strip(), level, attrs
    return None, None, raw_title, 1, {}


def _normalize_toc_label(raw_label: str) -> tuple[str, dict[str, Any]]:
    normalized_raw_label = re.sub(r"\s+", "", raw_label)
    if raw_label == "I":
        return (
            "1",
            {
                "label_correction": {
                    "from": raw_label,
                    "to": "1",
                    "reason": "ocr_roman_i_in_numeric_toc",
                }
            },
        )
    return normalized_raw_label, {}


def _infer_toc_levels(entries: list[dict[str, Any]]) -> None:
    has_parts = any(_is_part_entry(entry) for entry in entries)
    seen_chapter = False
    for entry in entries:
        if _is_part_entry(entry):
            entry["level"] = 1
            continue
        if _is_chapter_entry(entry):
            entry["level"] = 2 if has_parts else 1
            seen_chapter = True
            continue
        if _is_topic_entry(entry) or _is_appendix_entry(entry):
            entry["level"] = 1
            continue
        if entry.get("label") is not None:
            continue
        title = str(entry.get("title") or "")
        if _is_top_level_unlabeled_title(title):
            entry["level"] = 1
        elif seen_chapter:
            entry["level"] = 2
        else:
            entry["level"] = 1


def _is_part_entry(entry: dict[str, Any]) -> bool:
    label = str(entry.get("label") or "")
    return TOC_PART_LABEL_RE.match(f"{label} x") is not None


def _is_chapter_entry(entry: dict[str, Any]) -> bool:
    label = str(entry.get("label") or "")
    return TOC_CHAPTER_LABEL_RE.match(f"{label} x") is not None


def _is_topic_entry(entry: dict[str, Any]) -> bool:
    label = str(entry.get("label") or "")
    return label.startswith("专题") and label[2:].isdigit()


def _is_appendix_entry(entry: dict[str, Any]) -> bool:
    label = str(entry.get("label") or "")
    return label == "附录" or (label.startswith("附录") and label[2:].isdigit())


def _is_top_level_unlabeled_title(title: str) -> bool:
    stripped = title.strip()
    if stripped in TOP_LEVEL_UNLABELED_TITLES:
        return True
    return any(
        stripped.startswith(prefix)
        for prefix in (
            "结论",
            "附录",
            "注释",
            "参考书目",
            "参考文献",
            "索引",
            "译后记",
            "出版后记",
            "扩展阅读",
            "大事年表",
        )
    )


def _assign_toc_hierarchy(entries: list[dict[str, Any]]) -> None:
    stack_by_level: dict[int, int] = {}
    for entry in entries:
        level = int(entry["level"])
        parent_level = max((candidate for candidate in stack_by_level if candidate < level), default=None)
        entry["parent_entry_index"] = stack_by_level[parent_level] if parent_level is not None else None
        if _is_non_parentable_top_level_entry(entry):
            continue
        stack_by_level[level] = int(entry["entry_index"])
        for existing_level in list(stack_by_level):
            if existing_level > level:
                del stack_by_level[existing_level]


def _is_non_parentable_top_level_entry(entry: dict[str, Any]) -> bool:
    if int(entry.get("level") or 0) != 1:
        return False
    if entry.get("label") is not None:
        return False
    return _is_top_level_unlabeled_title(str(entry.get("title") or ""))


def _apply_role_level_guardrails(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        if entry.get("label") is None and entry.get("role") in {"front_matter", "back_matter"}:
            entry["level"] = 1
            entry["parent_entry_index"] = None
        if _is_top_level_unlabeled_title(str(entry.get("title") or "")):
            entry["level"] = 1
            entry["parent_entry_index"] = None


def _toc_entry(index: int, parts: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_index": index,
        "raw_title": parts["raw_title"],
        "title": parts["title"],
        "display_title": parts["display_title"],
        "raw_label": parts["raw_label"],
        "label": parts["label"],
        "level": parts["level"],
        "parent_entry_index": None,
        "role": "unknown",
        "candidate_start_pages": [],
        "selected_start_page": None,
        "attrs": parts["attrs"],
    }


def _locate_title_pages(
    page_records: list[dict[str, Any]], title: str, *, exclude_pages: list[int]
) -> list[int]:
    excluded = set(exclude_pages)
    title_key = _normalize_title(title)
    if not title_key:
        return []
    candidates = []
    for record in page_records:
        page = int(record["page"])
        if page in excluded:
            continue
        text = _title_location_text(record)
        page_key = _normalize_title(text)
        if not _title_matches_record(record, title_key, page_key):
            continue
        candidates.append((page, _title_location_score(record, title_key, text, page_key)))
    return [page for page, _score in sorted(candidates, key=lambda item: (-item[1], item[0]))]


def _locate_toc_entry_pages(
    page_records: list[dict[str, Any]], entry: dict[str, Any], *, exclude_pages: list[int]
) -> list[int]:
    candidates = []
    seen = set()
    titles = (
        (entry["display_title"], entry["title"])
        if entry.get("label") is not None
        else (entry["title"], entry["display_title"])
    )
    for title in titles:
        for page in _locate_title_pages(page_records, title, exclude_pages=exclude_pages):
            if page in seen:
                continue
            seen.add(page)
            candidates.append(page)
    return candidates


def _apply_structural_roles(entries: list[dict[str, Any]]) -> None:
    first_body_index = _first_matching_entry_index(
        entries, _looks_like_body_toc_entry
    )
    if first_body_index is None:
        return
    for entry in entries[:first_body_index]:
        entry["role"] = "front_matter"
    for entry in entries[first_body_index:]:
        entry["role"] = "body"


def _apply_llm_classification(
    entries: list[dict[str, Any]],
    *,
    llm_classification: dict[str, Any] | None,
    llm_model: str | None,
    llm_source: str | None,
) -> dict[str, Any]:
    if llm_classification is None:
        return {"used": False, "model": None, "source": None, "uncertain_entries": []}
    entries_by_index = {entry["entry_index"]: entry for entry in entries}
    for item in llm_classification.get("entry_roles") or []:
        if not isinstance(item, dict):
            continue
        index = item.get("entry_index")
        role = item.get("role")
        if not isinstance(index, int) or role not in BOOK_SKELETON_ENTRY_ROLES:
            continue
        if index in entries_by_index:
            entries_by_index[index]["role"] = role
    _apply_structural_role_guardrails(entries)
    return {
        "used": True,
        "model": llm_model,
        "source": llm_source,
        "uncertain_entries": deepcopy(llm_classification.get("uncertain_entries") or []),
    }


def _select_monotonic_start_pages(entries: list[dict[str, Any]]) -> None:
    selections = _choose_monotonic_start_pages(
        [entry["candidate_start_pages"] for entry in entries]
    )
    for entry, selected_start_page in zip(entries, selections, strict=True):
        entry["selected_start_page"] = selected_start_page


def _prune_candidate_start_pages_to_toc_intervals(entries: list[dict[str, Any]]) -> None:
    selected_pages = [
        entry.get("selected_start_page") if isinstance(entry.get("selected_start_page"), int) else None
        for entry in entries
    ]
    for index, entry in enumerate(entries):
        selected_page = selected_pages[index]
        if selected_page is None:
            continue
        previous_page = _nearest_selected_page(selected_pages[:index], reverse=True)
        next_page = _nearest_selected_page(selected_pages[index + 1 :], reverse=False)
        candidates = entry["candidate_start_pages"]
        pruned = [
            page
            for page in candidates
            if (previous_page is None or page >= previous_page)
            and (next_page is None or page <= next_page)
        ]
        if selected_page not in pruned:
            pruned.insert(0, selected_page)
        entry["candidate_start_pages"] = pruned


def _nearest_selected_page(pages: list[int | None], *, reverse: bool) -> int | None:
    iterable = reversed(pages) if reverse else pages
    for page in iterable:
        if isinstance(page, int):
            return page
    return None


def _choose_monotonic_start_pages(candidate_lists: list[list[int]]) -> list[int | None]:
    states: dict[int | None, tuple[int, list[int | None]]] = {None: (0, [])}
    for candidates in candidate_lists:
        if not candidates:
            states = {
                last_page: (cost, [*path, None])
                for last_page, (cost, path) in states.items()
            }
            continue
        next_states: dict[int, tuple[int, list[int | None]]] = {}
        for last_page, (cost, path) in states.items():
            for rank, candidate in enumerate(candidates):
                if last_page is not None and candidate < last_page:
                    continue
                new_cost = cost + rank
                existing = next_states.get(candidate)
                if existing is None or new_cost < existing[0]:
                    next_states[candidate] = (new_cost, [*path, candidate])
        if not next_states:
            return _choose_local_best_start_pages(candidate_lists)
        states = next_states
    _last_page, (_cost, path) = min(states.items(), key=lambda item: (item[1][0], item[0] or 0))
    return path


def _choose_local_best_start_pages(candidate_lists: list[list[int]]) -> list[int | None]:
    return [candidates[0] if candidates else None for candidates in candidate_lists]


def _boundaries(
    entries: list[dict[str, Any]], *, llm_classification: dict[str, Any] | None
) -> dict[str, int | None]:
    first_body = _first_role_index(entries, "body")
    last_body = _last_role_index(entries, "body")
    first_back = _first_role_index(entries, "back_matter")
    return {
        "first_body_entry_index": first_body,
        "first_body_page": _selected_start_page(entries, first_body),
        "last_body_entry_index": last_body,
        "last_body_page": _selected_start_page(entries, last_body),
        "first_back_matter_entry_index": first_back,
        "first_back_matter_page": _selected_start_page(entries, first_back),
    }


def _valid_boundary_index(value: Any, entries: list[dict[str, Any]]) -> int | None:
    if isinstance(value, int) and 0 <= value < len(entries):
        return value
    return None


def _selected_start_page(entries: list[dict[str, Any]], index: int | None) -> int | None:
    if index is None:
        return None
    page = entries[index].get("selected_start_page")
    return int(page) if isinstance(page, int) else None


def _first_role_index(entries: list[dict[str, Any]], role: str) -> int | None:
    return _first_matching_entry_index(entries, lambda entry: entry.get("role") == role)


def _last_role_index(entries: list[dict[str, Any]], role: str) -> int | None:
    for entry in reversed(entries):
        if entry.get("role") == role:
            return int(entry["entry_index"])
    return None


def _first_matching_entry_index(entries: list[dict[str, Any]], predicate) -> int | None:
    for entry in entries:
        if predicate(entry):
            return int(entry["entry_index"])
    return None


def _looks_like_body_toc_entry(entry: dict[str, Any]) -> bool:
    label = str(entry.get("label") or "")
    display_title = str(entry.get("display_title") or "")
    return _looks_like_body_toc_title(label) or _looks_like_body_toc_title(display_title)


def _looks_like_body_toc_title(title: str) -> bool:
    stripped = title.strip()
    return BODY_TITLE_RE.match(stripped) is not None or NUMERIC_BODY_TITLE_RE.match(stripped) is not None


def _apply_structural_role_guardrails(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        if _looks_like_body_toc_entry(entry):
            entry["role"] = "body"


def _normalize_toc_line(line: str) -> str:
    return (
        line.replace("／", "/")
        .replace("．", ".")
        .replace("—", "-")
        .replace("–", "-")
    )


def _clean_toc_title(title: str) -> str:
    return re.sub(r"[\s.·•/\-／]+$", "", title).strip()


def _is_noise_toc_title(title: str) -> bool:
    normalized = _normalize_title(title).lower()
    if not normalized:
        return True
    if normalized == "目录":
        return True
    return re.fullmatch(r"[ivxlcdm]+|\d+", normalized) is not None


def _normalize_title(text: str) -> str:
    return re.sub(r"[\s　,，.。:：;；/／\\\-—–·•…*＊①②③④⑤⑥⑦⑧⑨⑩《》〈〉（）()【】\[\]]+", "", text)


def _title_location_text(record: dict[str, Any]) -> str:
    lines = []
    seen = set()
    for key in ("content_text", "title_text"):
        for line in str(record.get(key) or "").splitlines():
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                lines.append(stripped)
    return "\n".join(lines)


def _title_matches_record(record: dict[str, Any], title_key: str, page_key: str) -> bool:
    if not title_key:
        return False
    title_text_key = _normalize_title(str(record.get("title_text") or ""))
    if title_key in GENERIC_TITLES_REQUIRING_TITLE_HINT:
        return title_key in title_text_key or _near_title_match(title_key, title_text_key)
    return (
        title_key in page_key
        or _near_title_match(title_key, page_key)
        or _near_title_match(title_key, title_text_key)
    )


def _near_title_match(title_key: str, text_key: str) -> bool:
    if len(title_key) < 5 or not text_key:
        return False
    max_distance = max(1, len(title_key) // 8)
    for candidate in _title_substrings(text_key, len(title_key)):
        if _edit_distance_at_most(title_key, candidate, max_distance):
            return True
    return False


def _title_substrings(text: str, length: int) -> list[str]:
    if len(text) <= length:
        return [text]
    return [text[index : index + length] for index in range(0, len(text) - length + 1)]


def _edit_distance_at_most(left: str, right: str, limit: int) -> bool:
    if abs(len(left) - len(right)) > limit:
        return False
    previous = list(range(len(right) + 1))
    for row_index, left_char in enumerate(left, start=1):
        current = [row_index]
        row_min = current[0]
        for column_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[column_index] + 1,
                current[column_index - 1] + 1,
                previous[column_index - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return False
        previous = current
    return previous[-1] <= limit


def _title_location_score(
    record: dict[str, Any], title_key: str, text: str, page_key: str
) -> float:
    score = 1.0
    role_hint_counts = record.get("role_hint_counts") or {}
    if _is_footnote_heavy_location(role_hint_counts):
        score -= 8.0
    title_text_key = _normalize_title(str(record.get("title_text") or ""))
    if title_text_key:
        score += 0.5
    first_title_line = _normalize_title(_first_nonempty_line(str(record.get("title_text") or "")))
    if first_title_line == title_key:
        score += 4.0
    elif first_title_line.startswith(title_key):
        score += 0.25
    if page_key.startswith(title_key):
        score += 1.5
    first_line = _normalize_title(_first_nonempty_line(text))
    if first_line == title_key:
        score += 2.0
    elif first_line.startswith(title_key):
        score += 0.75
    leading_two_lines = _normalize_title(_leading_nonempty_lines(text, limit=2))
    if leading_two_lines == title_key:
        score += 3.0
    elif leading_two_lines.startswith(title_key):
        score += 2.0
    return score


def _is_footnote_heavy_location(role_hint_counts: dict[str, Any]) -> bool:
    footnote_count = int(role_hint_counts.get("footnote_text") or 0)
    body_count = int(role_hint_counts.get("body_text") or 0)
    list_count = int(role_hint_counts.get("list_text") or 0)
    return footnote_count >= max(2, body_count + list_count + 1)


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _leading_nonempty_lines(text: str, *, limit: int) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
        if len(lines) >= limit:
            break
    return "".join(lines)


def _validate_metadata(metadata: dict[str, Any]) -> None:
    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata:
            raise ValidationError(f"metadata.{field} is required")
    if metadata.get("schema_name") != BOOK_SKELETON_SCHEMA_NAME:
        raise ValidationError(f"metadata.schema_name must be {BOOK_SKELETON_SCHEMA_NAME}")
    if metadata.get("schema_version") != BOOK_SKELETON_SCHEMA_VERSION:
        raise ValidationError(f"metadata.schema_version must be {BOOK_SKELETON_SCHEMA_VERSION}")


def _validate_toc_pages(toc_pages: list[Any]) -> None:
    if not all(isinstance(page, int) for page in toc_pages):
        raise ValidationError("toc_pages must contain integers")


def _validate_toc_entries(entries: list[dict[str, Any]]) -> None:
    seen: set[int] = set()
    previous_known_role_rank = -1
    for index, entry in enumerate(entries):
        _validate_toc_entry_shape(entry, index, seen)
        _validate_toc_entry_pages(entry, index)
        previous_known_role_rank = _validate_toc_entry_role_order(
            entry, previous_known_role_rank
        )


def _validate_toc_entry_shape(
    entry: dict[str, Any], index: int, seen: set[int]
) -> None:
    if not isinstance(entry, dict):
        raise ValidationError(f"toc_entries[{index}] must be object")
    for field, expected_type in REQUIRED_ENTRY_FIELDS.items():
        value = entry.get(field)
        if not isinstance(value, expected_type):
            raise ValidationError(f"toc_entries[{index}].{field} is invalid")
    entry_index = entry["entry_index"]
    if entry_index in seen:
        raise ValidationError(f"duplicate toc entry index: {entry_index}")
    if entry_index != index:
        raise ValidationError(f"toc_entries[{index}].entry_index must equal list index")
    seen.add(entry_index)
    if entry["role"] not in BOOK_SKELETON_ENTRY_ROLES:
        raise ValidationError(f"toc_entries[{index}].role is invalid: {entry['role']}")
    if "candidate_pages" in entry:
        raise ValidationError(
            f"toc_entries[{index}].candidate_pages is ambiguous; use candidate_start_pages"
        )
    if "selected_page" in entry:
        raise ValidationError(
            f"toc_entries[{index}].selected_page is ambiguous; use selected_start_page"
        )
    if "printed_start_page" in entry:
        raise ValidationError(
            f"toc_entries[{index}].printed_start_page is internal TOC evidence"
        )


def _validate_toc_entry_pages(entry: dict[str, Any], index: int) -> None:
    candidate_start_pages = entry["candidate_start_pages"]
    if not all(isinstance(page, int) for page in candidate_start_pages):
        raise ValidationError(f"toc_entries[{index}].candidate_start_pages must contain integers")
    selected_start_page = entry["selected_start_page"]
    if selected_start_page is not None and selected_start_page not in candidate_start_pages:
        raise ValidationError(
            f"toc_entries[{index}].selected_start_page must be one of candidate_start_pages"
        )
    if not candidate_start_pages and _looks_like_glued_toc_title(entry["title"]):
        raise ValidationError(f"toc_entries[{index}].title looks like glued TOC entries")


def _validate_toc_entry_role_order(
    entry: dict[str, Any], previous_known_role_rank: int
) -> int:
    role_rank = BOOK_SKELETON_ENTRY_ROLE_ORDER.get(entry["role"])
    if role_rank is None:
        return previous_known_role_rank
    if role_rank < previous_known_role_rank:
        raise ValidationError("toc_entries roles must be contiguous")
    return role_rank


def _looks_like_glued_toc_title(title: str) -> bool:
    return len(title) >= 40 and len(list(TOC_ENTRY_PART_RE.finditer(title))) >= 2


def _audit_toc_entry_issues(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    previous_selected_start_page: int | None = None
    previous_known_role_rank = -1
    for index, entry in enumerate(entries):
        entry_index = entry.get("entry_index", index)
        title = str(entry.get("title") or "")
        candidate_start_pages = entry.get("candidate_start_pages")
        if not isinstance(candidate_start_pages, list):
            candidate_start_pages = []
        selected_start_page = entry.get("selected_start_page")
        attrs = entry.get("attrs") if isinstance(entry.get("attrs"), dict) else {}
        label_correction = attrs.get("label_correction")
        if isinstance(label_correction, dict):
            issues.append(
                {
                    **_toc_entry_issue(
                        "label_ocr_corrected",
                        entry_index=entry_index,
                        title=title,
                        message="TOC label was corrected from OCR-suspect raw_label.",
                        severity="info",
                    ),
                    "raw_label": label_correction.get("from"),
                    "label": label_correction.get("to"),
                    "llm_review_recommended": True,
                }
            )
        if not candidate_start_pages:
            issues.append(
                _toc_entry_issue(
                    "unlocated_entry",
                    entry_index=entry_index,
                    title=title,
                    message="TOC entry has no located physical start page.",
                )
            )
        if selected_start_page is not None and selected_start_page not in candidate_start_pages:
            issues.append(
                _toc_entry_issue(
                    "selected_start_page_not_in_candidates",
                    entry_index=entry_index,
                    title=title,
                    message="selected_start_page is not present in candidate_start_pages.",
                )
            )
        if (
            isinstance(selected_start_page, int)
            and previous_selected_start_page is not None
            and selected_start_page < previous_selected_start_page
        ):
            issues.append(
                _toc_entry_issue(
                    "non_monotonic_selected_start_page",
                    entry_index=entry_index,
                    title=title,
                    message="selected_start_page moves backwards from the previous located TOC entry.",
                )
            )
        if isinstance(selected_start_page, int):
            previous_selected_start_page = selected_start_page
        role_rank = BOOK_SKELETON_ENTRY_ROLE_ORDER.get(str(entry.get("role") or ""))
        if role_rank is not None:
            if role_rank < previous_known_role_rank:
                issues.append(
                    _toc_entry_issue(
                        "roles_not_contiguous",
                        entry_index=entry_index,
                        title=title,
                        message="Known TOC roles must progress front_matter -> body -> back_matter.",
                    )
                )
            previous_known_role_rank = role_rank
    return issues


def _toc_entry_issue(
    issue_type: str, *, entry_index: Any, title: str, message: str, severity: str = "warning"
) -> dict[str, Any]:
    return {
        "severity": severity,
        "issue_type": issue_type,
        "entry_index": entry_index,
        "title": title,
        "message": message,
    }


def _validate_boundaries(boundaries: dict[str, Any], entry_count: int) -> None:
    for field in REQUIRED_BOUNDARY_FIELDS:
        if field not in boundaries:
            raise ValidationError(f"boundaries.{field} is required")
        value = boundaries[field]
        if value is not None and not isinstance(value, int):
            raise ValidationError(f"boundaries.{field} must be integer or null")
        if field.endswith("_entry_index") and isinstance(value, int) and not 0 <= value < entry_count:
            raise ValidationError(f"boundaries.{field} points to missing toc entry")


def _validate_llm(llm: dict[str, Any]) -> None:
    if not isinstance(llm.get("used"), bool):
        raise ValidationError("llm.used must be boolean")
    if llm.get("model") is not None and not isinstance(llm.get("model"), str):
        raise ValidationError("llm.model must be string or null")
    if llm.get("source") is not None and not isinstance(llm.get("source"), str):
        raise ValidationError("llm.source must be string or null")
    if not isinstance(llm.get("uncertain_entries"), list):
        raise ValidationError("llm.uncertain_entries must be list")


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
