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
from inkline.canonical.page_review.llm import (
    PAGE_REVIEW_PROMPT_VERSION,
    page_review_groups,
    page_review_llm_prompt,
    page_review_profile_groups,
)
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
PAGE_REVIEW_IMAGE_EVIDENCE_VERSION = "2-targeted-full-resolution"
PAGE_REVIEW_ROUTING_RASTER_SCALE = 0.25
PAGE_REVIEW_DARK_PIXEL_LUMA = 180
PAGE_REVIEW_DARK_PIXEL_RATIO = 0.35


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
    if source_pdf is not None and Path(source_pdf).is_file():
        page_roles = _add_pre_body_raster_visual_signals(
            page_roles, skeleton, Path(source_pdf)
        )
    plan = build_page_review_plan(observed, skeleton, page_roles)
    if not use_llm:
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


def _add_pre_body_raster_visual_signals(
    page_roles: list[dict[str, Any]], skeleton: dict[str, Any], source_pdf: Path
) -> list[dict[str, Any]]:
    """Route visually dark pre-body pages even when MinerU emitted only text regions.

    This is a thumbnail-level routing signal, not a page classification. The LLM still
    decides whether the page is external wrap, book front matter, or ordinary text.
    """

    first_body_page = _first_body_page(skeleton)
    if first_body_page is None or first_body_page <= 1:
        return page_roles
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - PyMuPDF is an optional runtime dependency.
        raise RuntimeError("page review visual routing requires PyMuPDF (`fitz`).") from exc

    augmented = deepcopy(page_roles)
    with fitz.open(source_pdf) as document:
        for record in augmented:
            page = record.get("page")
            if not isinstance(page, int) or page < 1 or page >= first_body_page:
                continue
            if page > len(document) or not _has_dark_raster_layout(document[page - 1]):
                continue
            signals = record.setdefault("signals", [])
            if "raster_dark_visual_layout" not in signals:
                signals.append("raster_dark_visual_layout")
    return augmented


def _first_body_page(skeleton: dict[str, Any]) -> int | None:
    boundaries = skeleton.get("boundaries")
    if not isinstance(boundaries, dict):
        return None
    value = boundaries.get("first_body_page")
    return value if isinstance(value, int) and value > 0 else None


def _has_dark_raster_layout(page: Any) -> bool:
    """Detect a large non-paper field from a low-cost grayscale-equivalent thumbnail."""

    import fitz  # type: ignore

    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(PAGE_REVIEW_ROUTING_RASTER_SCALE, PAGE_REVIEW_ROUTING_RASTER_SCALE),
        alpha=False,
    )
    samples = pixmap.samples
    channels = pixmap.n
    if not samples or channels < 3:
        return False
    dark_pixels = 0
    pixel_count = pixmap.width * pixmap.height
    for index in range(0, len(samples), channels):
        # Integer luma approximation, avoiding a Pillow dependency for routing.
        luma = (77 * samples[index] + 150 * samples[index + 1] + 29 * samples[index + 2]) // 256
        if luma < PAGE_REVIEW_DARK_PIXEL_LUMA:
            dark_pixels += 1
    return pixel_count > 0 and dark_pixels / pixel_count >= PAGE_REVIEW_DARK_PIXEL_RATIO


def _resolve_with_llm(
    plan: dict[str, Any],
    runtime: _PageReviewRuntime,
) -> dict[str, Any]:
    page_records = {int(record["page"]): record for record in plan["pages"]}
    groups = _prepare_llm_review_groups(plan, page_records)
    if not groups:
        return plan
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
    review = resolve_page_review(
        plan,
        decisions,
        llm_model=runtime.llm_model,
        llm_prompt_version=PAGE_REVIEW_PROMPT_VERSION,
    )
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


