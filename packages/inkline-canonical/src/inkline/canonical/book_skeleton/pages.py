from __future__ import annotations

import re
from collections import Counter
from typing import Any

from inkline.canonical.book_skeleton.contract import (
    BOOK_SKELETON_SCHEMA_NAME,
    BOOK_SKELETON_SCHEMA_VERSION,
)
from inkline.canonical.book_skeleton.toc import (
    normalize_title,
    parse_toc_line_entries,
)

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
SHORT_AMBIGUOUS_TITLE_KEY_MAX_LENGTH = 4
PRINTED_OFFSET_TOLERANCE = 2
MAX_PRINTED_PAGE_OFFSET = 128
MISSING_START_PAGE_COST = 24
DISPLAY_TITLE_PREFIX_RE = re.compile(
    r"^(?P<label>(?:第[一二三四五六七八九十百零〇\d]+[章节部篇卷]|"
    r"[一二三四五六七八九十百零〇\d]+[、.]?|"
    r"附录\s*[A-Za-z一二三四五六七八九十百零〇\d]*|"
    r"专题\s*\d+))\s*(?P<title>.+)$"
)


def metadata(document: dict[str, Any]) -> dict[str, Any]:
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


def page_records(document: dict[str, Any]) -> list[dict[str, Any]]:
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
                "visual_title_text": _page_text(visual_title_observations),
                "candidate_title_text": _page_text(
                    _candidate_title_context_observations(text_observations)
                ),
                "has_toc_hint": any(
                    observation.get("role_hint") == "toc_text"
                    for observation in text_observations
                ),
            }
        )
    return records


def detect_toc_pages(page_records_: list[dict[str, Any]]) -> list[int]:
    pages: set[int] = set()
    for record in page_records_:
        text = str(record.get("text") or "")
        toc_like_lines = _toc_like_line_count(text)
        has_toc_title = "目录" in text[:120]
        if (record.get("has_toc_hint") and (has_toc_title or toc_like_lines >= 3)) or (
            has_toc_title and toc_like_lines >= 2
        ):
            pages.add(int(record["page"]))
    if not pages:
        return []
    records_by_page = {int(record["page"]): record for record in page_records_}
    for page in sorted(pages):
        next_page = page + 1
        while next_page in records_by_page:
            text = str(records_by_page[next_page].get("text") or "")
            if _toc_like_line_count(text) < 2:
                break
            pages.add(next_page)
            next_page += 1
    return sorted(pages)


def observed_page_text(document: dict[str, Any], page_number: int) -> str:
    return "\n".join(
        str(observation.get("text") or "").strip()
        for observation in document["observations"]
        if int(observation.get("page") or 0) == page_number
        and observation.get("kind") in TEXT_KINDS
        and str(observation.get("text") or "").strip()
    )


def locate_toc_entry_pages(
    page_records_: list[dict[str, Any]], entry: dict[str, Any], *, exclude_pages: list[int]
) -> list[int]:
    candidates = []
    seen = set()
    for title in _location_titles_for_entry(entry):
        for page in locate_title_pages(page_records_, title, exclude_pages=exclude_pages):
            if page in seen:
                continue
            seen.add(page)
            candidates.append(page)
    return candidates


def _location_titles_for_entry(entry: dict[str, Any]) -> list[str]:
    titles = []
    for title in (
        entry.get("display_title"),
        entry.get("title"),
        _display_title_without_structural_prefix(str(entry.get("display_title") or "")),
    ):
        if not isinstance(title, str):
            continue
        title = title.strip()
        if title and title not in titles:
            titles.append(title)
    return titles


def _display_title_without_structural_prefix(display_title: str) -> str | None:
    match = DISPLAY_TITLE_PREFIX_RE.match(display_title.strip())
    if not match:
        return None
    title = match.group("title").strip()
    return title or None


def locate_title_pages(
    page_records_: list[dict[str, Any]], title: str, *, exclude_pages: list[int]
) -> list[int]:
    excluded = set(exclude_pages)
    title_key = normalize_title(title)
    if not title_key:
        return []
    candidates = []
    for record in page_records_:
        page = int(record["page"])
        if page in excluded:
            continue
        text = _title_location_text(record)
        page_key = normalize_title(text)
        if not _title_matches_record(record, title_key, page_key):
            continue
        candidates.append((page, _title_location_score(record, title_key, text, page_key)))
    return [page for page, _score in sorted(candidates, key=lambda item: (-item[1], item[0]))]


