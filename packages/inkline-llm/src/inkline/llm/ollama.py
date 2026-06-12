"""Small Ollama chat helpers shared by parser and RAG workflows."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


DEFAULT_QWEN_MODEL = "qwen3.6:35b-a3b"
DEFAULT_OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 180
DEFAULT_OLLAMA_KEEP_ALIVE = "2h"


@dataclass(frozen=True)
class OllamaChatConfig:
    model: str
    api_url: str = DEFAULT_OLLAMA_CHAT_URL
    timeout_seconds: int = DEFAULT_OLLAMA_TIMEOUT_SECONDS
    keep_alive: str = DEFAULT_OLLAMA_KEEP_ALIVE
    response_format: str | None = "json"
    think: bool = False
    stream: bool = False
    options: dict[str, Any] = field(
        default_factory=lambda: {
            "temperature": 0,
            "presence_penalty": 0,
            "frequency_penalty": 0,
            "repeat_penalty": 1,
            "num_predict": 2048,
        }
    )


def vision_chat_json(image_path: str | Path, config: OllamaChatConfig, *, prompt: str) -> dict[str, Any]:
    image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return chat_json(
        config,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
    )


def vision_chat_text(image_path: str | Path, config: OllamaChatConfig, *, prompt: str) -> str:
    image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return chat_text(
        config,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
    )


def chat_text(config: OllamaChatConfig, *, messages: list[dict[str, Any]]) -> str:
    body = _chat_response(replace(config, response_format=None), messages=messages)
    return ((body.get("message") or {}).get("content") or body.get("response") or "").strip()


def chat_json(config: OllamaChatConfig, *, messages: list[dict[str, Any]]) -> dict[str, Any]:
    body = _chat_response(replace(config, response_format="json"), messages=messages)
    content = ((body.get("message") or {}).get("content") or body.get("response") or "").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = extract_json_value(content)
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        parsed = parsed[0]
    elif isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        parsed = {"items": parsed}
    return parsed if isinstance(parsed, dict) else {}


def _chat_response(config: OllamaChatConfig, *, messages: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "think": config.think,
        "stream": config.stream,
        "keep_alive": config.keep_alive,
        "options": config.options,
    }
    if config.response_format is not None:
        payload["format"] = config.response_format

    return _post_json(config.api_url, payload, timeout_seconds=config.timeout_seconds)


def extract_json_value(text: str) -> Any:
    candidates = []
    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start >= 0 and object_end > object_start:
        candidates.append(text[object_start : object_end + 1])
    list_start = text.find("[")
    list_end = text.rfind("]")
    if list_start >= 0 and list_end > list_start:
        candidates.append(text[list_start : list_end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {}


def _post_json(api_url: str, payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(api_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError:
        raise
    except OSError as exc:
        raise RuntimeError(f"Cannot connect to Ollama endpoint {api_url}: {exc}") from exc
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama endpoint returned non-JSON output.") from exc
    return parsed if isinstance(parsed, dict) else {}
