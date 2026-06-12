"""Shared local LLM clients for inkline."""

from .ollama import (
    DEFAULT_OLLAMA_CHAT_URL,
    DEFAULT_OLLAMA_KEEP_ALIVE,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    DEFAULT_QWEN_MODEL,
    OllamaChatConfig,
    chat_json,
    chat_text,
    extract_json_value,
    vision_chat_json,
    vision_chat_text,
)

__all__ = [
    "DEFAULT_OLLAMA_CHAT_URL",
    "DEFAULT_OLLAMA_KEEP_ALIVE",
    "DEFAULT_OLLAMA_TIMEOUT_SECONDS",
    "DEFAULT_QWEN_MODEL",
    "OllamaChatConfig",
    "chat_json",
    "chat_text",
    "extract_json_value",
    "vision_chat_json",
    "vision_chat_text",
]
