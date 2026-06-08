"""Qwen model API interaction and response cleaning for the marker locator.

Contains the Ollama API call, JSON extraction fallback, and all response
cleaning/validation helpers.  Uses module-level import from ``qwen_types``
so that monkeypatching works correctly (patch the definition module namespace).
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ...extraction.text import normalize_note_marker
from . import qwen_types


def _call_qwen_marker_locator(image_path: Any, config: qwen_types.QwenMarkerLocatorConfig, *, prompt: str) -> Dict[str, Any]:
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        "format": "json",
        "think": False,
        "stream": False,
        "keep_alive": config.keep_alive,
        "options": {
            "temperature": 0,
            "presence_penalty": 0,
            "frequency_penalty": 0,
            "repeat_penalty": 1,
            "num_predict": 2048,
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(config.api_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(f"Qwen marker locator model `{config.model}` is not available. Run `ollama pull {config.model}`.") from exc
        raise
    except OSError as exc:
        raise RuntimeError(f"Cannot connect to Qwen marker locator endpoint {config.api_url}: {exc}") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Qwen marker locator endpoint returned non-JSON output.") from exc
    content = ((result.get("message") or {}).get("content") or result.get("response") or "").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = _extract_json_value(content)
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        parsed = parsed[0]
    elif isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        parsed = {"body_refs": parsed}
    return parsed if isinstance(parsed, dict) else {}


def _extract_json_value(text: str) -> Any:
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


def _clean_body_refs(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        marker = _clean_marker(item.get("marker"))
        if not marker:
            continue
        cleaned = {
            "marker": marker,
            "before_text": str(item.get("before_text") or ""),
            "after_text": str(item.get("after_text") or ""),
            "quote": str(item.get("quote") or ""),
            "confidence": _clean_confidence(item.get("confidence")),
        }
        for key in ("block_id", "body_ref_source", "crop_image"):
            val = item.get(key)
            if val:
                cleaned[key] = str(val)
        crop_bbox = item.get("crop_bbox_pdf")
        if isinstance(crop_bbox, list) and len(crop_bbox) >= 4:
            cleaned["crop_bbox_pdf"] = [float(v) for v in crop_bbox[:4]]
        out.append(cleaned)
    return out


def _clean_footnote_defs(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        cleaned = _clean_footnote_def(item)
        if cleaned is not None:
            out.append(cleaned)
    return out


def _clean_footnote_def(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    marker = _clean_marker(item.get("marker"))
    if not marker:
        return None
    return {
        "marker": marker,
        "near_text": str(item.get("near_text") or ""),
        "confidence": _clean_confidence(item.get("confidence")),
    }


def _clean_marker(value: Any) -> str:
    marker = normalize_note_marker(str(value or "").strip().replace("＊", "*"))
    return marker if qwen_types._VALID_MARKER_RE.match(marker) else ""


def _clean_confidence(value: Any) -> str:
    text = str(value or "").lower()
    return text if text in {"high", "medium", "low"} else "medium"