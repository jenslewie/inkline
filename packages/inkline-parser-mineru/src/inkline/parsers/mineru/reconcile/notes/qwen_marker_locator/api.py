"""Qwen marker-locator API adapter and response cleaning.

The generic Ollama request handling lives in ``inkline.llm``. This module keeps
the marker-locator public entry point and all note-marker-specific
cleaning/validation helpers.
"""

from __future__ import annotations

import urllib.error
from typing import Any, Dict, List, Optional

from inkline.llm import vision_chat_json

from ....extraction.text import normalize_note_marker
from . import types as qwen_types


def _call_qwen_marker_locator(image_path: Any, config: qwen_types.QwenMarkerLocatorConfig, *, prompt: str) -> Dict[str, Any]:
    try:
        parsed = vision_chat_json(image_path, config.locator_model_config().to_ollama_config(), prompt=prompt)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(f"Qwen marker locator model `{config.model}` is not available. Run `ollama pull {config.model}`.") from exc
        raise
    if isinstance(parsed.get("items"), list):
        return {"body_refs": parsed["items"]}
    return parsed if isinstance(parsed, dict) else {}


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
        cleaned: Dict[str, Any] = {
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
