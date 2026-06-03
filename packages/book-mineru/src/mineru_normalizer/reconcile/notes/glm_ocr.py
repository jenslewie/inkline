"""GLM-OCR evidence for repairing problematic footnote pages.

MinerU remains the primary parser. This module only renders selected problem
pages, asks a local GLM-OCR service for footnote marker evidence, and applies
conservative marker fixes to page-footnote blocks before note link recovery.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from ...analysis.page_geometry import PageGeometry
from ...extraction.text import normalize_note_marker, normalize_ws
from ..block_access import block_bbox, block_page, block_pages
from .marker_patterns import BODY_TYPES, _marker_int
from .keys import leading_note_marker
from .scopes import _EndnoteSectionStrategy, _NoteContext


_DEFAULT_PROMPT = (
    "OCR this footnote marker band. Return the text in reading order. "
    "Preserve line starts exactly, including markers such as 1, 2, *, **, and ***."
)
_DEFAULT_BODY_PROMPT = (
    "OCR this body text crop. Return only the text in reading order. "
    "Preserve superscript note reference markers as visible digits at the exact position."
)
_LINE_START_MARKER_RE = re.compile(r"^\s*(\*{1,3}|\d{1,3})(?=\s|$|[.．、)）《「“\"'\u4e00-\u9fffA-Za-z])")


@dataclass(frozen=True)
class GlmOcrConfig:
    source_pdf: Path
    artifact_dir: Path
    model: str = "glm-ocr:latest"
    api_url: str = "http://127.0.0.1:11434/api/generate"
    dpi: int = 300
    max_megapixels: float = 0.0
    footnote_min_y: float = 0.70
    marker_band_width_ratio: float = 0.18
    prompt: str = _DEFAULT_PROMPT
    body_prompt: str = _DEFAULT_BODY_PROMPT
    reuse_evidence: bool = False
    refresh_footnote_evidence: bool = False


@dataclass
class GlmOcrPageEvidence:
    page: int
    kind: str
    image: str
    crop_bbox_pdf: List[float]
    dpi: int
    raw_text: str
    markers: List[str] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)
    block_id: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "kind": self.kind,
            "image": self.image,
            "crop_bbox_pdf": self.crop_bbox_pdf,
            "dpi": self.dpi,
            "raw_text": self.raw_text,
            "markers": self.markers,
            "lines": self.lines,
            "block_id": self.block_id,
        }


def run_glm_ocr_repairs(blocks: List[Dict[str, Any]], config: GlmOcrConfig) -> List[GlmOcrPageEvidence]:
    """Render problem pages, collect GLM-OCR evidence, and repair targeted regions."""

    page_plan = _problem_page_plan(blocks)
    if not page_plan.footnote_pages and not page_plan.body_ref_pages:
        return []
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    evidence = _collect_glm_ocr_evidence(
        blocks,
        _ProblemPagePlan(footnote_pages=page_plan.footnote_pages, body_ref_pages=set(), body_candidate_block_ids=set()),
        config,
    )
    apply_glm_ocr_footnote_repairs(blocks, evidence)
    body_plan = _problem_page_plan(blocks)
    evidence.extend(
        _collect_glm_ocr_evidence(
            blocks,
            _ProblemPagePlan(
                footnote_pages=set(),
                body_ref_pages=body_plan.body_ref_pages,
                body_candidate_block_ids=body_plan.body_candidate_block_ids,
            ),
            config,
        )
    )
    _write_evidence(config.artifact_dir / "glm_ocr_evidence.json", evidence)
    return evidence


def run_glm_ocr_footnote_repairs(blocks: List[Dict[str, Any]], config: GlmOcrConfig) -> List[GlmOcrPageEvidence]:
    """Backward-compatible name for the footnote-focused repair entry point."""

    return run_glm_ocr_repairs(blocks, config)


def apply_glm_ocr_footnote_repairs(blocks: List[Dict[str, Any]], evidence_pages: Sequence[GlmOcrPageEvidence]) -> None:
    evidence_by_page = {item.page: item for item in evidence_pages if item.kind == "footnote_marker_band"}
    markers_by_page = _body_ref_markers_by_page(blocks)
    for page, page_blocks in _page_footnotes_by_page(blocks).items():
        evidence = evidence_by_page.get(page)
        if evidence is None:
            continue
        expected_markers = markers_by_page.get(page, [])
        _apply_page_footnote_lines(page_blocks, evidence, page, expected_markers)


def apply_glm_ocr_footnote_markers(blocks: List[Dict[str, Any]], evidence_pages: Sequence[GlmOcrPageEvidence]) -> None:
    """Backward-compatible wrapper for tests and callers."""

    apply_glm_ocr_footnote_repairs(blocks, evidence_pages)


@dataclass(frozen=True)
class _ProblemPagePlan:
    footnote_pages: Set[int]
    body_ref_pages: Set[int]
    body_candidate_block_ids: Set[int] = field(default_factory=set)


def _problem_page_plan(blocks: List[Dict[str, Any]]) -> _ProblemPagePlan:
    footnotes_by_page = _page_footnotes_by_page(blocks)
    footnote_pages: Set[int] = set()
    body_ref_pages: Set[int] = set()
    refs_by_page = _body_ref_items_by_page(blocks)
    body_candidate_block_ids: Set[int] = set()
    for page, footnotes in footnotes_by_page.items():
        markers = [leading_note_marker(str(block.get("text") or ""), include_superscript=True) for block in footnotes]
        if any(marker is None for marker in markers):
            footnote_pages.add(page)
        defs = {marker for marker in markers if marker}
        refs = {str(marker) for _idx, _block, marker in refs_by_page.get(page, [])}
        if defs and not defs.issubset(refs):
            body_ref_pages.add(page)
            body_candidate_block_ids.update(_fallback_page_body_candidate_block_ids(blocks, page))
        body_candidate_block_ids.update(_anchored_body_candidate_block_ids(blocks, page, markers, refs_by_page.get(page, [])))
    body_candidate_block_ids.update(_endnote_body_candidate_block_ids(blocks))
    for block in blocks:
        if id(block) in body_candidate_block_ids:
            body_ref_pages.update(block_pages(block))
    return _ProblemPagePlan(
        footnote_pages=footnote_pages,
        body_ref_pages=body_ref_pages,
        body_candidate_block_ids=set(),
    )


def _problem_pages(blocks: List[Dict[str, Any]]) -> Set[int]:
    plan = _problem_page_plan(blocks)
    return plan.footnote_pages | plan.body_ref_pages


def _collect_glm_ocr_evidence(blocks: List[Dict[str, Any]], page_plan: _ProblemPagePlan, config: GlmOcrConfig) -> List[GlmOcrPageEvidence]:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("GLM-OCR page rendering requires PyMuPDF (`fitz`).") from exc

    evidence: List[GlmOcrPageEvidence] = []
    evidence_cache = _read_existing_evidence(config.artifact_dir / "glm_ocr_evidence.json") if config.reuse_evidence else {}
    footnotes_by_page = _page_footnotes_by_page(blocks)
    geometry = PageGeometry.from_canonical_blocks(blocks)
    with fitz.open(config.source_pdf) as doc:
        for page in sorted(page_plan.footnote_pages):
            if page < 1 or page > doc.page_count:
                continue
            pdf_page = doc[page - 1]
            rect = pdf_page.rect
            crop = _footnote_marker_crop(page, pdf_page, footnotes_by_page.get(page, []), geometry, config)
            image_path = config.artifact_dir / f"page_{page:04d}_{config.dpi}dpi_footnote_marker_band.png"
            _render_crop(pdf_page, crop, image_path, config, fail_on_large=True)
            item = evidence_cache.get(_evidence_cache_key(page, "footnote_marker_band", image_path))
            if item is None or config.refresh_footnote_evidence:
                raw_text = _call_glm_ocr(image_path, config)
                lines = _line_start_lines(raw_text)
                item = GlmOcrPageEvidence(
                    page=page,
                    kind="footnote_marker_band",
                    image=str(image_path),
                    crop_bbox_pdf=[float(crop.x0), float(crop.y0), float(crop.x1), float(crop.y1)],
                    dpi=config.dpi,
                    raw_text=raw_text,
                    markers=[marker for marker, _line in lines],
                    lines=[line for _marker, line in lines],
                )
            evidence.append(item)
        for page in sorted(page_plan.body_ref_pages):
            if page < 1 or page > doc.page_count:
                continue
            pdf_page = doc[page - 1]
            crop = pdf_page.rect
            crop_parts = _split_crop_for_memory(crop, config)
            for part_index, part_crop in enumerate(crop_parts, start=1):
                part_suffix = f"_part{part_index:02d}" if part_index > 1 else ""
                image_path = config.artifact_dir / f"page_{page:04d}_{config.dpi}dpi_full_page{part_suffix}.png"
                if not _render_crop(pdf_page, part_crop, image_path, config, fail_on_large=False):
                    continue
                item = evidence_cache.get(_evidence_cache_key(page, "full_page", image_path))
                if item is None:
                    raw_text = _call_glm_ocr(image_path, config, prompt=config.body_prompt)
                    item = GlmOcrPageEvidence(
                        page=page,
                        kind="full_page",
                        image=str(image_path),
                        crop_bbox_pdf=[float(part_crop.x0), float(part_crop.y0), float(part_crop.x1), float(part_crop.y1)],
                        dpi=config.dpi,
                        raw_text=raw_text,
                        markers=[],
                        lines=[],
                        block_id=None,
                    )
                evidence.append(item)
    return evidence


def _read_existing_evidence(path: Path) -> Dict[tuple[int, str, str], GlmOcrPageEvidence]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = payload.get("pages") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return {}
    out: Dict[tuple[int, str, str], GlmOcrPageEvidence] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        kind = item.get("kind")
        image = item.get("image")
        if not isinstance(page, int) or not isinstance(kind, str) or not isinstance(image, str):
            continue
        evidence = GlmOcrPageEvidence(
            page=page,
            kind=kind,
            image=image,
            crop_bbox_pdf=[float(value) for value in item.get("crop_bbox_pdf") or []],
            dpi=int(item.get("dpi") or 0),
            raw_text=str(item.get("raw_text") or ""),
            markers=[str(value) for value in item.get("markers") or []],
            lines=[str(value) for value in item.get("lines") or []],
            block_id=str(item["block_id"]) if item.get("block_id") is not None else None,
        )
        out[_evidence_cache_key(page, kind, Path(image))] = evidence
    return out


def _evidence_cache_key(page: int, kind: str, image_path: Path) -> tuple[int, str, str]:
    return (page, kind, image_path.name)


def _footnote_marker_crop(
    page: int,
    pdf_page: Any,
    page_footnotes: Sequence[Dict[str, Any]],
    geometry: PageGeometry,
    config: GlmOcrConfig,
) -> Any:
    import fitz  # type: ignore

    rect = pdf_page.rect
    fallback_top = rect.y0 + rect.height * config.footnote_min_y
    footnote_tops: List[float] = []
    for block in page_footnotes:
        bbox = block_bbox(block)
        if not bbox:
            continue
        scaled = geometry.scale_bbox(page, bbox, rect)
        footnote_tops.append(float(scaled[1]))
    if footnote_tops:
        padding = max(12.0, rect.height * 0.025)
        top = max(rect.y0, min(footnote_tops) - padding)
    else:
        top = fallback_top
    top = min(top, rect.y1)
    return fitz.Rect(
        rect.x0,
        top,
        rect.x0 + rect.width * config.marker_band_width_ratio,
        rect.y1,
    )


def _render_crop(pdf_page: Any, crop: Any, image_path: Path, config: GlmOcrConfig, *, fail_on_large: bool) -> bool:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("GLM-OCR page rendering requires PyMuPDF (`fitz`).") from exc
    scale = config.dpi / 72
    megapixels = max(1, int(crop.width * scale)) * max(1, int(crop.height * scale)) / 1_000_000
    if config.max_megapixels > 0 and megapixels > config.max_megapixels:
        if fail_on_large:
            raise RuntimeError(f"Refusing GLM-OCR crop {image_path.name} ({megapixels:.1f}MP) above max {config.max_megapixels}MP.")
        return False
    try:
        pix = pdf_page.get_pixmap(matrix=fitz.Matrix(config.dpi / 72, config.dpi / 72), clip=crop, alpha=False)
        if pix.width <= 0 or pix.height <= 0:
            raise RuntimeError(f"Invalid GLM-OCR crop dimensions for {image_path.name}: {pix.width}x{pix.height}.")
        pix.save(str(image_path))
    except Exception as exc:
        if fail_on_large:
            raise
        return False
    return True


def _call_glm_ocr(image_path: Path, config: GlmOcrConfig, *, prompt: Optional[str] = None) -> str:
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "model": config.model,
        "prompt": prompt or config.prompt,
        "images": [image_b64],
        "stream": False,
        "keep_alive": "0s",
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(config.api_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(f"GLM-OCR model `{config.model}` is not available. Run `ollama pull {config.model}`.") from exc
        raise
    except OSError as exc:
        raise RuntimeError(f"Cannot connect to GLM-OCR endpoint {config.api_url}: {exc}") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GLM-OCR endpoint returned non-JSON output.") from exc
    return str(result.get("response") or "")


def _line_start_markers(text: str) -> List[str]:
    return [marker for marker, _line in _line_start_lines(text)]


def _line_start_lines(text: str) -> List[tuple[str, str]]:
    lines: List[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _LINE_START_MARKER_RE.match(line)
        if not match:
            continue
        lines.append((normalize_note_marker(match.group(1)), line))
    return lines


def _apply_page_footnote_lines(
    page_blocks: List[Dict[str, Any]],
    evidence: GlmOcrPageEvidence,
    page: int,
    expected_markers: Sequence[str] = (),
) -> None:
    if len(evidence.lines) == len(page_blocks) and evidence.lines:
        aligned = list(zip(page_blocks, evidence.lines, evidence.markers))
        if all(_line_matches_footnote_block(line, marker, block) for block, line, marker in aligned):
            for block, _line, marker in aligned:
                _apply_footnote_marker(block, marker, page, evidence=evidence)
            return
    if evidence.lines:
        if _apply_matching_page_lines(page_blocks, evidence, page):
            return
        if _apply_single_expected_marker(page_blocks, evidence, expected_markers, page):
            return
        return
    if not evidence.markers:
        if _apply_single_expected_marker(page_blocks, evidence, expected_markers, page):
            return
        return
    _apply_page_markers(page_blocks, evidence.markers, page)


def _apply_matching_page_lines(page_blocks: List[Dict[str, Any]], evidence: GlmOcrPageEvidence, page: int) -> bool:
    repaired = False
    used: Set[int] = set()
    for block in page_blocks:
        if leading_note_marker(str(block.get("text") or ""), include_superscript=True):
            continue
        for index, (marker, line) in enumerate(zip(evidence.markers, evidence.lines)):
            if index in used:
                continue
            if not _line_matches_footnote_block(line, marker, block):
                continue
            _prepend_note_marker(block, marker, page, evidence=evidence)
            used.add(index)
            repaired = True
            break
    return repaired


def _apply_single_expected_marker(
    page_blocks: List[Dict[str, Any]],
    evidence: GlmOcrPageEvidence,
    expected_markers: Sequence[str],
    page: int,
) -> bool:
    unmarked = [block for block in page_blocks if not leading_note_marker(str(block.get("text") or ""), include_superscript=True)]
    if len(unmarked) != 1:
        return False
    existing = {
        normalize_note_marker(marker)
        for marker in (leading_note_marker(str(block.get("text") or ""), include_superscript=True) for block in page_blocks)
        if marker
    }
    unmatched = [normalize_note_marker(marker) for marker in expected_markers if normalize_note_marker(marker) and normalize_note_marker(marker) not in existing]
    unmatched = sorted(set(unmatched))
    if len(unmatched) != 1 or not unmatched[0].startswith("*"):
        return False
    if not _ocr_text_matches_footnote_block(evidence.raw_text, unmarked[0]) and not _evidence_confirms_existing_footnote_sequence(page_blocks, evidence):
        return False
    _prepend_note_marker(unmarked[0], unmatched[0], page, evidence=evidence)
    return True


def _evidence_confirms_existing_footnote_sequence(page_blocks: Sequence[Dict[str, Any]], evidence: GlmOcrPageEvidence) -> bool:
    if not evidence.lines:
        return False
    marked_blocks = [
        block
        for block in page_blocks
        if leading_note_marker(str(block.get("text") or ""), include_superscript=True)
    ]
    matched = 0
    used: Set[int] = set()
    for marker, line in zip(evidence.markers, evidence.lines):
        for index, block in enumerate(marked_blocks):
            if index in used:
                continue
            existing = leading_note_marker(str(block.get("text") or ""), include_superscript=True)
            if existing != marker:
                continue
            if not _line_matches_footnote_block(line, marker, block):
                continue
            used.add(index)
            matched += 1
            break
    return matched == len(evidence.lines)


def _line_matches_footnote_block(line: str, marker: str, block: Dict[str, Any]) -> bool:
    line_text = str(line or "").strip()
    if marker:
        line_text = re.sub(rf"^\s*{re.escape(str(marker))}\s*[.．、)]?\s*", "", line_text)
    return _text_fragments_match(line_text, str(block.get("text") or ""))


def _ocr_text_matches_footnote_block(text: str, block: Dict[str, Any]) -> bool:
    return _text_fragments_match(str(text or ""), str(block.get("text") or ""))


def _text_fragments_match(left: str, right: str) -> bool:
    def compact(text: str) -> str:
        marker, rest = leading_note_marker(text, include_superscript=True) or "", text
        if marker:
            rest = re.sub(rf"^\s*{re.escape(marker)}\s*[.．、)]?\s*", "", text)
        return re.sub(r"\s+", "", rest)

    a = compact(left)
    b = compact(right)
    if not a or not b:
        return False
    common = 0
    for left_char, right_char in zip(a, b):
        if left_char != right_char:
            break
        common += 1
    if common >= 3:
        return True
    if len(a) >= 4 and a[:4] in b[:24]:
        return True
    return _has_meaningful_text_overlap(a, b)


def _has_meaningful_text_overlap(left: str, right: str) -> bool:
    if len(left) < 4 or len(right) < 4:
        return False
    if left.isdigit() or right.isdigit():
        return False
    common = set(left) & set(right)
    informative = {char for char in common if "\u4e00" <= char <= "\u9fff" or char.isalpha()}
    if len(informative) < 2:
        return False
    smaller = max(1, min(len(set(left)), len(set(right))))
    return len(informative) / smaller >= 0.4


def _apply_page_markers(page_blocks: List[Dict[str, Any]], markers: Sequence[str], page: int) -> None:
    marker_index = 0
    for block in page_blocks:
        existing = leading_note_marker(str(block.get("text") or ""), include_superscript=True)
        if existing:
            found_at = _find_marker(markers, existing, marker_index)
            if found_at is not None:
                marker_index = found_at + 1
            continue
        while marker_index < len(markers) and _marker_already_present(page_blocks, markers[marker_index]):
            marker_index += 1
        if marker_index >= len(markers):
            continue
        marker = markers[marker_index]
        marker_index += 1
        _prepend_note_marker(block, marker, page)


def _prepend_note_marker(block: Dict[str, Any], marker: str, page: int, *, evidence: Optional[GlmOcrPageEvidence] = None) -> None:
    text = str(block.get("text") or "")
    separator = "" if marker.startswith("*") else ". "
    block["text"] = f"{marker}{separator}{text.lstrip()}"
    attrs = block.setdefault("attrs", {})
    attrs["note_marker"] = marker
    attrs["note_marker_source"] = "glm_ocr"
    attrs["glm_ocr_repaired"] = True
    attrs["glm_ocr_repair_page"] = page
    if evidence is not None:
        attrs["glm_ocr_evidence_image"] = evidence.image


def _apply_footnote_marker(block: Dict[str, Any], marker: str, page: int, *, evidence: Optional[GlmOcrPageEvidence] = None) -> None:
    existing = leading_note_marker(str(block.get("text") or ""), include_superscript=True)
    if not existing:
        _prepend_note_marker(block, marker, page, evidence=evidence)
        return
    attrs = block.setdefault("attrs", {})
    attrs["note_marker"] = marker
    attrs["note_marker_source"] = "glm_ocr"
    attrs["glm_ocr_repaired"] = True
    attrs["glm_ocr_repair_page"] = page
    if evidence is not None:
        attrs["glm_ocr_evidence_image"] = evidence.image


def _find_marker(markers: Sequence[str], marker: str, start: int) -> Optional[int]:
    for index in range(start, len(markers)):
        if markers[index] == marker:
            return index
    return None


def _marker_already_present(blocks: Sequence[Dict[str, Any]], marker: str) -> bool:
    return any(leading_note_marker(str(block.get("text") or ""), include_superscript=True) == marker for block in blocks)


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


def _footnote_sort_key(block: Dict[str, Any]) -> tuple[float, float, str]:
    bbox = block_bbox(block) or []
    y = float(bbox[1]) if len(bbox) >= 2 else 0.0
    x = float(bbox[0]) if len(bbox) >= 1 else 0.0
    return (y, x, str(block.get("id") or ""))


def _body_ref_items_by_page(blocks: List[Dict[str, Any]]) -> Dict[int, List[tuple[int, Dict[str, Any], int]]]:
    out: Dict[int, List[tuple[int, Dict[str, Any], int]]] = {}
    for block_index, block in enumerate(blocks):
        if block.get("type") not in BODY_TYPES:
            continue
        fallback_pages = block_pages(block)
        attrs = block.get("attrs") or {}
        for ref in attrs.get("note_refs") or []:
            if not isinstance(ref, dict):
                continue
            marker = _marker_int(ref.get("marker"))
            if marker is None:
                continue
            source_page = ref.get("source_page")
            pages = [source_page] if isinstance(source_page, int) else fallback_pages
            for page in pages:
                if isinstance(page, int):
                    out.setdefault(page, []).append((block_index, block, marker))
    for refs in out.values():
        refs.sort(key=lambda item: (item[0], item[2]))
    return out


def _body_ref_markers_by_page(blocks: List[Dict[str, Any]]) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = {}
    for block in blocks:
        if block.get("type") not in BODY_TYPES:
            continue
        fallback_pages = block_pages(block)
        attrs = block.get("attrs") or {}
        for ref in attrs.get("note_refs") or []:
            if not isinstance(ref, dict):
                continue
            marker = normalize_note_marker(ref.get("marker", ""))
            if not marker:
                continue
            source_page = ref.get("source_page")
            pages = [source_page] if isinstance(source_page, int) else fallback_pages
            for page in pages:
                if isinstance(page, int):
                    out.setdefault(page, []).append(marker)
    return out


def _anchored_body_candidate_block_ids(
    blocks: List[Dict[str, Any]],
    page: int,
    footnote_markers: Sequence[Optional[str]],
    refs: Sequence[tuple[int, Dict[str, Any], int]],
) -> Set[int]:
    defs = {marker_int for marker in footnote_markers if (marker_int := _marker_int(marker)) is not None}
    if len(defs) < 3 or not refs:
        return set()
    ref_markers = {marker for _idx, _block, marker in refs}
    candidate_ids: Set[int] = set()
    for missing in sorted(defs - ref_markers):
        left = max((marker for marker in defs if marker < missing and marker in ref_markers), default=None)
        right = min((marker for marker in defs if marker > missing and marker in ref_markers), default=None)
        if left is None or right is None:
            continue
        anchor_span = _closest_anchor_span(refs, left, right)
        if anchor_span is None:
            continue
        left_index, right_index = anchor_span
        if right_index - left_index < 2:
            continue
        for block in blocks[left_index + 1:right_index]:
            if _is_body_ref_candidate_block(block, page):
                candidate_ids.add(id(block))
    return candidate_ids


def _endnote_body_candidate_block_ids(blocks: List[Dict[str, Any]]) -> Set[int]:
    context = _NoteContext(blocks)
    candidates: Set[int] = set()
    for scope_key, defs in _chapter_endnote_defs_by_scope(blocks, context).items():
        refs = _body_ref_items_for_scope(blocks, context, scope_key)
        candidates.update(_anchored_scope_candidate_block_ids(blocks, context, refs, defs, scope_key=scope_key))
    book_defs = _book_endnote_defs(blocks, context)
    if book_defs:
        refs = _body_ref_items_for_scope(blocks, context, None)
        candidates.update(_anchored_scope_candidate_block_ids(blocks, context, refs, book_defs, scope_key=None))
    return candidates


def _chapter_endnote_defs_by_scope(blocks: List[Dict[str, Any]], context: _NoteContext) -> Dict[str, Set[int]]:
    out: Dict[str, Set[int]] = {}
    for candidate in _EndnoteSectionStrategy("chapter_endnote", scope_required=True).collect(blocks, context):
        marker = _marker_int(candidate.marker)
        if marker is not None and candidate.scope_key:
            out.setdefault(candidate.scope_key, set()).add(marker)
    return out


def _book_endnote_defs(blocks: List[Dict[str, Any]], context: _NoteContext) -> Set[int]:
    out: Set[int] = set()
    for candidate in _EndnoteSectionStrategy("book_endnote", scope_required=False).collect(blocks, context):
        marker = _marker_int(candidate.marker)
        if marker is not None:
            out.add(marker)
    return out


def _body_ref_items_for_scope(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
    scope_key: Optional[str],
) -> List[tuple[int, Dict[str, Any], int]]:
    out: List[tuple[int, Dict[str, Any], int]] = []
    for block_index, block in enumerate(blocks):
        if block.get("type") not in BODY_TYPES:
            continue
        if scope_key is not None and context.scope_for(block) != scope_key:
            continue
        attrs = block.get("attrs") or {}
        for ref in attrs.get("note_refs") or []:
            if not isinstance(ref, dict):
                continue
            marker = _marker_int(ref.get("marker"))
            if marker is not None:
                out.append((block_index, block, marker))
    out.sort(key=lambda item: (item[0], item[2]))
    return out


def _anchored_scope_candidate_block_ids(
    blocks: List[Dict[str, Any]],
    context: _NoteContext,
    refs: Sequence[tuple[int, Dict[str, Any], int]],
    defs: Set[int],
    *,
    scope_key: Optional[str],
) -> Set[int]:
    if len(defs) < 3 or not refs:
        return set()
    ref_markers = {marker for _idx, _block, marker in refs}
    candidate_ids: Set[int] = set()
    for missing in sorted(defs - ref_markers):
        left = max((marker for marker in defs if marker < missing and marker in ref_markers), default=None)
        right = min((marker for marker in defs if marker > missing and marker in ref_markers), default=None)
        if left is None or right is None:
            continue
        anchor_span = _closest_anchor_span(refs, left, right)
        if anchor_span is None:
            continue
        left_index, right_index = anchor_span
        if right_index - left_index < 2:
            continue
        for block in blocks[left_index + 1:right_index]:
            if _is_scope_body_ref_candidate_block(block, context, scope_key):
                candidate_ids.add(id(block))
    return candidate_ids


def _closest_anchor_span(refs: Sequence[tuple[int, Dict[str, Any], int]], left_anchor: int, right_anchor: int) -> Optional[tuple[int, int]]:
    spans: List[tuple[int, int]] = []
    left_indexes = [block_index for block_index, _block, marker in refs if marker == left_anchor]
    right_indexes = [block_index for block_index, _block, marker in refs if marker == right_anchor]
    for left_index in left_indexes:
        for right_index in right_indexes:
            if left_index < right_index:
                spans.append((left_index, right_index))
    if not spans:
        return None
    return min(spans, key=lambda span: span[1] - span[0])


def _body_ref_candidate_blocks(blocks: List[Dict[str, Any]], page_plan: _ProblemPagePlan) -> List[Dict[str, Any]]:
    if not page_plan.body_candidate_block_ids:
        return []
    return [block for block in blocks if id(block) in page_plan.body_candidate_block_ids]


def _fallback_page_body_candidate_block_ids(blocks: List[Dict[str, Any]], page: int) -> Set[int]:
    return {
        id(block)
        for block in blocks
        if _is_body_ref_candidate_block(block, page)
    }


def _is_body_ref_candidate_block(block: Dict[str, Any], page: int) -> bool:
    if block.get("type") not in BODY_TYPES:
        return False
    if page not in block_pages(block):
        return False
    if (block.get("attrs") or {}).get("note_refs"):
        return False
    if not normalize_ws(str(block.get("text") or "")):
        return False
    return block_bbox(block) is not None


def _is_scope_body_ref_candidate_block(block: Dict[str, Any], context: _NoteContext, scope_key: Optional[str]) -> bool:
    if block.get("type") not in BODY_TYPES:
        return False
    if scope_key is not None and context.scope_for(block) != scope_key:
        return False
    if (block.get("attrs") or {}).get("note_refs"):
        return False
    if not normalize_ws(str(block.get("text") or "")):
        return False
    return block_bbox(block) is not None


def _block_crop_rect(page_rect: Any, block: Dict[str, Any]) -> Any:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("GLM-OCR page rendering requires PyMuPDF (`fitz`).") from exc
    bbox = block_bbox(block)
    if bbox is None:
        return None
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    if max(abs(x0), abs(y0), abs(x1), abs(y1)) <= 1000.0 and max(page_rect.width, page_rect.height) > 1000.0:
        x0 = x0 / 1000.0 * page_rect.width
        x1 = x1 / 1000.0 * page_rect.width
        y0 = y0 / 1000.0 * page_rect.height
        y1 = y1 / 1000.0 * page_rect.height
    pad_x = page_rect.width * 0.02
    pad_y = page_rect.height * 0.008
    return fitz.Rect(
        max(page_rect.x0, x0 - pad_x),
        max(page_rect.y0, y0 - pad_y),
        min(page_rect.x1, x1 + pad_x),
        min(page_rect.y1, y1 + pad_y),
    )


def _page_body_crop_rect(page_rect: Any, blocks: Sequence[Dict[str, Any]], page: int) -> Any:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("GLM-OCR page rendering requires PyMuPDF (`fitz`).") from exc
    rects: List[Any] = []
    for block in blocks:
        if block.get("type") not in BODY_TYPES:
            continue
        if page not in block_pages(block):
            continue
        if not normalize_ws(str(block.get("text") or "")):
            continue
        rect = _bbox_to_pdf_rect(page_rect, block)
        if rect is not None:
            rects.append(rect)
    if not rects:
        return None
    x0 = min(rect.x0 for rect in rects)
    y0 = min(rect.y0 for rect in rects)
    x1 = max(rect.x1 for rect in rects)
    y1 = max(rect.y1 for rect in rects)
    pad_x = page_rect.width * 0.025
    pad_y = page_rect.height * 0.012
    return fitz.Rect(
        max(page_rect.x0, x0 - pad_x),
        max(page_rect.y0, y0 - pad_y),
        min(page_rect.x1, x1 + pad_x),
        min(page_rect.y1, y1 + pad_y),
    )


def _bbox_to_pdf_rect(page_rect: Any, block: Dict[str, Any]) -> Optional[Any]:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("GLM-OCR page rendering requires PyMuPDF (`fitz`).") from exc
    bbox = block_bbox(block)
    if bbox is None:
        return None
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    if max(abs(x0), abs(y0), abs(x1), abs(y1)) <= 1000.0 and max(page_rect.width, page_rect.height) > 1000.0:
        x0 = x0 / 1000.0 * page_rect.width
        x1 = x1 / 1000.0 * page_rect.width
        y0 = y0 / 1000.0 * page_rect.height
        y1 = y1 / 1000.0 * page_rect.height
    if x1 <= x0 or y1 <= y0:
        return None
    return fitz.Rect(
        max(page_rect.x0, x0),
        max(page_rect.y0, y0),
        min(page_rect.x1, x1),
        min(page_rect.y1, y1),
    )


def _split_crop_for_memory(crop: Any, config: GlmOcrConfig) -> List[Any]:
    if config.max_megapixels <= 0:
        return [crop]
    scale = config.dpi / 72
    width_px = max(1, int(crop.width * scale))
    height_px = max(1, int(crop.height * scale))
    max_pixels = config.max_megapixels * 1_000_000
    if width_px * height_px <= max_pixels:
        return [crop]
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("GLM-OCR page rendering requires PyMuPDF (`fitz`).") from exc
    max_height = max(12.0, (max_pixels / width_px) / scale * 0.92)
    overlap = min(max_height * 0.12, max(4.0, crop.height * 0.04))
    parts: List[Any] = []
    y0 = float(crop.y0)
    while y0 < float(crop.y1):
        y1 = min(float(crop.y1), y0 + max_height)
        parts.append(fitz.Rect(float(crop.x0), y0, float(crop.x1), y1))
        if y1 >= float(crop.y1):
            break
        y0 = max(y0 + 1.0, y1 - overlap)
    return parts


def _write_evidence(path: Path, evidence: Sequence[GlmOcrPageEvidence]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"engine": "glmocr", "pages": [item.to_json() for item in evidence]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
