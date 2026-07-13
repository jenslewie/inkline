"""Build Phase 4A page-review artifacts from observed parser evidence."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any

from inkline.canonical import (
    audit_text_unit_layout,
    build_page_review_plan,
    build_text_units,
    classify_observed_page_roles,
    resolve_page_review,
    validate_page_review_decisions,
    validate_resolved_page_review,
)
from inkline.canonical.page_review.llm import page_review_groups, page_review_llm_prompt
from inkline.llm import (
    DEFAULT_OLLAMA_CHAT_URL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    DEFAULT_QWEN_MODEL,
    OllamaChatConfig,
    chat_json,
)

PAGE_REVIEW_LLM_NUM_PREDICT = 1024
PAGE_REVIEW_MAX_GROUP_PAGES = 4
PAGE_REVIEW_IMAGE_DPI = 96
PAGE_REVIEW_CONTACT_SHEET_COLUMNS = 2
PAGE_REVIEW_CONTACT_SHEET_TILE_WIDTH = 480
PAGE_REVIEW_CONTACT_SHEET_TILE_HEIGHT = 680
PAGE_REVIEW_CONTACT_SHEET_LABEL_HEIGHT = 32


@dataclass(frozen=True)
class _PageReviewRuntime:
    source_pdf: Path
    image_output_dir: Path
    llm_model: str
    llm_api_url: str
    llm_timeout_seconds: int
    checkpoint_path: str | Path | None


def build_page_review_shadow(
    observed: dict[str, Any],
    skeleton: dict[str, Any],
    *,
    use_llm: bool = False,
    source_pdf: str | Path | None = None,
    image_output_dir: str | Path | None = None,
    llm_model: str = DEFAULT_QWEN_MODEL,
    llm_api_url: str = DEFAULT_OLLAMA_CHAT_URL,
    llm_timeout_seconds: int = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    checkpoint_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic plan, then resolve only selected pages with the LLM."""

    text_units, _ignored_counts = build_text_units(observed)
    layout_audit = audit_text_unit_layout(text_units, observed["pages"], observed["observations"])
    page_roles = classify_observed_page_roles(observed, layout_audit=layout_audit)
    plan = build_page_review_plan(observed, skeleton, page_roles)
    if not use_llm or not plan["candidate_pages"]:
        return plan
    if source_pdf is None:
        raise ValueError("page review LLM requires source_pdf")
    output_dir = (
        Path(image_output_dir)
        if image_output_dir is not None
        else Path.cwd() / "page_review_llm_pages"
    )
    return _resolve_with_llm(
        plan,
        _PageReviewRuntime(
            source_pdf=Path(source_pdf),
            image_output_dir=output_dir,
            llm_model=llm_model,
            llm_api_url=llm_api_url,
            llm_timeout_seconds=llm_timeout_seconds,
            checkpoint_path=checkpoint_path,
        ),
    )


def _resolve_with_llm(
    plan: dict[str, Any],
    runtime: _PageReviewRuntime,
) -> dict[str, Any]:
    page_records = {int(record["page"]): record for record in plan["pages"]}
    groups = page_review_groups(plan["candidate_pages"], max_pages=PAGE_REVIEW_MAX_GROUP_PAGES)
    request_groups = _record_llm_request_groups(page_records, groups)
    plan["llm_request_groups"] = request_groups
    checkpoint = _load_page_review_checkpoint(
        runtime.checkpoint_path,
        plan=plan,
        request_groups=request_groups,
        llm_model=runtime.llm_model,
    )
    if checkpoint is not None and checkpoint["checkpoint"]["status"] == "complete":
        review = checkpoint.get("resolved_page_review")
        if not isinstance(review, dict):
            raise ValueError("completed page review checkpoint lacks resolved_page_review")
        validate_resolved_page_review(review)
        return review
    group_decisions = _resolve_pending_groups(
        plan,
        request_groups,
        page_records,
        checkpoint,
        runtime,
    )
    decisions = [
        decision
        for request_group in request_groups
        for decision in group_decisions[str(request_group["group_id"])]
    ]
    review = resolve_page_review(plan, decisions, llm_model=runtime.llm_model)
    _write_page_review_checkpoint(
        runtime.checkpoint_path,
        _checkpoint_payload(
            plan,
            request_groups,
            runtime.llm_model,
            group_decisions,
            status="complete",
            resolved_page_review=review,
        ),
    )
    return review


def _resolve_pending_groups(
    plan: dict[str, Any],
    request_groups: list[dict[str, Any]],
    page_records: dict[int, dict[str, Any]],
    checkpoint: dict[str, Any] | None,
    runtime: _PageReviewRuntime,
) -> dict[str, list[dict[str, Any]]]:
    group_decisions = _checkpoint_group_decisions(checkpoint)
    unfinished_groups = [
        request_group
        for request_group in request_groups
        if str(request_group["group_id"]) not in group_decisions
    ]
    unfinished_pages = [
        page for request_group in unfinished_groups for page in request_group["pages"]
    ]
    image_paths = _render_page_images(runtime.source_pdf, unfinished_pages, runtime.image_output_dir)
    contact_sheets = _render_contact_sheets(unfinished_groups, image_paths, runtime.image_output_dir)
    for request_group in unfinished_groups:
        _resolve_request_group(
            plan,
            request_group,
            page_records,
            image_paths,
            contact_sheets,
            request_groups,
            checkpoint,
            runtime,
            group_decisions,
        )
    return group_decisions


