"""Build Phase 4A page-review artifacts from observed parser evidence."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from dataclasses import dataclass
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
    page_review_llm_prompt,
    page_review_prompt_profile,
)
from inkline.llm import (
    DEFAULT_OLLAMA_CHAT_URL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    DEFAULT_QWEN_MODEL,
    OllamaChatConfig,
    chat_json,
)

PAGE_REVIEW_LLM_NUM_PREDICT = 1024
PAGE_REVIEW_IMAGE_DPI = 96
PAGE_REVIEW_IMAGE_EVIDENCE_VERSION = "3-one-page-full-resolution"
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
    request_pages = _prepare_llm_review_pages(plan, page_records)
    if not request_pages:
        return plan
    checkpoint = _load_page_review_checkpoint(
        runtime.checkpoint_path,
        plan=plan,
        request_pages=request_pages,
        llm_model=runtime.llm_model,
    )
    if checkpoint is not None and checkpoint["checkpoint"]["status"] == "complete":
        review = checkpoint.get("resolved_page_review")
        if not isinstance(review, dict):
            raise ValueError("completed page review checkpoint lacks resolved_page_review")
        validate_resolved_page_review(review)
        return review
    page_decisions = _resolve_pending_pages(
        plan,
        request_pages,
        page_records,
        checkpoint,
        runtime,
    )
    decisions = [page_decisions[page] for page in sorted(request_pages)]
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
            request_pages,
            runtime.llm_model,
            page_decisions,
            status="complete",
            resolved_page_review=review,
        ),
    )
    return review


def _prepare_llm_review_pages(
    plan: dict[str, Any], page_records: dict[int, dict[str, Any]]
) -> dict[int, dict[str, str]]:
    """Create a resumable two-pass review plan for pre-body pages.

    The first pass handles visually suspicious pages selected by layout. The second
    pass closes the remaining pre-body gap left before the earliest TOC-localized
    front-matter section, so an ordinary text leaf cannot silently remain unknown.
    """

    initial_pages = set(plan["candidate_pages"])
    request_pages = {
        page: {
            "matter": _page_review_matter(page_records[page]),
            "prompt_profile": page_review_prompt_profile(page_records[page]),
        }
        for page in sorted(initial_pages)
    }

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
        request_pages[page] = {
            "matter": "pre_body",
            "prompt_profile": "front_residual_unknown",
        }
    for page, request in request_pages.items():
        page_records[page]["llm_prompt_profile"] = request["prompt_profile"]
    plan["candidate_pages"] = sorted(initial_pages | set(residual_pages))
    return request_pages


def _is_pre_body_unknown(record: dict[str, Any]) -> bool:
    context = record.get("skeleton_context")
    return (
        isinstance(context, dict)
        and context.get("matter") == "pre_body"
        and record.get("book_block_position") == "unknown"
    )


def _page_review_matter(record: dict[str, Any]) -> str:
    context = record.get("skeleton_context")
    if isinstance(context, dict):
        matter = context.get("matter")
        if matter in {"pre_body", "body", "back_matter"}:
            return str(matter)
    return "unknown"


def _resolve_pending_pages(
    plan: dict[str, Any],
    request_pages: dict[int, dict[str, str]],
    page_records: dict[int, dict[str, Any]],
    checkpoint: dict[str, Any] | None,
    runtime: _PageReviewRuntime,
) -> dict[int, dict[str, Any]]:
    page_decisions = _checkpoint_page_decisions(checkpoint)
    unfinished_pages = [page for page in sorted(request_pages) if page not in page_decisions]
    image_paths = _render_page_images(runtime.source_pdf, unfinished_pages, runtime.image_output_dir)
    for page in unfinished_pages:
        _resolve_request_page(
            plan,
            page,
            request_pages[page],
            page_records,
            image_paths,
            request_pages,
            checkpoint,
            runtime,
            page_decisions,
        )
    return page_decisions


def _resolve_request_page(
    plan: dict[str, Any],
    page: int,
    request: dict[str, str],
    page_records: dict[int, dict[str, Any]],
    image_paths: dict[int, Path],
    request_pages: dict[int, dict[str, str]],
    checkpoint: dict[str, Any] | None,
    runtime: _PageReviewRuntime,
    page_decisions: dict[int, dict[str, Any]],
) -> None:
    image_path = image_paths.get(page)
    if image_path is None:
        error = RuntimeError(f"page review image missing page: {page}")
        _record_checkpoint_failure(runtime.checkpoint_path, checkpoint, page, error, page_decisions)
        raise error
    payload = {
        "first_body_page": plan["first_body_page"],
        "pages": [_llm_page_payload(page_records[page])],
    }
    preceding = page_decisions.get(page - 1)
    if preceding is not None:
        payload["preceding_page_decision"] = {
            "page": page - 1,
            "book_block_position": preceding.get("book_block_position"),
            "special_page_kind": preceding.get("special_page_kind"),
        }
    result: dict[str, Any] | None = None
    try:
        prompt_profile = _effective_prompt_profile(request["prompt_profile"], preceding)
        page_records[page]["llm_prompt_profile"] = prompt_profile
        result = chat_json(
            _llm_config(runtime.llm_model, runtime.llm_api_url, runtime.llm_timeout_seconds),
            messages=_llm_messages(
                page_review_llm_prompt(payload, profile=prompt_profile),
                page,
                image_path,
            ),
        )
        reviewed = result.get("page_reviews")
        if not isinstance(reviewed, list):
            raise ValueError("page review LLM response missing page_reviews")
        validated = validate_page_review_decisions(reviewed, [page])
        page_decisions[page] = {"page": page, **validated[page]}
        _write_page_review_checkpoint(
            runtime.checkpoint_path,
            _checkpoint_payload(
                plan,
                request_pages,
                runtime.llm_model,
                page_decisions,
                status="in_progress",
            ),
        )
    except Exception as exc:
        _record_checkpoint_failure(
            runtime.checkpoint_path,
            checkpoint,
            page,
            exc,
            page_decisions,
            raw_response=result,
        )
        raise


def _effective_prompt_profile(
    default_profile: str, preceding_page_decision: dict[str, Any] | None
) -> str:
    """Add only bounded prior identity context to a single-page visual review."""

    if preceding_page_decision is None:
        return default_profile
    preceding_kind = preceding_page_decision.get("special_page_kind")
    if default_profile == "front_visual_identity" and preceding_kind == "front_exterior_page":
        return "after_front_exterior"
    if default_profile == "front_visual_identity" and preceding_kind == "back_exterior_page":
        return "after_back_exterior"
    if default_profile == "front_visual_identity" and preceding_kind == "dust_jacket_spread":
        return "after_dust_jacket_spread"
    if default_profile == "front_visual_identity" and preceding_kind == "decorative_preliminary_page":
        return "after_decorative_preliminary"
    if default_profile == "front_visual_identity" and preceding_kind == "title_page":
        return "after_title_page"

    return default_profile


def _load_page_review_checkpoint(
    checkpoint_path: str | Path | None,
    *,
    plan: dict[str, Any],
    request_pages: dict[int, dict[str, str]],
    llm_model: str,
) -> dict[str, Any] | None:
    if checkpoint_path is None:
        return None
    path = Path(checkpoint_path)
    if not path.exists():
        return _checkpoint_payload(plan, request_pages, llm_model, {}, status="in_progress")
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"page review checkpoint is not valid JSON: {path}") from exc
    expected = _checkpoint_fingerprint(plan, request_pages, llm_model)
    if checkpoint.get("fingerprint") != expected:
        _archive_stale_page_review_checkpoint(path)
        fresh_checkpoint = _checkpoint_payload(plan, request_pages, llm_model, {}, status="in_progress")
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


def _checkpoint_page_decisions(checkpoint: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if checkpoint is None:
        return {}
    raw_pages = checkpoint.get("page_decisions")
    if not isinstance(raw_pages, dict):
        raise ValueError("page review checkpoint page_decisions must be an object")
    decisions: dict[int, dict[str, Any]] = {}
    for raw_page, decision in raw_pages.items():
        if not isinstance(raw_page, str) or not raw_page.isdigit() or not isinstance(decision, dict):
            raise ValueError("page review checkpoint has invalid page decisions")
        decisions[int(raw_page)] = decision
    return decisions


def _record_checkpoint_failure(
    checkpoint_path: str | Path | None,
    checkpoint: dict[str, Any] | None,
    page: int,
    error: Exception,
    page_decisions: dict[int, dict[str, Any]] | None = None,
    raw_response: dict[str, Any] | None = None,
) -> None:
    if checkpoint_path is None or checkpoint is None:
        return
    decisions = page_decisions if page_decisions is not None else _checkpoint_page_decisions(checkpoint)
    payload = deepcopy(checkpoint)
    payload["page_decisions"] = {str(key): value for key, value in decisions.items()}
    payload["checkpoint"] = {
        "status": "failed",
        "completed_pages": sorted(decisions),
        "failed_page": page,
        "error": str(error),
    }
    payload["failed_group_response"] = raw_response
    _write_page_review_checkpoint(checkpoint_path, payload)


def _checkpoint_payload(
    plan: dict[str, Any],
    request_pages: dict[int, dict[str, str]],
    llm_model: str,
    page_decisions: dict[int, dict[str, Any]],
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
        "fingerprint": _checkpoint_fingerprint(plan, request_pages, llm_model),
        "checkpoint": {
            "status": status,
            "completed_pages": sorted(page_decisions),
            "failed_page": None,
            "error": None,
        },
        "page_decisions": {str(page): decision for page, decision in page_decisions.items()},
    }
    if resolved_page_review is not None:
        payload["resolved_page_review"] = resolved_page_review
    return payload


def _checkpoint_fingerprint(
    plan: dict[str, Any], request_pages: dict[int, dict[str, str]], llm_model: str
) -> dict[str, Any]:
    return {
        "doc_id": plan["metadata"]["doc_id"],
        "page_review_schema_version": plan["metadata"]["schema_version"],
        "page_review_prompt_version": PAGE_REVIEW_PROMPT_VERSION,
        "page_review_image_evidence_version": PAGE_REVIEW_IMAGE_EVIDENCE_VERSION,
        "candidate_pages": plan["candidate_pages"],
        "request_pages": {str(page): request_pages[page] for page in sorted(request_pages)},
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
    page: int,
    page_image_path: Path,
) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": (
                f"The attached image is physical PDF page {page}. Classify only this page and use "
                f"{page} as the page value in the required JSON.\n\n"
                f"{prompt}"
            ),
            "images": [base64.b64encode(page_image_path.read_bytes()).decode("ascii")],
        }
    ]


def _llm_page_payload(page_record: dict[str, Any]) -> dict[str, Any]:
    """Expose structural evidence to the LLM without leaking a provisional decision."""

    return {
        "page": page_record["page"],
        "skeleton_context": deepcopy(page_record.get("skeleton_context") or {}),
        "signals": deepcopy(page_record.get("signals") or []),
        "visual_kinds": deepcopy(page_record.get("visual_kinds") or []),
    }


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