def select_monotonic_start_pages(entries: list[dict[str, Any]]) -> None:
    selections = _choose_monotonic_start_pages(
        [entry["candidate_start_pages"] for entry in entries],
        [entry.get("printed_start_page") for entry in entries],
        [entry.get("role") for entry in entries],
    )
    for entry, selected_start_page in zip(entries, selections, strict=True):
        entry["selected_start_page"] = selected_start_page


def add_printed_page_offset_candidates(entries: list[dict[str, Any]], *, page_count: int) -> None:
    """Add a physical-page candidate when adjacent same-role anchors agree on offset."""

    for index, entry in enumerate(entries):
        if entry.get("selected_start_page") is not None:
            continue
        printed_start_page = entry.get("printed_start_page")
        if not isinstance(printed_start_page, int):
            continue
        offset = _agreed_neighbor_offset(entries, index)
        if offset is None:
            continue
        predicted_page = printed_start_page + offset
        if not 1 <= predicted_page <= page_count:
            continue
        if predicted_page not in entry["candidate_start_pages"]:
            entry["candidate_start_pages"].append(predicted_page)


def prune_candidate_start_pages_to_toc_intervals(entries: list[dict[str, Any]]) -> None:
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


def boundaries(entries: list[dict[str, Any]]) -> dict[str, int | None]:
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