def _resolve_request_group(
    plan: dict[str, Any],
    request_group: dict[str, Any],
    page_records: dict[int, dict[str, Any]],
    image_paths: dict[int, Path],
    contact_sheets: dict[str, Path],
    request_groups: list[dict[str, Any]],
    checkpoint: dict[str, Any] | None,
    runtime: _PageReviewRuntime,
    group_decisions: dict[str, list[dict[str, Any]]],
) -> None:
    group_id = str(request_group["group_id"])
    group = list(request_group["pages"])
    missing_images = [page for page in group if page not in image_paths]
    if missing_images:
        error = RuntimeError(f"page review images missing pages: {missing_images}")
        _record_checkpoint_failure(
            runtime.checkpoint_path, checkpoint, group_id, error, group_decisions
        )
        raise error
    payload = {
        "first_body_page": plan["first_body_page"],
        "pages": [page_records[page] for page in group],
    }
    try:
        result = chat_json(
            _llm_config(runtime.llm_model, runtime.llm_api_url, runtime.llm_timeout_seconds),
            messages=_llm_messages(page_review_llm_prompt(payload), group, contact_sheets[group_id]),
        )
        reviewed = result.get("page_reviews")
        if not isinstance(reviewed, list):
            raise ValueError("page review LLM response missing page_reviews")
        validated = validate_page_review_decisions(reviewed, group)
        group_decisions[group_id] = [{"page": page, **decision} for page, decision in validated.items()]
        _write_page_review_checkpoint(
            runtime.checkpoint_path,
            _checkpoint_payload(
                plan,
                request_groups,
                runtime.llm_model,
                group_decisions,
                status="in_progress",
            ),
        )
    except Exception as exc:
        _record_checkpoint_failure(
            runtime.checkpoint_path, checkpoint, group_id, exc, group_decisions
        )
        raise


def _load_page_review_checkpoint(
    checkpoint_path: str | Path | None,
    *,
    plan: dict[str, Any],
    request_groups: list[dict[str, Any]],
    llm_model: str,
) -> dict[str, Any] | None:
    if checkpoint_path is None:
        return None
    path = Path(checkpoint_path)
    if not path.exists():
        return _checkpoint_payload(plan, request_groups, llm_model, {}, status="in_progress")
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"page review checkpoint is not valid JSON: {path}") from exc
    expected = _checkpoint_fingerprint(plan, request_groups, llm_model)
    if checkpoint.get("fingerprint") != expected:
        raise ValueError("page review checkpoint does not match the current review plan")
    return checkpoint


def _checkpoint_group_decisions(checkpoint: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    if checkpoint is None:
        return {}
    raw_groups = checkpoint.get("group_decisions")
    if not isinstance(raw_groups, dict):
        raise ValueError("page review checkpoint group_decisions must be an object")
    decisions: dict[str, list[dict[str, Any]]] = {}
    for group_id, group_items in raw_groups.items():
        if not isinstance(group_id, str) or not isinstance(group_items, list):
            raise ValueError("page review checkpoint has invalid group decisions")
        decisions[group_id] = group_items
    return decisions


def _record_checkpoint_failure(
    checkpoint_path: str | Path | None,
    checkpoint: dict[str, Any] | None,
    group_id: str,
    error: Exception,
    group_decisions: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    if checkpoint_path is None or checkpoint is None:
        return
    decisions = group_decisions if group_decisions is not None else _checkpoint_group_decisions(checkpoint)
    payload = deepcopy(checkpoint)
    payload["group_decisions"] = decisions
    payload["checkpoint"] = {
        "status": "failed",
        "completed_group_ids": sorted(decisions),
        "failed_group_id": group_id,
        "error": str(error),
    }
    _write_page_review_checkpoint(checkpoint_path, payload)


def _checkpoint_payload(
    plan: dict[str, Any],
    request_groups: list[dict[str, Any]],
    llm_model: str,
    group_decisions: dict[str, list[dict[str, Any]]],
    *,
    status: str,
    resolved_page_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "metadata": {
            "schema_name": "inkline_page_review_checkpoint",
            "schema_version": "0.1-shadow",
            "doc_id": plan["metadata"]["doc_id"],
            "title": plan["metadata"]["title"],
        },
        "fingerprint": _checkpoint_fingerprint(plan, request_groups, llm_model),
        "checkpoint": {
            "status": status,
            "completed_group_ids": sorted(group_decisions),
            "failed_group_id": None,
            "error": None,
        },
        "group_decisions": group_decisions,
    }
    if resolved_page_review is not None:
        payload["resolved_page_review"] = resolved_page_review
    return payload


def _checkpoint_fingerprint(
    plan: dict[str, Any], request_groups: list[dict[str, Any]], llm_model: str
) -> dict[str, Any]:
    return {
        "doc_id": plan["metadata"]["doc_id"],
        "candidate_pages": plan["candidate_pages"],
        "request_groups": request_groups,
        "llm_model": llm_model,
    }


def _write_page_review_checkpoint(
    checkpoint_path: str | Path | None, payload: dict[str, Any]
) -> None:
    if checkpoint_path is None:
        return
    path = Path(checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def _record_llm_request_groups(
    page_records: dict[int, dict[str, Any]], groups: list[list[int]]
) -> list[dict[str, Any]]:
    requests = []
    for index, pages in enumerate(groups, start=1):
        group_id = f"g{index:04d}"
        requests.append({"group_id": group_id, "pages": pages})
        for page in pages:
            page_records[page]["llm_group_id"] = group_id
    return requests


def _llm_config(model: str, api_url: str, timeout_seconds: int) -> OllamaChatConfig:
    defaults = OllamaChatConfig(model=model, api_url=api_url, timeout_seconds=timeout_seconds)
    return OllamaChatConfig(
        model=model,
        api_url=api_url,
        timeout_seconds=timeout_seconds,
        keep_alive=defaults.keep_alive,
        response_format=defaults.response_format,
        think=defaults.think,
        stream=defaults.stream,
        options={**defaults.options, "num_predict": PAGE_REVIEW_LLM_NUM_PREDICT, "seed": 0},
    )


def _llm_messages(
    prompt: str, pages: list[int], contact_sheet_path: Path
) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": (
                "This contact sheet contains only the selected candidate pages. "
                f"Its physical pages are {pages}; each tile is labeled with its physical page number. "
                "Use those labels as the page values in the required JSON.\n\n"
                f"{prompt}"
            ),
            "images": [base64.b64encode(contact_sheet_path.read_bytes()).decode("ascii")],
        }
    ]


