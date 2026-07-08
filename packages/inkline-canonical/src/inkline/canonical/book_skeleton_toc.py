from __future__ import annotations

import re
from typing import Any

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
BOOK_MATTER_TITLE_PREFIXES = (
    "前言",
    "序言",
    "引言",
    "致谢",
    "说明",
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


def parse_toc_entries(text: str) -> list[dict[str, Any]]:
    entries = []
    for line in _logical_toc_lines(text):
        if line == "目录":
            continue
        for item in parse_toc_line_entries(line):
            entries.append(_toc_entry(len(entries), item))
    return entries


def parse_toc_line_entries(line: str) -> list[dict[str, str | None]]:
    normalized_line = normalize_toc_line(line)
    matches = list(TOC_ENTRY_PART_RE.finditer(normalized_line))
    if not matches and _looks_like_standalone_toc_heading(normalized_line):
        return [_toc_entry_parts(normalized_line)]
    if _should_parse_as_single_toc_entry(normalized_line, matches):
        match = TOC_ENTRY_RE.match(normalized_line)
        if match is None:
            return []
        title = clean_toc_title(match.group("title"))
        if not title or _is_noise_toc_title(title):
            return []
        return [_toc_entry_parts(title)]
    items = []
    raw_items = [
        {
            "title": clean_toc_title(match.group("title")),
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


def infer_toc_levels(entries: list[dict[str, Any]]) -> None:
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
        if is_top_level_unlabeled_title(title):
            entry["level"] = 1
        elif seen_chapter:
            entry["level"] = 2
        else:
            entry["level"] = 1


def assign_toc_hierarchy(entries: list[dict[str, Any]]) -> None:
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


def apply_role_level_guardrails(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        if entry.get("label") is None and entry.get("role") in {"front_matter", "back_matter"}:
            entry["level"] = 1
            entry["parent_entry_index"] = None
        if is_top_level_unlabeled_title(str(entry.get("title") or "")):
            entry["level"] = 1
            entry["parent_entry_index"] = None


def looks_like_body_toc_entry(entry: dict[str, Any]) -> bool:
    label = str(entry.get("label") or "")
    display_title = str(entry.get("display_title") or "")
    return looks_like_body_toc_title(label) or looks_like_body_toc_title(display_title)


def looks_like_body_toc_title(title: str) -> bool:
    stripped = title.strip()
    return BODY_TITLE_RE.match(stripped) is not None or NUMERIC_BODY_TITLE_RE.match(stripped) is not None


def apply_structural_role_guardrails(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        if looks_like_body_toc_entry(entry):
            entry["role"] = "body"


def normalize_toc_line(line: str) -> str:
    return (
        line.replace("／", "/")
        .replace("．", ".")
        .replace("—", "-")
        .replace("–", "-")
    )


def clean_toc_title(title: str) -> str:
    return re.sub(r"[\s.·•/\-／]+$", "", title).strip()


def normalize_title(text: str) -> str:
    return re.sub(r"[\s　,，.。:：;；/／\\\-—–·•…*＊①②③④⑤⑥⑦⑧⑨⑩《》〈〉（）()【】\[\]]+", "", text)


def is_top_level_unlabeled_title(title: str) -> bool:
    stripped = title.strip()
    return any(stripped.startswith(prefix) for prefix in BOOK_MATTER_TITLE_PREFIXES)


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
        if next_line and _is_toc_page_token(next_line) and not parse_toc_line_entries(line):
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
    if parse_toc_line_entries(line):
        return False
    if _looks_like_standalone_toc_heading(line):
        return False
    return bool(parse_toc_line_entries(next_line))


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
        title = clean_toc_title(whole_line_match.group("title"))
        if _has_non_numeric_toc_label(title):
            return True
    first = matches[0]
    title = clean_toc_title(first.group("title"))
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


def _is_non_parentable_top_level_entry(entry: dict[str, Any]) -> bool:
    if int(entry.get("level") or 0) != 1:
        return False
    if entry.get("label") is not None:
        return False
    return is_top_level_unlabeled_title(str(entry.get("title") or ""))


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


def _is_noise_toc_title(title: str) -> bool:
    normalized = normalize_title(title).lower()
    if not normalized:
        return True
    if normalized == "目录":
        return True
    return re.fullmatch(r"[ivxlcdm]+|\d+", normalized) is not None
