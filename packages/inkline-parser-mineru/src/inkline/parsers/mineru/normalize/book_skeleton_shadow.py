from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from inkline.canonical import (
    book_skeleton_toc_llm_prompt,
    build_book_skeleton_from_observed,
    build_book_skeleton_toc_llm_input,
)
from inkline.llm import (
    DEFAULT_OLLAMA_CHAT_URL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    DEFAULT_QWEN_MODEL,
    OllamaChatConfig,
    chat_json,
)

BOOK_SKELETON_LLM_NUM_PREDICT = 8192


def build_book_skeleton_shadow(
    observed: dict[str, Any],
    *,
    use_llm: bool = False,
    source_pdf: str | Path | None = None,
    image_output_dir: str | Path | None = None,
    llm_model: str = DEFAULT_QWEN_MODEL,
    llm_api_url: str = DEFAULT_OLLAMA_CHAT_URL,
    llm_timeout_seconds: int = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if not use_llm:
        return build_book_skeleton_from_observed(observed)
    llm_input = build_book_skeleton_toc_llm_input(observed)
    image_paths = _toc_image_paths(
        source_pdf=source_pdf,
        toc_pages=llm_input["toc_pages"],
        image_output_dir=image_output_dir,
    )
    messages = [_llm_message(book_skeleton_toc_llm_prompt(llm_input), image_paths)]
    llm_result = chat_json(
        _llm_config(llm_model, llm_api_url, llm_timeout_seconds),
        messages=messages,
    )
    if isinstance(llm_result.get("toc_entries"), list):
        return build_book_skeleton_from_observed(
            observed,
            llm_toc_entries=llm_result["toc_entries"],
            llm_uncertain_entries=llm_result.get("uncertain_entries"),
            llm_model=llm_model,
            llm_source="toc_image_llm" if image_paths else "toc_llm_entries",
        )
    return build_book_skeleton_from_observed(
        observed,
        llm_classification=llm_result,
        llm_model=llm_model,
        llm_source="toc_llm",
    )


def _llm_config(model: str, api_url: str, timeout_seconds: int) -> OllamaChatConfig:
    defaults = OllamaChatConfig(
        model=model,
        api_url=api_url,
        timeout_seconds=timeout_seconds,
    )
    return OllamaChatConfig(
        model=model,
        api_url=api_url,
        timeout_seconds=timeout_seconds,
        keep_alive=defaults.keep_alive,
        response_format=defaults.response_format,
        think=defaults.think,
        stream=defaults.stream,
        options={**defaults.options, "num_predict": BOOK_SKELETON_LLM_NUM_PREDICT},
    )


def _toc_image_paths(
    *,
    source_pdf: str | Path | None,
    toc_pages: list[int],
    image_output_dir: str | Path | None,
) -> list[Path]:
    if source_pdf is None or not toc_pages:
        return []
    output_dir = Path(image_output_dir) if image_output_dir else Path.cwd() / "book_skeleton_toc_llm_pages"
    return _render_toc_page_images(Path(source_pdf), toc_pages, output_dir)


def _llm_message(prompt: str, image_paths: list[Path]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "user", "content": prompt}
    if image_paths:
        message["images"] = [
            base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
            for image_path in image_paths
        ]
    return message


def _render_toc_page_images(
    pdf_path: Path, toc_pages: list[int], output_dir: Path
) -> list[Path]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError("TOC LLM image extraction requires PyMuPDF (`fitz`).") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    document = fitz.open(pdf_path)
    matrix = fitz.Matrix(120 / 72.0, 120 / 72.0)
    try:
        for page_number in toc_pages:
            if page_number < 1 or page_number > len(document):
                continue
            image_path = output_dir / f"toc_page_{page_number:04d}.png"
            document[page_number - 1].get_pixmap(matrix=matrix, alpha=False).save(image_path)
            rendered.append(image_path)
    finally:
        document.close()
    return rendered
