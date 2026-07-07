from __future__ import annotations

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


def build_book_skeleton_shadow(
    observed: dict[str, Any],
    *,
    use_llm: bool = False,
    llm_model: str = DEFAULT_QWEN_MODEL,
    llm_api_url: str = DEFAULT_OLLAMA_CHAT_URL,
    llm_timeout_seconds: int = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if not use_llm:
        return build_book_skeleton_from_observed(observed)
    llm_input = build_book_skeleton_toc_llm_input(observed)
    llm_classification = chat_json(
        OllamaChatConfig(
            model=llm_model,
            api_url=llm_api_url,
            timeout_seconds=llm_timeout_seconds,
        ),
        messages=[{"role": "user", "content": book_skeleton_toc_llm_prompt(llm_input)}],
    )
    return build_book_skeleton_from_observed(
        observed,
        llm_classification=llm_classification,
        llm_model=llm_model,
        llm_source="toc_llm",
    )
