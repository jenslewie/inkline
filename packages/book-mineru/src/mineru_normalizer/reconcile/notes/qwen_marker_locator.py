"""Qwen visual marker locator evidence for problematic note pages.

MinerU remains the primary parser. This module renders selected full pages,
asks a local Ollama-hosted Qwen visual model for structured marker evidence,
and applies only footnote-definition marker fixes before note ref recovery.
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ...extraction.text import normalize_note_marker, normalize_ws
from ..block_access import block_bbox, block_page
from .glm_ocr import _problem_page_plan
from .keys import leading_note_marker

_BODY_REFS_PROMPT = (
    "/no_think\n"
    "只返回JSON，不要解释。只在脚注分隔横线以上的正文区域识别脚注引用marker，不要识别页底脚注定义。"
    "marker只允许数字或*,**,***。正文marker必须是小号上标或紧贴正文的脚注符号。"
    "before_text必须是marker左侧紧邻的2到8个原文字符，并以marker左边那个字符结尾；"
    "after_text必须是marker右侧紧邻的2到8个原文字符，并以marker右边那个字符开头。"
    "如果marker右边紧邻句号、逗号等标点，after_text必须以该标点开头；如果marker左边紧邻标点，before_text必须以该标点结尾。"
    "quote必须等于连续原文片段 before_text + marker + after_text，多个marker相邻时必须保留相对位置。"
    "格式:"
    "{\"body_refs\":[{\"marker\":\"\",\"before_text\":\"\",\"after_text\":\"\",\"quote\":\"\",\"confidence\":\"high|medium|low\"}]}。"
    "看不清或无法确定紧邻字符就省略该项。"
)
_FOOTNOTE_DEFS_PROMPT = (
    "/no_think\n"
    "只返回JSON，不要解释。只识别页底脚注列表，不要识别正文。"
    "请从脚注分隔横线下方开始，逐行列出所有脚注定义开头的marker，包括星号*,**,***和数字1,2,3。"
    "特别注意：数字脚注1之前如果还有一条星号脚注，也必须列出。"
    "输出格式:"
    "{\"footnote_defs\":[{\"marker\":\"\",\"near_text\":\"\",\"confidence\":\"high|medium|low\"}]}。"
    "near_text填写该脚注marker后面的开头文字。"
    "看不清或无法确定紧邻字符就省略该项。"
)
_PROMPT_VERSION = 2
_VALID_MARKER_RE = re.compile(r"^(?:\d{1,3}|\*{1,3})$")


@dataclass(frozen=True)
class QwenMarkerLocatorConfig:
    source_pdf: Path
    artifact_dir: Path
    model: str = "qwen3.5:9b"
    api_url: str = "http://127.0.0.1:11434/api/chat"
    dpi: int = 300
    max_megapixels: float = 0.0
    body_prompt: str = _BODY_REFS_PROMPT
    footnote_prompt: str = _FOOTNOTE_DEFS_PROMPT
    reuse_evidence: bool = False
    timeout_seconds: int = 180
    timing_log_path: Path | None = None


@dataclass
class QwenMarkerPageEvidence:
    page: int
    image: str
    crop_bbox_pdf: List[float]
    dpi: int
    raw_json: Dict[str, Any]
    body_refs: List[Dict[str, Any]] = field(default_factory=list)
    footnote_defs: List[Dict[str, Any]] = field(default_factory=list)
    prompt_version: int = _PROMPT_VERSION

    @property
    def kind(self) -> str:
        return "full_page"

    def to_json(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "kind": self.kind,
            "image": self.image,
            "crop_bbox_pdf": self.crop_bbox_pdf,
            "dpi": self.dpi,
            "raw_json": self.raw_json,
            "body_refs": self.body_refs,
            "footnote_defs": self.footnote_defs,
            "prompt_version": self.prompt_version,
        }


def run_qwen_marker_locator_repairs(blocks: List[Dict[str, Any]], config: QwenMarkerLocatorConfig) -> List[QwenMarkerPageEvidence]:
    """Collect Qwen marker evidence and apply footnote-definition marker fixes."""

    plan = _problem_page_plan(blocks)
    pages = set(plan.footnote_pages) | set(plan.body_ref_pages)
    if not pages:
        return []
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    _reset_timing_log(config)
    run_started = _now_iso()
    run_timer = time.perf_counter()
    _write_timing_event(
        config,
        {
            "event": "run_start",
            "started_at": run_started,
            "model": config.model,
            "dpi": config.dpi,
            "reuse_evidence": config.reuse_evidence,
            "source_pdf": str(config.source_pdf),
            "artifact_dir": str(config.artifact_dir),
            "planned_pages": sorted(pages),
            "footnote_pages": sorted(plan.footnote_pages),
            "body_ref_pages": sorted(plan.body_ref_pages),
        },
    )
    evidence = _collect_qwen_marker_evidence(
        sorted(pages),
        config,
        pass_name="initial",
        footnote_pages=plan.footnote_pages,
        body_ref_pages=plan.body_ref_pages,
        expected_body_markers_by_page=_page_footnote_markers_by_page(blocks),
    )
    apply_qwen_footnote_markers(blocks, evidence)

    body_plan = _problem_page_plan(blocks)
    missing_pages = sorted(set(body_plan.body_ref_pages) - set(plan.body_ref_pages))
    if missing_pages:
        evidence.extend(
            _collect_qwen_marker_evidence(
                missing_pages,
                config,
                pass_name="body_ref_retry",
                footnote_pages=set(),
                body_ref_pages=set(missing_pages),
                expected_body_markers_by_page=_page_footnote_markers_by_page(blocks),
            )
        )
    _write_evidence(config.artifact_dir / "qwen_marker_evidence.json", evidence)
    _write_timing_event(
        config,
        {
            "event": "run_end",
            "started_at": run_started,
            "finished_at": _now_iso(),
            "duration_seconds": _duration(run_timer),
            "evidence_items": len(evidence),
            "unique_pages": sorted({item.page for item in evidence}),
            "evidence_path": str(config.artifact_dir / "qwen_marker_evidence.json"),
        },
    )
    return evidence


def apply_qwen_footnote_markers(blocks: List[Dict[str, Any]], evidence_pages: Sequence[QwenMarkerPageEvidence]) -> None:
    evidence_by_page = {item.page: item for item in evidence_pages}
    for page, page_blocks in _page_footnotes_by_page(blocks).items():
        evidence = evidence_by_page.get(page)
        if evidence is None:
            continue
        defs = [_clean_footnote_def(item) for item in evidence.footnote_defs]
        defs = [item for item in defs if item is not None]
        if not defs:
            continue
        if len(defs) == len(page_blocks) and _footnote_defs_match_blocks(defs, page_blocks):
            for block, item in zip(page_blocks, defs):
                _apply_qwen_footnote_marker(block, item["marker"], page, evidence=evidence)
            continue
        _apply_unique_near_text_matches(page_blocks, defs, page, evidence)


def _collect_qwen_marker_evidence(
    pages: Sequence[int],
    config: QwenMarkerLocatorConfig,
    *,
    pass_name: str,
    footnote_pages: set[int] | None = None,
    body_ref_pages: set[int] | None = None,
    expected_body_markers_by_page: Dict[int, List[str]] | None = None,
) -> List[QwenMarkerPageEvidence]:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("Qwen marker locator page rendering requires PyMuPDF (`fitz`).") from exc

    cache = _read_existing_evidence(config.artifact_dir / "qwen_marker_evidence.json") if config.reuse_evidence else {}
    evidence: List[QwenMarkerPageEvidence] = []
    footnote_pages = set() if footnote_pages is None else footnote_pages
    body_ref_pages = set(pages) if body_ref_pages is None else body_ref_pages
    expected_body_markers_by_page = expected_body_markers_by_page or {}
    pass_started = _now_iso()
    pass_timer = time.perf_counter()
    _write_timing_event(
        config,
        {
            "event": "collect_pass_start",
            "pass": pass_name,
            "started_at": pass_started,
            "pages": list(pages),
            "footnote_pages": sorted(footnote_pages),
            "body_ref_pages": sorted(body_ref_pages),
        },
    )
    with fitz.open(config.source_pdf) as doc:
        for page in pages:
            if page < 1 or page > doc.page_count:
                _write_timing_event(
                    config,
                    {
                        "event": "page_skipped",
                        "pass": pass_name,
                        "page": page,
                        "reason": "outside_pdf_page_range",
                        "page_count": doc.page_count,
                        "finished_at": _now_iso(),
                    },
                )
                continue
            page_started = _now_iso()
            page_timer = time.perf_counter()
            render_duration = 0.0
            model_calls: List[Dict[str, Any]] = []
            pdf_page = doc[page - 1]
            image_path = config.artifact_dir / f"page_{page:04d}_{config.dpi}dpi_qwen_full_page.png"
            render_timer = time.perf_counter()
            try:
                _render_full_page(pdf_page, image_path, config)
            except Exception as exc:
                _write_timing_event(
                    config,
                    {
                        "event": "page_error",
                        "pass": pass_name,
                        "page": page,
                        "stage": "render",
                        "started_at": page_started,
                        "finished_at": _now_iso(),
                        "duration_seconds": _duration(page_timer),
                        "render_seconds": _duration(render_timer),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                raise
            render_duration = _duration(render_timer)
            item = cache.get((page, image_path.name))
            cache_hit = item is not None
            if item is None:
                raw_parts: Dict[str, Any] = {}
                if page in footnote_pages:
                    call_timer = time.perf_counter()
                    call_started = _now_iso()
                    try:
                        footnote_raw = _call_qwen_marker_locator(image_path, config, prompt=config.footnote_prompt)
                    except Exception as exc:
                        model_calls.append(
                            {
                                "kind": "footnote_defs",
                                "started_at": call_started,
                                "finished_at": _now_iso(),
                                "duration_seconds": _duration(call_timer),
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            }
                        )
                        _write_timing_event(
                            config,
                            {
                                "event": "page_error",
                                "pass": pass_name,
                                "page": page,
                                "stage": "footnote_defs",
                                "started_at": page_started,
                                "finished_at": _now_iso(),
                                "duration_seconds": _duration(page_timer),
                                "render_seconds": render_duration,
                                "cache_hit": cache_hit,
                                "image": str(image_path),
                                "model_calls": model_calls,
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            },
                        )
                        raise
                    model_calls.append(
                        {
                            "kind": "footnote_defs",
                            "started_at": call_started,
                            "finished_at": _now_iso(),
                            "duration_seconds": _duration(call_timer),
                            "raw_item_count": len(footnote_raw.get("footnote_defs") or []) if isinstance(footnote_raw, dict) else 0,
                        }
                    )
                    raw_parts["footnote_defs"] = footnote_raw.get("footnote_defs") if isinstance(footnote_raw, dict) else []
                if page in body_ref_pages:
                    marker_items = _clean_footnote_defs(raw_parts.get("footnote_defs"))
                    markers = _body_markers_for_prompt(marker_items, expected_body_markers_by_page.get(page, []))
                    call_timer = time.perf_counter()
                    call_started = _now_iso()
                    try:
                        body_raw = _call_qwen_marker_locator(image_path, config, prompt=_body_prompt_for_markers(config.body_prompt, markers))
                    except Exception as exc:
                        model_calls.append(
                            {
                                "kind": "body_refs",
                                "started_at": call_started,
                                "finished_at": _now_iso(),
                                "duration_seconds": _duration(call_timer),
                                "markers_for_prompt": markers,
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            }
                        )
                        _write_timing_event(
                            config,
                            {
                                "event": "page_error",
                                "pass": pass_name,
                                "page": page,
                                "stage": "body_refs",
                                "started_at": page_started,
                                "finished_at": _now_iso(),
                                "duration_seconds": _duration(page_timer),
                                "render_seconds": render_duration,
                                "cache_hit": cache_hit,
                                "image": str(image_path),
                                "model_calls": model_calls,
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            },
                        )
                        raise
                    model_calls.append(
                        {
                            "kind": "body_refs",
                            "started_at": call_started,
                            "finished_at": _now_iso(),
                            "duration_seconds": _duration(call_timer),
                            "markers_for_prompt": markers,
                            "raw_item_count": len(body_raw.get("body_refs") or []) if isinstance(body_raw, dict) else 0,
                        }
                    )
                    raw_parts["body_refs"] = body_raw.get("body_refs") if isinstance(body_raw, dict) else []
                item = QwenMarkerPageEvidence(
                    page=page,
                    image=str(image_path),
                    crop_bbox_pdf=[float(pdf_page.rect.x0), float(pdf_page.rect.y0), float(pdf_page.rect.x1), float(pdf_page.rect.y1)],
                    dpi=config.dpi,
                    raw_json=raw_parts,
                    body_refs=_clean_body_refs(raw_parts.get("body_refs")),
                    footnote_defs=_clean_footnote_defs(raw_parts.get("footnote_defs")),
                )
            evidence.append(item)
            _write_timing_event(
                config,
                {
                    "event": "page_end",
                    "pass": pass_name,
                    "page": page,
                    "started_at": page_started,
                    "finished_at": _now_iso(),
                    "duration_seconds": _duration(page_timer),
                    "render_seconds": render_duration,
                    "cache_hit": cache_hit,
                    "image": str(image_path),
                    "image_bytes": image_path.stat().st_size if image_path.exists() else None,
                    "requested_footnote_defs": page in footnote_pages,
                    "requested_body_refs": page in body_ref_pages,
                    "model_calls": model_calls,
                    "footnote_def_count": len(item.footnote_defs),
                    "body_ref_count": len(item.body_refs),
                },
            )
    _write_timing_event(
        config,
        {
            "event": "collect_pass_end",
            "pass": pass_name,
            "started_at": pass_started,
            "finished_at": _now_iso(),
            "duration_seconds": _duration(pass_timer),
            "evidence_items": len(evidence),
        },
    )
    return evidence


def _body_prompt_for_markers(default_prompt: str, markers: Sequence[str]) -> str:
    markers = [marker for marker in markers if marker]
    if not markers:
        return default_prompt
    marker_list = ", ".join(dict.fromkeys(markers))
    return (
        "/no_think\n"
        f"只返回JSON，不要解释。只在脚注分隔横线以上的正文区域定位这些脚注上标marker：{marker_list}。"
        "排除页底脚注列表，不要输出脚注定义行开头的marker。不要根据脚注意义推测，只看正文里真实印刷的小号上标或星号。"
        "请逐个marker查找，能确定就输出，不能确定就省略。"
        "特别注意：如果某个marker印在句号/逗号等标点之后，before_text必须包含这个标点并以这个标点结尾，after_text从标点后的正文开始；"
        "如果marker印在标点之前，after_text必须以这个标点开头。"
        "输出格式:{\"body_refs\":[{\"marker\":\"\",\"before_text\":\"\",\"after_text\":\"\",\"quote\":\"\",\"confidence\":\"high|medium|low\"}]}。"
        "before_text和after_text都必须是紧邻marker的2到8个原文字符，不要输出超过8个字符的before_text或after_text。"
        "quote必须是before_text+marker+after_text的连续原文片段。"
        "多个marker相邻时，quote必须保留相对位置。"
    )


def _body_markers_for_prompt(footnote_defs: Sequence[Dict[str, Any]], expected_markers: Sequence[str]) -> List[str]:
    markers = [str(item.get("marker") or "") for item in footnote_defs]
    return list(dict.fromkeys([marker for marker in [*markers, *expected_markers] if marker]))


def _render_full_page(pdf_page: Any, image_path: Path, config: QwenMarkerLocatorConfig) -> None:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("Qwen marker locator page rendering requires PyMuPDF (`fitz`).") from exc
    scale = config.dpi / 72
    megapixels = max(1, int(pdf_page.rect.width * scale)) * max(1, int(pdf_page.rect.height * scale)) / 1_000_000
    if config.max_megapixels > 0 and megapixels > config.max_megapixels:
        raise RuntimeError(f"Refusing Qwen marker locator image {image_path.name} ({megapixels:.1f}MP) above max {config.max_megapixels}MP.")
    pix = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    if pix.width <= 0 or pix.height <= 0:
        raise RuntimeError(f"Invalid Qwen marker locator image dimensions for {image_path.name}: {pix.width}x{pix.height}.")
    pix.save(str(image_path))


def _call_qwen_marker_locator(image_path: Path, config: QwenMarkerLocatorConfig, *, prompt: str) -> Dict[str, Any]:
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
        "keep_alive": "0s",
        "options": {"temperature": 0, "num_predict": 2048},
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
        out.append(
            {
                "marker": marker,
                "before_text": str(item.get("before_text") or ""),
                "after_text": str(item.get("after_text") or ""),
                "quote": str(item.get("quote") or ""),
                "confidence": _clean_confidence(item.get("confidence")),
            }
        )
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
    return marker if _VALID_MARKER_RE.match(marker) else ""


def _clean_confidence(value: Any) -> str:
    text = str(value or "").lower()
    return text if text in {"high", "medium", "low"} else "medium"


def _footnote_defs_match_blocks(defs: Sequence[Dict[str, Any]], blocks: Sequence[Dict[str, Any]]) -> bool:
    return all(_footnote_def_matches_block(item, block) for item, block in zip(defs, blocks))


def _apply_unique_near_text_matches(
    page_blocks: Sequence[Dict[str, Any]],
    defs: Sequence[Dict[str, Any]],
    page: int,
    evidence: QwenMarkerPageEvidence,
) -> None:
    used_blocks: set[int] = set()
    for item in defs:
        candidates = [
            (index, block)
            for index, block in enumerate(page_blocks)
            if index not in used_blocks and _footnote_def_matches_block(item, block)
        ]
        if len(candidates) != 1:
            continue
        index, block = candidates[0]
        _apply_qwen_footnote_marker(block, item["marker"], page, evidence=evidence)
        used_blocks.add(index)


def _footnote_def_matches_block(item: Dict[str, Any], block: Dict[str, Any]) -> bool:
    marker = str(item.get("marker") or "")
    existing = normalize_note_marker((block.get("attrs") or {}).get("note_marker", "")) or leading_note_marker(str(block.get("text") or ""), include_superscript=True)
    if existing and existing != marker:
        return False
    near_text = _strip_leading_marker(str(item.get("near_text") or ""))
    block_text = _strip_leading_marker(str(block.get("text") or ""))
    if not near_text:
        return True
    return _text_similarity(near_text, block_text) >= 0.18


def _apply_qwen_footnote_marker(block: Dict[str, Any], marker: str, page: int, *, evidence: QwenMarkerPageEvidence) -> None:
    existing = leading_note_marker(str(block.get("text") or ""), include_superscript=True)
    if not existing:
        separator = "" if marker.startswith("*") else ". "
        block["text"] = f"{marker}{separator}{str(block.get('text') or '').lstrip()}"
    attrs = block.setdefault("attrs", {})
    attrs["note_marker"] = marker
    attrs["note_marker_source"] = "qwen_marker_locator"
    attrs["qwen_marker_repaired"] = True
    attrs["qwen_marker_repair_page"] = page
    attrs["qwen_marker_evidence_image"] = evidence.image


def _strip_leading_marker(text: str) -> str:
    marker = leading_note_marker(text, include_superscript=True)
    if not marker:
        return normalize_ws(text)
    stripped = normalize_ws(text)
    return normalize_ws(stripped[len(marker) :].lstrip(".．。、)） "))


def _text_similarity(left: str, right: str) -> float:
    left = normalize_ws(left)
    right = normalize_ws(right)
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _page_footnotes_by_page(blocks: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    out: Dict[int, List[Dict[str, Any]]] = {}
    for block in blocks:
        if block.get("type") != "footnote":
            continue
        attrs = block.get("attrs") or {}
        if attrs.get("role") != "page_footnote":
            continue
        page = block_page(block)
        if page is None:
            continue
        out.setdefault(page, []).append(block)
    for page_blocks in out.values():
        page_blocks.sort(key=lambda block: _footnote_sort_key(block))
    return out


def _page_footnote_markers_by_page(blocks: List[Dict[str, Any]]) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = {}
    for page, page_blocks in _page_footnotes_by_page(blocks).items():
        markers: List[str] = []
        for block in page_blocks:
            attrs = block.get("attrs") or {}
            marker = normalize_note_marker(attrs.get("note_marker", "")) or (leading_note_marker(str(block.get("text") or ""), include_superscript=True) or "")
            if marker:
                markers.append(marker)
        if markers:
            out[page] = markers
    return out


def _footnote_sort_key(block: Dict[str, Any]) -> tuple[float, float, str]:
    bbox = block_bbox(block) or []
    y = float(bbox[1]) if len(bbox) >= 2 else 0.0
    x = float(bbox[0]) if len(bbox) >= 1 else 0.0
    return (y, x, str(block.get("id") or block.get("block_id") or ""))


def _read_existing_evidence(path: Path) -> Dict[tuple[int, str], QwenMarkerPageEvidence]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = payload.get("pages") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return {}
    out: Dict[tuple[int, str], QwenMarkerPageEvidence] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        image = item.get("image")
        if not isinstance(page, int) or not isinstance(image, str):
            continue
        evidence = QwenMarkerPageEvidence(
            page=page,
            image=image,
            crop_bbox_pdf=[float(value) for value in item.get("crop_bbox_pdf") or []],
            dpi=int(item.get("dpi") or 0),
            raw_json=dict(item.get("raw_json") or {}),
            body_refs=_clean_body_refs(item.get("body_refs")),
            footnote_defs=_clean_footnote_defs(item.get("footnote_defs")),
            prompt_version=int(item.get("prompt_version") or 0),
        )
        if evidence.prompt_version != _PROMPT_VERSION:
            continue
        out[(page, Path(image).name)] = evidence
    return out


def _write_evidence(path: Path, evidence: Sequence[QwenMarkerPageEvidence]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"engine": "qwen_marker_locator", "pages": [item.to_json() for item in evidence]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _timing_log_path(config: QwenMarkerLocatorConfig) -> Path:
    return config.timing_log_path or (config.artifact_dir / "qwen_marker_timing.jsonl")


def _reset_timing_log(config: QwenMarkerLocatorConfig) -> None:
    path = _timing_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _write_timing_event(config: QwenMarkerLocatorConfig, event: Dict[str, Any]) -> None:
    path = _timing_log_path(config)
    payload = {
        "schema": "qwen_marker_timing.v1",
        **event,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        f.write("\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _duration(start: float) -> float:
    return round(time.perf_counter() - start, 6)