def _candidate_title_context_observations(
    text_observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = [
        observation
        for observation in text_observations
        if _is_candidate_title_context_observation(observation)
    ]
    if len(candidates) < 2:
        return []
    return candidates


def _is_candidate_title_context_observation(observation: dict[str, Any]) -> bool:
    role_hint = str(observation.get("role_hint") or "")
    if role_hint in TITLE_LOCATION_EXCLUDED_ROLE_HINTS or role_hint == "toc_text":
        return False
    text = str(observation.get("text") or "").strip()
    return role_hint in {"body_text", "list_text", ""} and _is_short_title_context_line(text)


def _is_short_title_context_line(text: str) -> bool:
    return 0 < len(normalize_title(text)) <= 36


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


def _toc_like_line_count(text: str) -> int:
    return sum(
        len(parse_toc_line_entries(line.strip()))
        for line in text.splitlines()
    )


def _nearest_selected_page(pages: list[int | None], *, reverse: bool) -> int | None:
    iterable = reversed(pages) if reverse else pages
    for page in iterable:
        if isinstance(page, int):
            return page
    return None


def _agreed_neighbor_offset(entries: list[dict[str, Any]], index: int) -> int | None:
    entry = entries[index]
    role = entry.get("role")
    previous_offset = _neighbor_printed_offset(entries, index, role=role, reverse=True)
    next_offset = _neighbor_printed_offset(entries, index, role=role, reverse=False)
    if previous_offset is None or next_offset is None:
        return None
    if abs(previous_offset - next_offset) > PRINTED_OFFSET_TOLERANCE:
        return None
    return round((previous_offset + next_offset) / 2)


def _neighbor_printed_offset(
    entries: list[dict[str, Any]],
    index: int,
    *,
    role: Any,
    reverse: bool,
) -> int | None:
    positions = range(index - 1, -1, -1) if reverse else range(index + 1, len(entries))
    for position in positions:
        candidate = entries[position]
        if candidate.get("role") != role:
            continue
        selected_page = candidate.get("selected_start_page")
        printed_page = candidate.get("printed_start_page")
        if isinstance(selected_page, int) and isinstance(printed_page, int):
            return selected_page - printed_page
    return None


def _choose_monotonic_start_pages(
    candidate_lists: list[list[int]], printed_start_pages: list[Any], roles: list[Any]
) -> list[int | None]:
    states: dict[tuple[int | None, int | None, Any], tuple[int, list[int | None]]] = {
        (None, None, None): (0, [])
    }
    for candidates, printed_start_page, role in zip(
        candidate_lists, printed_start_pages, roles, strict=True
    ):
        next_states: dict[tuple[int | None, int | None, Any], tuple[int, list[int | None]]] = {}
        for (last_page, last_offset, last_role), (cost, path) in states.items():
            _keep_better_state(
                next_states,
                (last_page, last_offset, last_role),
                cost + MISSING_START_PAGE_COST,
                [*path, None],
            )
            for rank, candidate in enumerate(candidates):
                if last_page is not None and candidate < last_page:
                    continue
                candidate_offset = _printed_offset(candidate, printed_start_page)
                if _is_implausible_printed_offset(candidate_offset):
                    continue
                active_offset = last_offset if last_role == role else None
                new_cost = cost + rank + _offset_transition_penalty(
                    candidate_offset, active_offset
                )
                _keep_better_state(
                    next_states,
                    (
                        candidate,
                        candidate_offset if candidate_offset is not None else active_offset,
                        role,
                    ),
                    new_cost,
                    [*path, candidate],
                )
        states = next_states
    _last_state, (_cost, path) = min(
        states.items(),
        key=lambda item: (
            item[1][0],
            _missing_pattern(item[1][1]),
            item[0][0] or 0,
        ),
    )
    return path


def _printed_offset(candidate: int, printed_start_page: Any) -> int | None:
    return candidate - printed_start_page if isinstance(printed_start_page, int) else None


def _is_implausible_printed_offset(offset: int | None) -> bool:
    return offset is not None and abs(offset) > MAX_PRINTED_PAGE_OFFSET


def _offset_transition_penalty(candidate_offset: int | None, last_offset: int | None) -> int:
    if candidate_offset is None or last_offset is None:
        return 0
    return abs(candidate_offset - last_offset)


def _keep_better_state(
    states: dict[tuple[int | None, int | None, Any], tuple[int, list[int | None]]],
    state_key: tuple[int | None, int | None, Any],
    cost: int,
    path: list[int | None],
) -> None:
    existing = states.get(state_key)
    if existing is None or (cost, _missing_pattern(path)) < (
        existing[0],
        _missing_pattern(existing[1]),
    ):
        states[state_key] = (cost, path)


def _missing_pattern(path: list[int | None]) -> tuple[bool, ...]:
    return tuple(page is None for page in path)


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


def _title_location_text(record: dict[str, Any]) -> str:
    lines = []
    seen = set()
    for key in ("content_text", "title_text", "candidate_title_text"):
        for line in str(record.get(key) or "").splitlines():
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                lines.append(stripped)
    return "\n".join(lines)


def _title_matches_record(record: dict[str, Any], title_key: str, page_key: str) -> bool:
    if not title_key:
        return False
    title_text_key = normalize_title(str(record.get("title_text") or ""))
    visual_title_key = normalize_title(str(record.get("visual_title_text") or ""))
    if _requires_title_evidence(title_key):
        return (
            title_key in title_text_key
            or title_key in visual_title_key
            or _near_title_match(title_key, title_text_key)
            or _near_title_match(title_key, visual_title_key)
        )
    return (
        title_key in page_key
        or _near_title_match(title_key, page_key)
        or _near_title_match(title_key, title_text_key)
        or _near_title_match(title_key, visual_title_key)
    )


def _requires_title_evidence(title_key: str) -> bool:
    return len(title_key) <= SHORT_AMBIGUOUS_TITLE_KEY_MAX_LENGTH


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
    title_text_key = normalize_title(str(record.get("title_text") or ""))
    score += _presence_score(title_text_key, 0.5)
    visual_title_key = normalize_title(str(record.get("visual_title_text") or ""))
    score += _presence_score(visual_title_key, 0.5)
    score += _exact_or_prefix_score(visual_title_key, title_key, exact=4.0, prefix=0.0)
    first_title_line = normalize_title(_first_nonempty_line(str(record.get("title_text") or "")))
    score += _exact_or_prefix_score(first_title_line, title_key, exact=4.0, prefix=0.25)
    score += _prefix_score(page_key, title_key, 1.5)
    first_line = normalize_title(_first_nonempty_line(text))
    score += _exact_or_prefix_score(first_line, title_key, exact=2.0, prefix=0.75)
    leading_two_lines = normalize_title(_leading_nonempty_lines(text, limit=2))
    score += _exact_or_prefix_score(leading_two_lines, title_key, exact=3.0, prefix=2.0)
    candidate_title_key = normalize_title(str(record.get("candidate_title_text") or ""))
    score += _exact_or_prefix_score(candidate_title_key, title_key, exact=4.0, prefix=2.0)
    return score


def _presence_score(value: str, score: float) -> float:
    return score if value else 0.0


def _prefix_score(value: str, target: str, score: float) -> float:
    return score if value.startswith(target) else 0.0


def _exact_or_prefix_score(value: str, target: str, *, exact: float, prefix: float) -> float:
    if value == target:
        return exact
    if value.startswith(target):
        return prefix
    return 0.0


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