def _prepare_llm_review_groups(
    plan: dict[str, Any], page_records: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Create a resumable two-pass review plan for pre-body pages.

    The first pass handles visually suspicious pages selected by layout. The second
    pass closes the remaining pre-body gap left before the earliest TOC-localized
    front-matter section, so an ordinary text leaf cannot silently remain unknown.
    """

    initial_candidates = list(plan["candidate_pages"])
    initial_groups = page_review_profile_groups(
        initial_candidates, page_records, max_pages=PAGE_REVIEW_MAX_GROUP_PAGES
    )
    for group in initial_groups:
        group["review_stage"] = "initial_visual"

    initial_pages = set(initial_candidates)
    residual_pages = [
        page
        for page, record in sorted(page_records.items())
        if page not in initial_pages
        and _is_pre_body_unknown(record)
    ]
    for page in residual_pages:
        record = page_records[page]
        record["text_flow_action"] = "needs_review"
        record["visual_asset_action"] = "needs_review"
        record["decision_source"] = "llm_page_review"
        record["llm_review_status"] = "pending"

    residual_groups = [
        {
            "matter": "pre_body",
            "prompt_profile": "front_residual_unknown",
            "pages": pages,
            "review_stage": "residual_unknown",
        }
        for pages in page_review_groups(
            residual_pages, max_pages=PAGE_REVIEW_MAX_GROUP_PAGES
        )
    ]
    plan["candidate_pages"] = sorted(initial_pages | set(residual_pages))
    return initial_groups + residual_groups


def _is_pre_body_unknown(record: dict[str, Any]) -> bool:
    context = record.get("skeleton_context")
    return (
        isinstance(context, dict)
        and context.get("matter") == "pre_body"
        and record.get("book_block_position") == "unknown"
    )


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
        "pages": [_llm_page_payload(page_records[page]) for page in group],
    }
    result: dict[str, Any] | None = None
    try:
        full_resolution_pages = _full_resolution_pages(group, page_records)
        prompt_profile = str(request_group["prompt_profile"])
        result = chat_json(
            _llm_config(runtime.llm_model, runtime.llm_api_url, runtime.llm_timeout_seconds),
            messages=_llm_messages(
                page_review_llm_prompt(payload, profile=prompt_profile),
                group,
                contact_sheets[group_id],
                image_paths,
                full_resolution_pages,
            ),
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
            runtime.checkpoint_path,
            checkpoint,
            group_id,
            exc,
            group_decisions,
            raw_response=result,
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
        _archive_stale_page_review_checkpoint(path)
        fresh_checkpoint = _checkpoint_payload(plan, request_groups, llm_model, {}, status="in_progress")
        _write_page_review_checkpoint(path, fresh_checkpoint)
        return fresh_checkpoint
    return checkpoint


def _archive_stale_page_review_checkpoint(path: Path) -> None:
    """Preserve an obsolete plan checkpoint before restarting review."""

    stale_path = path.with_name(f"{path.name}.stale")
    index = 1
    while stale_path.exists():
        stale_path = path.with_name(f"{path.name}.stale.{index}")
        index += 1
    path.replace(stale_path)


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
    raw_response: dict[str, Any] | None = None,
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
    payload["failed_group_response"] = raw_response
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
        "page_review_schema_version": plan["metadata"]["schema_version"],
        "page_review_prompt_version": PAGE_REVIEW_PROMPT_VERSION,
        "page_review_image_evidence_version": PAGE_REVIEW_IMAGE_EVIDENCE_VERSION,
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
    page_records: dict[int, dict[str, Any]], groups: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    requests = []
    for index, group in enumerate(groups, start=1):
        group_id = f"g{index:04d}"
        pages = list(group["pages"])
        matter = str(group["matter"])
        prompt_profile = str(group["prompt_profile"])
        review_stage = str(group["review_stage"])
        requests.append(
            {
                "group_id": group_id,
                "matter": matter,
                "pages": pages,
                "prompt_profile": prompt_profile,
                "review_stage": review_stage,
            }
        )
        for page in pages:
            page_records[page]["llm_group_id"] = group_id
            page_records[page]["llm_prompt_profile"] = prompt_profile
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
    prompt: str,
    pages: list[int],
    contact_sheet_path: Path,
    page_image_paths: dict[int, Path],
    full_resolution_pages: list[int],
) -> list[dict[str, Any]]:
    images = [base64.b64encode(contact_sheet_path.read_bytes()).decode("ascii")]
    for page in full_resolution_pages:
        images.append(base64.b64encode(page_image_paths[page].read_bytes()).decode("ascii"))
    evidence_note = "No additional full-resolution page images are attached."
    if full_resolution_pages:
        evidence_note = (
            "Additional full-resolution images are attached for physical pages "
            f"{full_resolution_pages}, in that exact order."
        )
    return [
        {
            "role": "user",
            "content": (
                "The first image is a contact sheet containing only the selected candidate pages. "
                f"Its physical pages are {pages}; each tile is labeled with its physical page number. "
                f"{evidence_note} "
                "Use those labels as the page values in the required JSON.\n\n"
                f"{prompt}"
            ),
            "images": images,
        }
    ]


def _full_resolution_pages(
    pages: list[int], page_records: dict[int, dict[str, Any]]
) -> list[int]:
    """Attach readable evidence only where structure or layout leaves real ambiguity."""

    return [page for page in pages if _needs_full_resolution_image(page_records[page])]


def _needs_full_resolution_image(page_record: dict[str, Any]) -> bool:
    context = page_record.get("skeleton_context")
    if isinstance(context, dict):
        if context.get("matter") == "pre_body":
            return True
        if context.get("is_body_section_start") is True:
            return True
    signals = page_record.get("signals") or []
    visual_kinds = page_record.get("visual_kinds") or []
    return bool(
        {"visual_verifier_candidate", "visual_sparse_text"} & set(signals)
        or "image_region" in visual_kinds
        or "table_region" in visual_kinds
    )


def _llm_page_payload(page_record: dict[str, Any]) -> dict[str, Any]:
    """Expose structural evidence to the LLM without leaking a provisional decision."""

    return {
        "page": page_record["page"],
        "skeleton_context": deepcopy(page_record.get("skeleton_context") or {}),
        "signals": deepcopy(page_record.get("signals") or []),
        "visual_kinds": deepcopy(page_record.get("visual_kinds") or []),
    }


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
