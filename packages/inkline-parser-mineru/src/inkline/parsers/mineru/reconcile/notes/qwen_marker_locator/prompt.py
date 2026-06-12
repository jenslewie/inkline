"""Prompt engineering, page/block rendering, and footnote matching for the Qwen marker locator.

Contains prompt string generation, block/page rendering to images, footnote
definition matching, and text similarity helpers.  Uses module-level import
from ``types`` so that monkeypatching works correctly.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ....analysis.page_geometry import PageGeometry
from ....extraction.text import normalize_note_marker, normalize_ws
from ...block_access import block_bbox, block_id, block_page, block_pages
from ....schema.models import CanonicalBlock
from ..keys import leading_note_marker
from . import types as qwen_types


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
        "特别注意：如果某个marker印在标点之后，before_text必须包含这个标点并以这个标点结尾，after_text从标点后的正文开始；"
        "如果marker印在标点之前，after_text必须以这个标点开头。"
        + qwen_types._PUNCTUATION_BOUNDARY_INSTRUCTION +
        "输出格式:{\"body_refs\":[{\"marker\":\"\",\"before_text\":\"\",\"after_text\":\"\",\"quote\":\"\",\"confidence\":\"high|medium|low\"}]}。"
        "before_text和after_text都必须是紧邻marker的2到8个原文字符，不要输出超过8个字符的before_text或after_text。"
        "quote必须是before_text+marker+after_text的连续原文片段。"
        "多个marker相邻时，quote必须保留相对位置。"
    )


def _single_marker_body_prompt(marker: str) -> str:
    return (
        "/no_think\n"
        "只返回JSON，不要解释。只看脚注分隔横线以上的正文区域，排除页底脚注定义区。"
        f"只定位正文脚注引用marker：{marker}。不要找其他marker。"
        f"如果正文中找到 {marker}，输出一条；找不到返回空数组。"
        "before_text是marker左侧紧邻2到8个原文字符，after_text是marker右侧紧邻2到8个原文字符，"
        + qwen_types._PUNCTUATION_BOUNDARY_INSTRUCTION +
        f"quote=before_text+{marker}+after_text。不要输出整句或脚注定义。"
        "输出格式:{\"body_refs\":[{\"marker\":\"\",\"before_text\":\"\",\"after_text\":\"\",\"quote\":\"\",\"confidence\":\"high|medium|low\"}]}。"
    )


def _merge_body_ref_raw_items(base_refs: Sequence[Any], extra_refs: Any) -> List[Dict[str, Any]]:
    merged = [dict(item) for item in base_refs if isinstance(item, dict)]
    seen = {
        (
            str(item.get("marker") or ""),
            normalize_ws(str(item.get("before_text") or "")),
            normalize_ws(str(item.get("after_text") or "")),
            normalize_ws(str(item.get("quote") or "")),
        )
        for item in merged
    }
    if not isinstance(extra_refs, list):
        return merged
    for item in extra_refs:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("marker") or ""),
            normalize_ws(str(item.get("before_text") or "")),
            normalize_ws(str(item.get("after_text") or "")),
            normalize_ws(str(item.get("quote") or "")),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(item))
    return merged


def _paragraph_body_prompt_for_markers(markers: Sequence[str], block: CanonicalBlock) -> str:
    marker_list = ", ".join(dict.fromkeys([marker for marker in markers if marker]))
    block_label = block_id(block) or "unknown"
    return (
        "/no_think\n"
        f"只返回JSON，不要解释。当前图片是正文中的一个段落crop，block_id={block_label}。"
        f"只在这个段落crop内定位这些脚注上标marker：{marker_list}。"
        "不要识别页底脚注定义，不要根据脚注意义推测，只看真实印刷的小号上标、数字或星号。"
        "如果看不到任何marker，返回{\"body_refs\":[]}。"
        "before_text必须是marker左侧紧邻的2到8个原文字符，并以marker左边那个字符结尾；"
        "after_text必须是marker右侧紧邻的2到8个原文字符，并以marker右边那个字符开头。"
        "如果marker右边紧邻标点，after_text必须以该标点开头；如果marker左边紧邻标点，before_text必须以该标点结尾。"
        + qwen_types._PUNCTUATION_BOUNDARY_INSTRUCTION +
        "quote必须等于连续原文片段 before_text + marker + after_text，多个marker相邻时必须保留相对位置。"
        "输出格式:{\"body_refs\":[{\"marker\":\"\",\"before_text\":\"\",\"after_text\":\"\",\"quote\":\"\",\"confidence\":\"high|medium|low\"}]}。"
        "看不清或无法确定紧邻字符就省略该项。"
    )


def _body_markers_for_prompt(footnote_defs: Sequence[Dict[str, Any]], expected_markers: Sequence[str]) -> List[str]:
    markers = [str(item.get("marker") or "") for item in footnote_defs]
    return list(dict.fromkeys([marker for marker in [*markers, *expected_markers] if marker]))


def _body_blocks_by_page(blocks: Sequence[CanonicalBlock]) -> Dict[int, List[CanonicalBlock]]:
    out: Dict[int, List[CanonicalBlock]] = {}
    for block in blocks:
        if block.get("type") not in qwen_types._BODY_REF_BLOCK_TYPES or not normalize_ws(str(block.get("text") or "")):
            continue
        for page in block_pages(block):
            if _block_bbox_for_page(block, page) is not None:
                out.setdefault(page, []).append(block)
    for page, page_blocks in out.items():
        page_blocks.sort(key=lambda block: _body_block_sort_key(block, page))
    return out


def _body_block_sort_key(block: CanonicalBlock, page: int) -> tuple[float, float, str]:
    bbox = _block_bbox_for_page(block, page) or []
    y = float(bbox[1]) if len(bbox) >= 2 else 0.0
    x = float(bbox[0]) if len(bbox) >= 1 else 0.0
    return (y, x, block_id(block))


def _block_bbox_for_page(block: CanonicalBlock, page: int) -> Optional[List[float]]:
    source = block.get("source") or {}
    boxes: List[List[float]] = []
    for span in source.get("spans") or []:
        if not isinstance(span, dict):
            continue
        if span.get("page") != page:
            continue
        bbox = span.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            boxes.append([float(value) for value in bbox[:4]])
    if boxes:
        return _union_bboxes(boxes)
    if block_page(block) == page:
        bbox = block_bbox(block)
        if bbox is not None:
            return [float(value) for value in bbox[:4]]
    return None


def _union_bboxes(boxes: Sequence[Sequence[float]]) -> List[float]:
    return [
        min(float(box[0]) for box in boxes),
        min(float(box[1]) for box in boxes),
        max(float(box[2]) for box in boxes),
        max(float(box[3]) for box in boxes),
    ]


def _render_block_crop(
    pdf_page: Any,
    image_path: Path,
    page: int,
    bbox: Sequence[float],
    geometry: PageGeometry,
    config: qwen_types.QwenMarkerLocatorConfig,
) -> List[float]:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("Qwen marker locator paragraph rendering requires PyMuPDF (`fitz`).") from exc
    scaled = geometry.scale_bbox(page, list(bbox[:4]), pdf_page.rect)
    rect = fitz.Rect(*scaled)
    page_rect = pdf_page.rect
    pad = qwen_types._PARAGRAPH_CROP_PADDING_PDF
    rect = fitz.Rect(
        max(page_rect.x0, rect.x0 - pad),
        max(page_rect.y0, rect.y0 - pad),
        min(page_rect.x1, rect.x1 + pad),
        min(page_rect.y1, rect.y1 + pad),
    )
    if rect.width <= 0 or rect.height <= 0:
        raise RuntimeError(f"Invalid paragraph crop bbox for page {page}: {list(bbox[:4])}.")
    scale = config.dpi / 72
    megapixels = max(1, int(rect.width * scale)) * max(1, int(rect.height * scale)) / 1_000_000
    if config.max_megapixels > 0 and megapixels > config.max_megapixels:
        raise RuntimeError(f"Refusing Qwen paragraph crop {image_path.name} ({megapixels:.1f}MP) above max {config.max_megapixels}MP.")
    pix = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    if pix.width <= 0 or pix.height <= 0:
        raise RuntimeError(f"Invalid Qwen paragraph crop dimensions for {image_path.name}: {pix.width}x{pix.height}.")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(image_path))
    return [round(float(rect.x0), 3), round(float(rect.y0), 3), round(float(rect.x1), 3), round(float(rect.y1), 3)]


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned or "block"


def _render_full_page(pdf_page: Any, image_path: Path, config: qwen_types.QwenMarkerLocatorConfig) -> None:
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


def _footnote_defs_match_blocks(defs: Sequence[Dict[str, Any]], blocks: Sequence[CanonicalBlock]) -> bool:
    return all(_footnote_def_matches_block(item, block) for item, block in zip(defs, blocks))


def _apply_unique_near_text_matches(
    page_blocks: Sequence[CanonicalBlock],
    defs: Sequence[Dict[str, Any]],
    page: int,
    evidence: qwen_types.QwenMarkerPageEvidence,
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


def _footnote_def_matches_block(item: Dict[str, Any], block: CanonicalBlock) -> bool:
    marker = str(item.get("marker") or "")
    existing = normalize_note_marker((block.get("attrs") or {}).get("note_marker", "")) or leading_note_marker(str(block.get("text") or ""), include_superscript=True)
    if existing and existing != marker:
        return False
    near_text = _strip_leading_marker(str(item.get("near_text") or ""))
    block_text = _strip_leading_marker(str(block.get("text") or ""))
    if not near_text:
        return True
    return _text_similarity(near_text, block_text) >= 0.18


def _apply_qwen_footnote_marker(block: CanonicalBlock, marker: str, page: int, *, evidence: qwen_types.QwenMarkerPageEvidence) -> None:
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
