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

TEXT_KINDS = {"text_region", "footnote_region", "page_marker"}
TITLE_LOCATION_ROLE_HINTS = {"title_text", "body_text", "list_text", "unknown"}
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
BODY_TITLE_RE = re.compile(r"^(?:第[一二三四五六七八九十百千万\d]+(?:章节|部分|[章节部卷篇])|序章)")
NUMERIC_BODY_TITLE_RE = re.compile(r"^\d{1,3}\s+\S")
GENERIC_TITLES_REQUIRING_TITLE_HINT = {"注释", "索引", "参考文献", "参考书目"}

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
    "title": str,
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
    for entry in entries:
        candidates = _locate_title_pages(page_records, entry["title"], exclude_pages=toc_pages)
        entry["candidate_start_pages"] = candidates
        entry["selected_start_page"] = candidates[0] if candidates else None
    _apply_structural_roles(entries)
    llm_summary = _apply_llm_classification(
        entries,
        llm_classification=llm_classification,
        llm_model=llm_model,
        llm_source=llm_source,
    )
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
    toc_entries = []
    for entry in entries:
        toc_entries.append(
            {
                "entry_index": entry["entry_index"],
                "title": entry["title"],
                "candidate_start_pages": _locate_title_pages(
                    page_records,
                    entry["title"],
                    exclude_pages=toc_pages,
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
        "Use only entry_index and title to decide entry roles. Do not infer or output physical "
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
        role_hint_counts = Counter(str(observation.get("role_hint") or "") for observation in observations)
        records.append(
            {
                "page": page_number,
                "role_hint_counts": dict(role_hint_counts),
                "text": _page_text(text_observations),
                "content_text": _page_text(title_location_observations),
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
    for line in (line.strip() for line in text.splitlines()):
        if not line or line == "目录":
            continue
        for title in _parse_toc_line_entries(line):
            entries.append(_toc_entry(len(entries), title))
    return entries


def _parse_toc_line_entries(line: str) -> list[str]:
    normalized_line = _normalize_toc_line(line)
    matches = list(TOC_ENTRY_PART_RE.finditer(normalized_line))
    if _should_parse_as_single_toc_entry(normalized_line, matches):
        match = TOC_ENTRY_RE.match(normalized_line)
        if match is None:
            return []
        title = _clean_toc_title(match.group("title"))
        return [title] if title and not _is_noise_toc_title(title) else []
    titles = []
    for match in matches:
        title = _clean_toc_title(match.group("title"))
        if title and not _is_noise_toc_title(title):
            titles.append(title)
    return titles


def _should_parse_as_single_toc_entry(line: str, matches: list[re.Match[str]]) -> bool:
    if len(matches) <= 1:
        return True
    first = matches[0]
    title = _clean_toc_title(first.group("title"))
    page_token = first.group("page")
    return title in {"附录", "Appendix", "appendix"} and len(page_token) == 1


def _toc_entry(index: int, title: str) -> dict[str, Any]:
    return {
        "entry_index": index,
        "title": title,
        "role": "unknown",
        "candidate_start_pages": [],
        "selected_start_page": None,
        "attrs": {},
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


def _apply_structural_roles(entries: list[dict[str, Any]]) -> None:
    first_body_index = _first_matching_entry_index(
        entries, lambda entry: _looks_like_body_toc_title(entry["title"])
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


def _looks_like_body_toc_title(title: str) -> bool:
    stripped = title.strip()
    return BODY_TITLE_RE.match(stripped) is not None or NUMERIC_BODY_TITLE_RE.match(stripped) is not None


def _apply_structural_role_guardrails(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        if _looks_like_body_toc_title(entry["title"]):
            entry["role"] = "body"


def _normalize_toc_line(line: str) -> str:
    return (
        line.replace("／", "/")
        .replace("．", ".")
        .replace("…", ".")
        .replace("—", "-")
        .replace("–", "-")
    )


def _clean_toc_title(title: str) -> str:
    return re.sub(r"[\s.·•…/\-／]+$", "", title).strip()


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
    return title_key in page_key or _near_title_match(title_key, title_text_key)


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
        score -= 4.0
    title_text_key = _normalize_title(str(record.get("title_text") or ""))
    if title_text_key:
        score += 0.5
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
    reference_count = int(role_hint_counts.get("reference_text") or 0)
    body_count = int(role_hint_counts.get("body_text") or 0)
    list_count = int(role_hint_counts.get("list_text") or 0)
    return footnote_count + reference_count >= max(2, body_count + list_count + 1)


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
    for index, entry in enumerate(entries):
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
        if not all(isinstance(page, int) for page in entry["candidate_start_pages"]):
            raise ValidationError(
                f"toc_entries[{index}].candidate_start_pages must contain integers"
            )
        if not entry["candidate_start_pages"] and _looks_like_glued_toc_title(entry["title"]):
            raise ValidationError(f"toc_entries[{index}].title looks like glued TOC entries")


def _looks_like_glued_toc_title(title: str) -> bool:
    return len(title) >= 40 and len(list(TOC_ENTRY_PART_RE.finditer(title))) >= 2


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
