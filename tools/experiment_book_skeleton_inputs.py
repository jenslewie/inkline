#!/usr/bin/env python
"""Build offline input packages for Book Skeleton LLM experiments.

The tool intentionally consumes ObservedDocument rather than BookGraph nodes.  It
lets us compare ObservedDocument-only, PDF-image-only, and hybrid prompt inputs
without wiring LLM output back into canonical generation.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from inkline.canonical.observed import validate_observed_document
from inkline.llm import DEFAULT_QWEN_MODEL, OllamaChatConfig, extract_json_value

TEXT_KINDS = {"text_region", "footnote_region", "page_marker"}
VISUAL_KINDS = {"image_region", "table_region"}
EDGE_PAGE_LIMIT = 24
MAX_PAGE_TEXT_CHARS = 320
MAX_PROMPT_JSON_CHARS = 90000
TOC_ENTRY_RE = re.compile(r"^\s*(?P<title>.+?)\s*(?:[/／.·•…\-\s]+)?(?P<page>[ivxlcdmIVXLCDM\d]+)\s*$")
BODY_TITLE_RE = re.compile(r"^(?:第[一二三四五六七八九十百千万\d]+(?:章节|部分|[章节部卷篇])|序章)")
NUMERIC_BODY_TITLE_RE = re.compile(r"^\d{1,3}\s+\S")
FRONT_MATTER_TITLE_KEYWORDS = {
    "中文版序言",
    "新版序言",
    "序言",
    "前言",
    "自序",
    "导言",
    "引言",
    "致谢",
    "学术惯例说明",
    "凡例",
    "献词",
    "年表",
}
BACK_MATTER_TITLE_KEYWORDS = {
    "附录",
    "注释",
    "参考书目",
    "参考文献",
    "扩展阅读",
    "索引",
    "大事年表",
    "出版后记",
    "译后记",
    "后记",
    "版权页",
}


def build_skeleton_evidence_package(document: dict[str, Any]) -> dict[str, Any]:
    validate_observed_document(document)
    observations_by_page = _observations_by_page(document["observations"])
    pages = sorted(document["pages"], key=lambda page: int(page["page"]))
    page_numbers = [int(page["page"]) for page in pages]
    edge_pages = _edge_pages(page_numbers)
    page_records = [
        _page_record(page, observations_by_page.get(int(page["page"]), []), edge_pages)
        for page in pages
    ]
    candidate_pages = [
        _candidate_record(record)
        for record in page_records
        if _candidate_record(record) is not None
    ]
    return {
        "schema_name": "inkline_book_skeleton_experiment",
        "schema_version": "0.1-dev",
        "metadata": _metadata(document),
        "page_count": len(pages),
        "pages": page_records,
        "candidate_pages": candidate_pages,
        "instructions": {
            "purpose": "Compare LLM inputs for book skeleton detection before node construction.",
            "expected_output": _expected_skeleton_schema(),
            "do_not_use": [
                "Do not depend on existing logical content ids or logical content types.",
                "Do not create paragraph/display_block/heading content items.",
            ],
        },
    }


def build_toc_driven_skeleton_plan(document: dict[str, Any]) -> dict[str, Any]:
    package = build_skeleton_evidence_package(document)
    toc_pages = detect_toc_pages(package)
    toc_text = "\n".join(_observed_page_text(document, page) for page in toc_pages)
    entries = parse_toc_entries(toc_text)
    for entry in entries:
        entry["candidate_pages"] = locate_title_pages(package, entry["title"], exclude_pages=toc_pages)

    first_body_entry = _first_body_entry(entries)
    body_start_candidates = (
        [int(first_body_entry["candidate_pages"][0])]
        if first_body_entry is not None and first_body_entry.get("candidate_pages")
        else []
    )
    first_back_entry = _first_back_matter_entry(entries)
    back_matter_start_candidates = (
        [int(first_back_entry["candidate_pages"][0])]
        if first_back_entry is not None and first_back_entry.get("candidate_pages")
        else []
    )
    last_back_entry_page = _estimated_last_back_entry_end_page(package, entries)
    first_entry_page = _first_located_entry_page(entries)
    llm_page_tasks = _toc_driven_llm_page_tasks(
        entries,
        toc_pages=toc_pages,
        page_numbers=[int(page["page"]) for page in package["pages"]],
        first_entry_page=first_entry_page,
        last_back_entry_page=last_back_entry_page,
    )
    return {
        "mode": "toc_driven",
        "metadata": package["metadata"],
        "page_count": package["page_count"],
        "toc_pages": toc_pages,
        "toc_entries": entries,
        "body_start_candidates": body_start_candidates,
        "back_matter_start_candidates": back_matter_start_candidates,
        "llm_page_tasks": llm_page_tasks,
    }


def build_toc_llm_input(document: dict[str, Any]) -> dict[str, Any]:
    package = build_skeleton_evidence_package(document)
    toc_pages = detect_toc_pages(package)
    toc_text_pages = [
        {"page": page, "text": _observed_page_text(document, page)}
        for page in toc_pages
    ]
    toc_text = "\n".join(item["text"] for item in toc_text_pages)
    entries = parse_toc_entries(toc_text)
    toc_entries = []
    for index, entry in enumerate(entries):
        toc_entries.append(
            {
                "entry_index": index,
                "title": entry["title"],
                "candidate_pages": locate_title_pages(
                    package,
                    entry["title"],
                    exclude_pages=toc_pages,
                )[:5],
            }
        )
    return {
        "mode": "toc_llm",
        "metadata": package["metadata"],
        "page_count": package["page_count"],
        "toc_pages": toc_pages,
        "toc_text_pages": toc_text_pages,
        "toc_entries": toc_entries,
        "expected_output": _expected_toc_llm_schema(),
        "instructions": {
            "purpose": "Ask an LLM to classify the book skeleton from TOC structure only.",
            "rule_layer_responsibility": [
                "Find TOC pages.",
                "Extract TOC text and candidate title locations.",
                "Do not decide front/body/back roles from title word lists.",
            ],
        },
    }


def detect_toc_pages(package: dict[str, Any]) -> list[int]:
    toc_pages: set[int] = set()
    page_count = int(package.get("page_count") or len(package.get("pages") or []))
    front_limit = max(80, round(page_count * 0.12))
    records_by_page = {int(record["page"]): record for record in package["pages"]}
    for record in package["pages"]:
        text = str(record.get("text_snippet") or "")
        page = int(record["page"])
        role_hint_counts = record.get("role_hint_counts") or {}
        toc_like_lines = _toc_like_line_count(text)
        has_toc_title = "目录" in text[:80]
        if _looks_like_copyright_page(text) or _looks_like_index_page(text, page, page_count):
            continue
        if has_toc_title and toc_like_lines >= 1:
            toc_pages.add(page)
            continue
        if page <= front_limit and role_hint_counts.get("toc_text", 0) > 0 and toc_like_lines >= 8:
            toc_pages.add(page)
    return sorted(_expand_toc_continuation_pages(toc_pages, records_by_page, front_limit, page_count))


def parse_toc_entries(text: str) -> list[dict[str, Any]]:
    entries = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        if not line or line == "目录":
            index += 1
            continue
        normalized_line = _normalize_toc_line(line)
        match = TOC_ENTRY_RE.match(normalized_line)
        if (
            not match
            and _unpaged_structural_toc_title(normalized_line) is None
            and index + 1 < len(lines)
            and not _is_standalone_page_label(lines[index + 1])
        ):
            combined_line = _normalize_toc_line(f"{line} {lines[index + 1].strip()}")
            combined_match = TOC_ENTRY_RE.match(combined_line)
            if combined_match is not None:
                match = combined_match
                index += 1
        if not match:
            structural_title = _unpaged_structural_toc_title(normalized_line)
            if structural_title is not None:
                entries.append(
                    {
                        "title": structural_title,
                        "printed_page": None,
                        "role": classify_toc_entry_role(structural_title),
                        "_role_source": _toc_entry_role_source(structural_title),
                    }
                )
            index += 1
            continue
        title = _clean_toc_title(match.group("title"))
        if not title or _is_noise_toc_title(title):
            index += 1
            continue
        entries.append(
            {
                "title": title,
                "printed_page": match.group("page"),
                "role": classify_toc_entry_role(title),
                "_role_source": _toc_entry_role_source(title),
            }
        )
        index += 1
    _apply_toc_sequence_roles(entries)
    for entry in entries:
        entry.pop("_role_source", None)
    return entries


def classify_toc_entry_role(title: str) -> str:
    source = _toc_entry_role_source(title)
    if source == "explicit_back":
        return "back_matter"
    if source == "explicit_body":
        return "body"
    if source == "explicit_front":
        return "front_matter"
    return "body"


def _toc_entry_role_source(title: str) -> str:
    normalized = _normalize_title(title)
    if any(_normalize_title(keyword) in normalized for keyword in BACK_MATTER_TITLE_KEYWORDS):
        return "explicit_back"
    if _looks_like_body_toc_title(title):
        return "explicit_body"
    if any(_normalize_title(keyword) in normalized for keyword in FRONT_MATTER_TITLE_KEYWORDS):
        return "explicit_front"
    return "default"


def _apply_toc_sequence_roles(entries: list[dict[str, Any]]) -> None:
    first_body_index = _first_entry_index(entries, source="explicit_body")
    if first_body_index is not None:
        for entry in entries[:first_body_index]:
            if entry.get("_role_source") != "explicit_back":
                entry["role"] = "front_matter"

    first_back_index = _first_entry_index(entries, source="explicit_back", start=first_body_index)
    if first_back_index is None:
        return

    for entry in entries[first_back_index:]:
        entry["role"] = "back_matter"


def _first_entry_index(
    entries: list[dict[str, Any]], *, source: str, start: int | None = None
) -> int | None:
    start_index = 0 if start is None else start
    for index, entry in enumerate(entries[start_index:], start=start_index):
        if entry.get("_role_source") == source:
            return index
    return None


def _looks_like_body_toc_title(title: str) -> bool:
    stripped = title.strip()
    return BODY_TITLE_RE.match(stripped) is not None or NUMERIC_BODY_TITLE_RE.match(stripped) is not None


def locate_title_pages(
    package: dict[str, Any], title: str, *, exclude_pages: list[int] | None = None
) -> list[int]:
    excluded = set(exclude_pages or [])
    title_key = _normalize_title(title)
    if not title_key:
        return []
    candidates = []
    for record in package["pages"]:
        page = int(record["page"])
        if page in excluded:
            continue
        text = str(record.get("text_snippet") or "")
        page_key = _normalize_title(text)
        if title_key and title_key in page_key:
            candidates.append((page, _title_location_score(record, title_key, text, page_key)))
    return [page for page, _score in sorted(candidates, key=lambda item: (-item[1], item[0]))]


def write_experiment_inputs(
    *,
    book: str,
    observed_path: Path,
    output_dir: Path,
    pdf_path: Path | None = None,
    render_images: bool = True,
) -> dict[str, Any]:
    document = _read_json(observed_path)
    package = build_skeleton_evidence_package(document)
    book_dir = output_dir / book
    book_dir.mkdir(parents=True, exist_ok=True)
    _write_json(book_dir / "evidence_package.json", package)

    selected_pages = _selected_image_pages(package)
    image_manifest = _image_manifest(
        book_dir=book_dir,
        pdf_path=pdf_path,
        selected_pages=selected_pages,
        render_images=render_images,
    )

    observed_input = build_observed_only_input(package)
    hybrid_input = _hybrid_input(package, image_manifest)
    pdf_image_input = _pdf_image_only_input(package, image_manifest)
    toc_driven_input = build_toc_driven_skeleton_plan(document)
    toc_llm_input = build_toc_llm_input(document)
    _write_mode(book_dir, "observed_only", observed_input, _observed_prompt(observed_input))
    _write_mode(book_dir, "hybrid", hybrid_input, _hybrid_prompt(hybrid_input))
    _write_mode(book_dir, "pdf_image_only", pdf_image_input, _pdf_image_prompt(pdf_image_input))
    _write_mode(
        book_dir,
        "toc_driven",
        toc_driven_input,
        _toc_driven_prompt(toc_driven_input),
    )
    _write_mode(book_dir, "toc_llm", toc_llm_input, _toc_llm_prompt(toc_llm_input))
    summary = {
        "book": book,
        "observed_path": str(observed_path),
        "pdf_path": str(pdf_path) if pdf_path else None,
        "output_dir": str(book_dir),
        "page_count": package["page_count"],
        "candidate_page_count": len(package["candidate_pages"]),
        "selected_image_pages": selected_pages,
        "rendered_image_count": len(image_manifest["rendered_images"]),
        "toc_driven_task_count": len(toc_driven_input["llm_page_tasks"]),
        "toc_llm_entry_count": len(toc_llm_input["toc_entries"]),
    }
    _write_json(book_dir / "summary.json", summary)
    return summary


def run_llm_modes(
    book_dir: Path,
    *,
    modes: list[str],
    model: str,
    api_url: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    config = OllamaChatConfig(model=model, api_url=api_url, timeout_seconds=timeout_seconds)
    results: dict[str, Any] = {}
    for mode in modes:
        mode_dir = book_dir / mode
        prompt = (mode_dir / "prompt.md").read_text(encoding="utf-8")
        input_data = _read_json(mode_dir / "input.json")
        image_paths = _image_paths_for_mode(mode, input_data)
        try:
            result, raw_content = _chat_json_raw(config, prompt=prompt, image_paths=image_paths)
        except Exception as exc:
            raw_content = ""
            result = {"_llm_error": str(exc), "_llm_error_type": type(exc).__name__}
            status = "error"
        else:
            status = "written"
        (mode_dir / "llm_raw_response.txt").write_text(raw_content, encoding="utf-8")
        _write_json(mode_dir / "skeleton_proposal.json", result)
        results[mode] = {"status": status, "path": str(mode_dir / "skeleton_proposal.json")}
    return results


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = write_experiment_inputs(
        book=args.book,
        observed_path=args.observed,
        output_dir=args.output_dir,
        pdf_path=args.pdf,
        render_images=not args.no_render_images,
    )
    if args.run_llm:
        summary["llm_results"] = run_llm_modes(
            Path(summary["output_dir"]),
            modes=args.modes,
            model=args.model,
            api_url=args.ollama_url,
            timeout_seconds=args.timeout_seconds,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", required=True)
    parser.add_argument("--observed", required=True, type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--no-render-images", action="store_true")
    parser.add_argument("--run-llm", action="store_true")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["observed_only", "hybrid", "pdf_image_only", "toc_driven", "toc_llm"],
        default=["observed_only", "hybrid", "pdf_image_only"],
    )
    parser.add_argument("--model", default=DEFAULT_QWEN_MODEL)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser


def _metadata(document: dict[str, Any]) -> dict[str, Any]:
    source = document["metadata"]
    return {
        "doc_id": str(source.get("doc_id") or ""),
        "title": str(source.get("title") or ""),
        "language": str(source.get("language") or ""),
        "source_file": str(source.get("source_file") or ""),
        "parser_name": str(source.get("parser_name") or ""),
        "parser_mode": str(source.get("parser_mode") or ""),
    }


def _expected_skeleton_schema() -> dict[str, Any]:
    return {
        "front_matter_ranges": [{"start_page": 1, "end_page": 1, "confidence": 0.0}],
        "body_ranges": [{"start_page": 1, "end_page": 1, "confidence": 0.0}],
        "back_matter_ranges": [{"start_page": 1, "end_page": 1, "confidence": 0.0}],
        "special_pages": [{"page": 1, "role": "cover_page", "confidence": 0.0}],
        "sections": [{"title": "", "kind": "chapter", "start_page": 1, "end_page": 1}],
        "note_ranges": [{"start_page": 1, "end_page": 1, "scope": "book"}],
        "bibliography_ranges": [{"start_page": 1, "end_page": 1}],
        "index_ranges": [{"start_page": 1, "end_page": 1}],
        "uncertain_pages": [{"page": 1, "reason": ""}],
    }


def _expected_toc_llm_schema() -> dict[str, Any]:
    return {
        "entry_roles": [
            {
                "entry_index": 0,
                "role": "front_matter|body|back_matter",
            }
        ],
        "first_body_entry_index": 0,
        "first_body_entry_title": "",
        "last_body_entry_index": 0,
        "last_body_entry_title": "",
        "first_back_matter_entry_index": None,
        "first_back_matter_entry_title": None,
        "uncertain_entries": [{"entry_index": 0, "title": "", "reason": ""}],
    }


def _observations_by_page(observations: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for observation in observations:
        grouped.setdefault(int(observation["page"]), []).append(observation)
    return grouped


def _observed_page_text(document: dict[str, Any], page_number: int) -> str:
    parts = [
        str(observation.get("text") or "").strip()
        for observation in document.get("observations", [])
        if int(observation.get("page") or 0) == page_number
        and observation.get("kind") in TEXT_KINDS
        and str(observation.get("text") or "").strip()
    ]
    return "\n".join(parts)


def _toc_like_line_count(text: str) -> int:
    return sum(
        1
        for line in text.splitlines()
        if TOC_ENTRY_RE.match(_normalize_toc_line(line.strip())) is not None
    )


def _expand_toc_continuation_pages(
    toc_pages: set[int],
    records_by_page: dict[int, dict[str, Any]],
    front_limit: int,
    page_count: int,
) -> set[int]:
    expanded = set(toc_pages)
    for page in sorted(toc_pages):
        next_page = page + 1
        while next_page <= front_limit and next_page in records_by_page:
            record = records_by_page[next_page]
            text = str(record.get("text_snippet") or "")
            if _looks_like_copyright_page(text) or _looks_like_index_page(text, next_page, page_count):
                break
            if _toc_like_line_count(text) < 2:
                break
            expanded.add(next_page)
            next_page += 1
    return expanded


def _looks_like_copyright_page(text: str) -> bool:
    normalized = text.lower()
    markers = ["copyright", "isbn", "cip", "版权所有", "版次", "印次", "定价"]
    return sum(1 for marker in markers if marker in normalized) >= 2


def _looks_like_index_page(text: str, page: int, page_count: int) -> bool:
    if page < round(page_count * 0.75):
        return False
    if "索引" in text[:80]:
        return True
    if "(see also" in text.lower() or "(contd.)" in text.lower() or "—(contd.)" in text:
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    index_like = sum(
        1
        for line in lines
        if re.search(r"\d+\s*(?:[,，、;；]\s*\d+){1,}", line)
        or re.search(r",\s*\d+(?:[–-]\d+)?", line)
    )
    return index_like >= 3


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
    if re.fullmatch(r"[ivxlcdm]+|\d+", normalized):
        return True
    publication_markers = {"copyright", "isbn", "postwave", "publishing", "consulting"}
    return any(marker in normalized for marker in publication_markers)


def _is_standalone_page_label(line: str) -> bool:
    normalized = _normalize_title(_normalize_toc_line(line)).lower()
    return bool(re.fullmatch(r"[ivxlcdm]+|\d+", normalized))


def _unpaged_structural_toc_title(line: str) -> str | None:
    title = _clean_toc_title(line)
    if not title or _is_noise_toc_title(title):
        return None
    if BODY_TITLE_RE.match(title):
        return title
    return None


def _normalize_title(text: str) -> str:
    return re.sub(r"[\s　,，.。:：;；/／\\\-—–·•…《》〈〉（）()【】\[\]]+", "", text)


def _title_location_score(
    record: dict[str, Any],
    title_key: str,
    text: str,
    page_key: str,
) -> float:
    score = 1.0
    role_hint_counts = record.get("role_hint_counts") or {}
    if role_hint_counts.get("title_text", 0) > 0:
        score += 2.0
    if page_key.startswith(title_key):
        score += 1.5
    first_line = _normalize_title(_first_nonempty_line(text))
    if first_line == title_key:
        score += 2.0
    elif first_line.startswith(title_key):
        score += 0.75
    if float(record.get("text_area_ratio") or 0.0) < 0.25:
        score += 0.5
    return score


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _last_located_entry_page(entries: list[dict[str, Any]], *, role: str) -> int | None:
    pages = [
        int(entry["candidate_pages"][0])
        for entry in entries
        if entry.get("role") == role and entry.get("candidate_pages")
    ]
    return max(pages) if pages else None


def _estimated_last_back_entry_end_page(
    package: dict[str, Any], entries: list[dict[str, Any]]
) -> int | None:
    located_back_entries = [
        entry
        for entry in entries
        if entry.get("role") == "back_matter" and entry.get("candidate_pages")
    ]
    if not located_back_entries:
        return None
    last_entry = max(located_back_entries, key=lambda entry: int(entry["candidate_pages"][0]))
    start_page = int(last_entry["candidate_pages"][0])
    if "索引" not in str(last_entry.get("title") or ""):
        return start_page

    page_count = int(package.get("page_count") or len(package.get("pages") or []))
    text_by_page = {
        int(record["page"]): str(record.get("text_snippet") or "")
        for record in package.get("pages", [])
    }
    end_page = start_page
    sorted_pages = sorted(page for page in text_by_page if page > start_page)
    tolerated_gap = 0
    for index, page in enumerate(sorted_pages):
        if _looks_like_index_page(text_by_page[page], page, page_count):
            end_page = page
            tolerated_gap = 0
            continue
        next_page_is_index = any(
            _looks_like_index_page(text_by_page[next_page], next_page, page_count)
            for next_page in sorted_pages[index + 1 : index + 3]
        )
        if tolerated_gap < 1 and next_page_is_index and not _looks_like_copyright_page(text_by_page[page]):
            end_page = page
            tolerated_gap += 1
            continue
        break
    return end_page


def _first_located_entry_page(entries: list[dict[str, Any]]) -> int | None:
    pages = [
        int(entry["candidate_pages"][0])
        for entry in entries
        if entry.get("candidate_pages")
    ]
    return min(pages) if pages else None


def _toc_driven_llm_page_tasks(
    entries: list[dict[str, Any]],
    *,
    toc_pages: list[int],
    page_numbers: list[int],
    first_entry_page: int | None,
    last_back_entry_page: int | None,
) -> list[dict[str, Any]]:
    tasks: dict[int, dict[str, Any]] = {}
    toc_page_set = set(toc_pages)
    if first_entry_page is not None:
        for page in page_numbers:
            if page >= first_entry_page:
                continue
            if page in toc_page_set:
                continue
            tasks[page] = {"page": page, "task": "classify_residual_front_page"}

    for entry in entries:
        if entry["role"] == "body" and _first_body_entry(entries) is not entry:
            continue
        for page in entry.get("candidate_pages", [])[:1]:
            tasks[int(page)] = {
                "page": int(page),
                "task": "verify_toc_entry_page",
                "title": entry["title"],
                "role": entry["role"],
            }

    if last_back_entry_page is not None:
        for page in page_numbers:
            if page > last_back_entry_page:
                tasks.setdefault(page, {"page": page, "task": "classify_residual_back_page"})

    return [tasks[page] for page in sorted(tasks)]


def _first_body_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        if entry.get("role") == "body" and entry.get("candidate_pages"):
            return entry
    return None


def _first_back_matter_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        if entry.get("role") == "back_matter":
            return entry
    return None


def _edge_pages(page_numbers: list[int]) -> dict[int, list[str]]:
    if not page_numbers:
        return {}
    limit = min(EDGE_PAGE_LIMIT, max(4, round(len(page_numbers) * 0.05)))
    first_pages = set(page_numbers[:limit])
    last_pages = set(page_numbers[-limit:])
    signals: dict[int, list[str]] = {}
    for page in first_pages:
        signals.setdefault(page, []).append("early_page")
    for page in last_pages:
        signals.setdefault(page, []).append("late_page")
    signals.setdefault(page_numbers[0], []).append("first_page")
    signals.setdefault(page_numbers[-1], []).append("last_page")
    return signals


def _page_record(
    page: dict[str, Any], observations: list[dict[str, Any]], edge_pages: dict[int, list[str]]
) -> dict[str, Any]:
    page_number = int(page["page"])
    text_observations = [
        observation for observation in observations if observation.get("kind") in TEXT_KINDS
    ]
    visual_observations = [
        observation for observation in observations if observation.get("kind") in VISUAL_KINDS
    ]
    page_area = float(page["width"]) * float(page["height"])
    role_hint_counts = Counter(str(observation.get("role_hint") or "") for observation in observations)
    kind_counts = Counter(str(observation.get("kind") or "") for observation in observations)
    signals = list(edge_pages.get(page_number, []))
    signals.extend(_structural_signals(role_hint_counts, visual_observations, page_area))
    return {
        "page": page_number,
        "width": page["width"],
        "height": page["height"],
        "kind_counts": dict(sorted(kind_counts.items())),
        "role_hint_counts": dict(sorted(role_hint_counts.items())),
        "text_area_ratio": round(_area_ratio(text_observations, page_area), 4),
        "visual_area_ratio": round(_area_ratio(visual_observations, page_area), 4),
        "text_snippet": _page_text_snippet(text_observations),
        "signals": sorted(set(signals)),
    }


def _structural_signals(
    role_hint_counts: Counter[str],
    visual_observations: list[dict[str, Any]],
    page_area: float,
) -> list[str]:
    signals: list[str] = []
    if role_hint_counts.get("toc_text", 0) > 0:
        signals.append("toc_hint")
    if role_hint_counts.get("title_text", 0) > 0:
        signals.append("title_hint")
    if role_hint_counts.get("reference_text", 0) > 0:
        signals.append("reference_hint")
    if role_hint_counts.get("footnote_text", 0) > 0:
        signals.append("footnote_hint")
    if visual_observations:
        signals.append("visual_content")
    if _area_ratio(visual_observations, page_area) >= 0.45:
        signals.append("visual_dominant")
    return signals


def _area_ratio(observations: list[dict[str, Any]], page_area: float) -> float:
    if page_area <= 0:
        return 0.0
    return sum(_bbox_area(observation.get("bbox")) for observation in observations) / page_area


def _bbox_area(bbox: Any) -> float:
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return 0.0
    x0, y0, x1, y1 = [float(value) for value in bbox]
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _page_text_snippet(text_observations: list[dict[str, Any]]) -> str:
    text = "\n".join(
        str(observation.get("text") or "").strip()
        for observation in text_observations
        if str(observation.get("text") or "").strip()
    )
    return text[:MAX_PAGE_TEXT_CHARS]


def _candidate_record(record: dict[str, Any]) -> dict[str, Any] | None:
    signals = [
        signal
        for signal in record["signals"]
        if signal
        in {
            "early_page",
            "late_page",
            "first_page",
            "last_page",
            "toc_hint",
            "title_hint",
            "reference_hint",
            "visual_content",
            "visual_dominant",
            "footnote_hint",
        }
    ]
    if not signals:
        return None
    return {
        "page": record["page"],
        "signals": signals,
        "text_snippet": record["text_snippet"],
        "role_hint_counts": record["role_hint_counts"],
        "kind_counts": record["kind_counts"],
        "text_area_ratio": record["text_area_ratio"],
        "visual_area_ratio": record["visual_area_ratio"],
    }


def _selected_image_pages(package: dict[str, Any]) -> list[int]:
    pages: set[int] = set()
    for record in package["candidate_pages"]:
        signals = set(record["signals"])
        page = int(record["page"])
        edge_or_toc = signals & {"early_page", "late_page", "first_page", "last_page", "toc_hint"}
        sparse_visual = "visual_content" in signals and float(record["text_area_ratio"]) < 0.08
        late_reference = "reference_hint" in signals and "late_page" in signals
        early_title = "title_hint" in signals and bool(signals & {"early_page", "late_page"})
        if edge_or_toc or "visual_dominant" in signals or sparse_visual or late_reference or early_title:
            pages.add(page)
    return sorted(pages)


def _image_manifest(
    *,
    book_dir: Path,
    pdf_path: Path | None,
    selected_pages: list[int],
    render_images: bool,
) -> dict[str, Any]:
    manifest = {
        "pdf_path": str(pdf_path) if pdf_path else None,
        "selected_pages": selected_pages,
        "rendered_images": [],
        "contact_sheets": [],
    }
    if not render_images or pdf_path is None:
        return manifest
    manifest["rendered_images"] = _render_pages(pdf_path, book_dir / "page_images", selected_pages)
    manifest["contact_sheets"] = make_contact_sheets(
        manifest["rendered_images"], book_dir / "contact_sheets"
    )
    return manifest


def _render_pages(pdf_path: Path, output_dir: Path, pages: list[int]) -> list[dict[str, Any]]:
    import fitz  # type: ignore

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    document = fitz.open(pdf_path)
    matrix = fitz.Matrix(120 / 72.0, 120 / 72.0)
    for page_number in pages:
        if page_number < 1 or page_number > len(document):
            continue
        page = document[page_number - 1]
        image_path = output_dir / f"page_{page_number:04d}.png"
        page.get_pixmap(matrix=matrix, alpha=False).save(image_path)
        rendered.append({"page": page_number, "image_path": str(image_path)})
    document.close()
    return rendered


def make_contact_sheets(
    rendered_images: list[dict[str, Any]],
    output_dir: Path,
    *,
    pages_per_sheet: int = 12,
    columns: int = 4,
    thumb_width: int = 260,
) -> list[dict[str, Any]]:
    from PIL import Image, ImageDraw

    if not rendered_images:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    sheets = []
    for sheet_index, group in enumerate(_chunks(rendered_images, pages_per_sheet), start=1):
        thumbs = []
        for item in group:
            image = Image.open(item["image_path"]).convert("RGB")
            scale = thumb_width / image.width
            thumb = image.resize((thumb_width, max(1, int(image.height * scale))))
            thumbs.append((item, thumb))
        rows = (len(thumbs) + columns - 1) // columns
        cell_height = max(thumb.height for _item, thumb in thumbs) + 34
        sheet = Image.new("RGB", (columns * thumb_width, rows * cell_height), "white")
        draw = ImageDraw.Draw(sheet)
        for offset, (item, thumb) in enumerate(thumbs):
            row = offset // columns
            col = offset % columns
            x = col * thumb_width
            y = row * cell_height
            draw.text((x + 6, y + 6), f"PDF page {item['page']}", fill=(0, 0, 0))
            sheet.paste(thumb, (x, y + 28))
        path = output_dir / f"sheet_{sheet_index:02d}.png"
        sheet.save(path)
        sheets.append(
            {
                "sheet": sheet_index,
                "pages": [int(item["page"]) for item, _thumb in thumbs],
                "image_path": str(path),
            }
        )
    return sheets


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def build_observed_only_input(package: dict[str, Any]) -> dict[str, Any]:
    evidence_pages = _selected_evidence_pages(package)
    return {
        "mode": "observed_only",
        "metadata": package["metadata"],
        "page_count": package["page_count"],
        "page_signal_index": _page_signal_index(package),
        "candidate_page_count": len(package["candidate_pages"]),
        "evidence_pages": evidence_pages,
        "expected_output": package["instructions"]["expected_output"],
    }


def _hybrid_input(package: dict[str, Any], image_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "hybrid",
        "metadata": package["metadata"],
        "page_count": package["page_count"],
        "page_signal_index": _page_signal_index(package),
        "candidate_page_count": len(package["candidate_pages"]),
        "evidence_pages": _selected_evidence_pages(package),
        "image_manifest": image_manifest,
        "expected_output": package["instructions"]["expected_output"],
    }


def _pdf_image_only_input(package: dict[str, Any], image_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "pdf_image_only",
        "metadata": package["metadata"],
        "page_count": package["page_count"],
        "image_manifest": image_manifest,
        "expected_output": package["instructions"]["expected_output"],
    }


def _page_signal_index(package: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"page": int(record["page"]), "signals": list(record["signals"])}
        for record in package["pages"]
        if _include_in_signal_index(record)
    ]


def _selected_evidence_pages(package: dict[str, Any]) -> list[dict[str, Any]]:
    selected = set(_selected_image_pages(package))
    for record in package["candidate_pages"]:
        signals = set(record["signals"])
        if signals & {"toc_hint", "reference_hint", "first_page", "last_page"}:
            selected.add(int(record["page"]))
    by_page = {int(record["page"]): record for record in package["candidate_pages"]}
    return [by_page[page] for page in sorted(selected) if page in by_page]


def _include_in_signal_index(record: dict[str, Any]) -> bool:
    signals = set(record["signals"])
    stable_signals = signals - {"footnote_hint"}
    return bool(
        stable_signals
        & {
            "early_page",
            "late_page",
            "first_page",
            "last_page",
            "toc_hint",
            "reference_hint",
            "visual_dominant",
        }
    )


def _write_mode(book_dir: Path, mode: str, input_data: dict[str, Any], prompt: str) -> None:
    mode_dir = book_dir / mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    _write_json(mode_dir / "input.json", input_data)
    (mode_dir / "prompt.md").write_text(prompt, encoding="utf-8")


def _observed_prompt(input_data: dict[str, Any]) -> str:
    return _prompt(
        "Use only the structured ObservedDocument-derived evidence below.",
        input_data,
    )


def _hybrid_prompt(input_data: dict[str, Any]) -> str:
    return _prompt(
        "Use the structured evidence below and any provided page images as visual tie-breakers.",
        input_data,
    )


def _pdf_image_prompt(input_data: dict[str, Any]) -> str:
    return _prompt(
        "Use the provided page images as the primary evidence. Do not infer from BookGraph nodes.",
        input_data,
    )


def _toc_driven_prompt(input_data: dict[str, Any]) -> str:
    return _prompt(
        "Use the table-of-contents-derived tasks below. Verify only the listed pages; do not infer unrelated pages.",
        input_data,
    )


def _toc_llm_prompt(input_data: dict[str, Any]) -> str:
    return _prompt(
        "Use only the table of contents to classify TOC entries into front_matter, "
        "body, and back_matter. Do not classify TOC entries with hard-coded title "
        "word lists. Identify first_body_entry_index, last_body_entry_index, and "
        "first_back_matter_entry_index by reading TOC order and structure. Keep the "
        "JSON compact: entry_roles must contain only entry_index and role; do not "
        "include per-entry explanations unless an entry is uncertain. Treat conclusion "
        "or epilogue-style argumentative closing entries as body when they precede "
        "notes, bibliography, index, afterword, or other back matter. Never choose a "
        "numbered chapter as first_back_matter_entry; numbered chapters remain body "
        "even when they appear near the end of the TOC.",
        input_data,
    )


def _prompt(instruction: str, input_data: dict[str, Any]) -> str:
    compact_json = json.dumps(input_data, ensure_ascii=False, separators=(",", ":"))
    if len(compact_json) > MAX_PROMPT_JSON_CHARS:
        compact_json = compact_json[:MAX_PROMPT_JSON_CHARS] + "...TRUNCATED"
    return (
        "You are identifying the high-level skeleton of a scanned history book.\n"
        f"{instruction}\n"
        "Return strict JSON matching expected_output keys. Use PDF physical page numbers.\n"
        "Never return an empty object. If uncertain, fill uncertain_pages with reasons.\n"
        "Do not create, delete, or rename logical content items.\n\n"
        f"INPUT_JSON:\n{compact_json}\n"
    )


def _image_paths_for_mode(mode: str, input_data: dict[str, Any]) -> list[Path]:
    if mode == "observed_only":
        return []
    manifest = input_data.get("image_manifest") if isinstance(input_data, dict) else {}
    images = manifest.get("contact_sheets") if isinstance(manifest, dict) else []
    if not images and isinstance(manifest, dict):
        images = manifest.get("rendered_images")
    return [
        Path(item["image_path"])
        for item in images
        if isinstance(item, dict) and item.get("image_path")
    ]


def parse_llm_json_content(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = extract_json_value(content)
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        parsed = parsed[0]
    elif isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        parsed = {"items": parsed}
    if isinstance(parsed, dict) and parsed:
        return parsed
    return {"_parse_error": "llm_response_not_json", "_raw_content": content[:4000]}


def _chat_json_raw(
    config: OllamaChatConfig, *, prompt: str, image_paths: list[Path]
) -> tuple[dict[str, Any], str]:
    images = [base64.b64encode(path.read_bytes()).decode("ascii") for path in image_paths[:32]]
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt, "images": images}],
        "think": config.think,
        "stream": False,
        "keep_alive": config.keep_alive,
        "format": "json",
        "options": config.options,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        config.api_url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = ((body.get("message") or {}).get("content") or body.get("response") or "").strip()
    return parse_llm_json_content(content), content


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