def _render_contact_sheets(
    request_groups: list[dict[str, Any]], image_paths: dict[int, Path], output_dir: Path
) -> dict[str, Path]:
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional runtime
        raise RuntimeError("page review contact sheets require Pillow.") from exc

    sheets: dict[str, Path] = {}
    for request_group in request_groups:
        group_id = str(request_group["group_id"])
        pages = [int(page) for page in request_group["pages"]]
        rows = ceil(len(pages) / PAGE_REVIEW_CONTACT_SHEET_COLUMNS)
        sheet = Image.new(
            "RGB",
            (
                PAGE_REVIEW_CONTACT_SHEET_COLUMNS * PAGE_REVIEW_CONTACT_SHEET_TILE_WIDTH,
                rows * (PAGE_REVIEW_CONTACT_SHEET_LABEL_HEIGHT + PAGE_REVIEW_CONTACT_SHEET_TILE_HEIGHT),
            ),
            "white",
        )
        draw = ImageDraw.Draw(sheet)
        for index, page in enumerate(pages):
            column = index % PAGE_REVIEW_CONTACT_SHEET_COLUMNS
            row = index // PAGE_REVIEW_CONTACT_SHEET_COLUMNS
            x = column * PAGE_REVIEW_CONTACT_SHEET_TILE_WIDTH
            y = row * (PAGE_REVIEW_CONTACT_SHEET_LABEL_HEIGHT + PAGE_REVIEW_CONTACT_SHEET_TILE_HEIGHT)
            draw.text((x + 8, y + 8), f"PDF page {page}", fill="black")
            with Image.open(image_paths[page]) as source:
                tile = source.convert("RGB")
                tile.thumbnail(
                    (PAGE_REVIEW_CONTACT_SHEET_TILE_WIDTH, PAGE_REVIEW_CONTACT_SHEET_TILE_HEIGHT)
                )
                tile_x = x + (PAGE_REVIEW_CONTACT_SHEET_TILE_WIDTH - tile.width) // 2
                tile_y = y + PAGE_REVIEW_CONTACT_SHEET_LABEL_HEIGHT
                sheet.paste(tile, (tile_x, tile_y))
        sheet_path = output_dir / f"group_{group_id}.jpg"
        sheet.save(sheet_path, format="JPEG", quality=85, optimize=True)
        sheets[group_id] = sheet_path
    return sheets


def _render_page_images(
    pdf_path: Path, pages: list[int], output_dir: Path
) -> dict[int, Path]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional runtime
        raise RuntimeError("page review image extraction requires PyMuPDF (`fitz`).") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: dict[int, Path] = {}
    document = fitz.open(pdf_path)
    matrix = fitz.Matrix(PAGE_REVIEW_IMAGE_DPI / 72.0, PAGE_REVIEW_IMAGE_DPI / 72.0)
    try:
        for page in pages:
            if page < 1 or page > len(document):
                continue
            image_path = output_dir / f"page_{page:04d}.png"
            document[page - 1].get_pixmap(matrix=matrix, alpha=False).save(image_path)
            rendered[page] = image_path
    finally:
        document.close()
    return rendered
