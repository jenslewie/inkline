"""Canonical asset path resolution. Resolves image/file paths from MinerU source data into paths referenced in canonical output metadata."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..analysis.page_geometry import PageGeometry
from ..schema.block_types import FIGURE


def materialize_image_assets(
    canonical: Dict[str, Any],
    source_pdf: Optional[str],
    output_dir: Path,
    page_sizes: Optional[Dict[int, Tuple[float, float]]] = None,
    dpi: int = 150,
) -> None:
    materialize_page_snapshot_assets(canonical, source_pdf, output_dir, dpi=dpi)
    materialize_full_page_image_assets(canonical, source_pdf, output_dir, dpi=dpi)
    materialize_repaired_figure_image_assets(
        canonical, source_pdf, output_dir, page_sizes=page_sizes, dpi=dpi
    )
    materialize_figure_path_assets(canonical, output_dir)


def materialize_page_snapshot_assets(
    canonical: Dict[str, Any], source_pdf: Optional[str], output_dir: Path, dpi: int = 150
) -> None:
    pages = [
        p
        for p in canonical.get("pages", [])
        if isinstance(p, dict)
        and isinstance(p.get("snapshot"), dict)
        and p["snapshot"].get("required")
    ]
    if not pages or not source_pdf:
        return
    try:
        import fitz  # type: ignore
    except Exception as exc:
        for page in pages:
            page.setdefault("snapshot", {})["render_error"] = f"PyMuPDF unavailable: {exc}"
        return

    pdf_path = Path(source_pdf)
    asset_dir = output_dir / "images" / "pages"
    asset_dir.mkdir(parents=True, exist_ok=True)
    related_by_page = _related_block_ids_by_page(canonical)
    doc = fitz.open(pdf_path)
    try:
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        for page in pages:
            page_num = page.get("physical_page")
            if not isinstance(page_num, int) or page_num < 1 or page_num > len(doc):
                continue
            image_id = f"page-{page_num:04d}-snapshot"
            image_name = f"page_{page_num:04d}.png"
            image_path = asset_dir / image_name
            if not image_path.exists():
                pix = doc[page_num - 1].get_pixmap(matrix=matrix, alpha=False)
                pix.save(str(image_path))
            snapshot = page.setdefault("snapshot", {})
            snapshot["asset_id"] = image_id
            snapshot["image_render_source"] = "source_pdf"
            snapshot["image_render_dpi"] = dpi
            role = (
                page.get("page_role")
                if page.get("page_role") in {"cover", "back_cover"}
                else "page_snapshot"
            )
            _upsert_image_asset(
                canonical,
                {
                    "image_id": image_id,
                    "path": _asset_path_relative_to_output_dir(image_path, output_dir),
                    "media_type": "image/png",
                    "role": role,
                    "snapshot_role": snapshot.get("role"),
                    "source": {"page": page_num},
                    "related_block_ids": related_by_page.get(page_num, []),
                },
            )
    finally:
        doc.close()


def materialize_full_page_image_assets(
    canonical: Dict[str, Any], source_pdf: Optional[str], output_dir: Path, dpi: int = 150
) -> None:
    if not source_pdf:
        return
    full_page_figures = _full_page_figures(canonical)
    if not full_page_figures:
        return

    try:
        import fitz  # type: ignore
    except Exception as exc:
        for b in full_page_figures:
            b.setdefault("attrs", {})["full_page_image_render_error"] = (
                f"PyMuPDF unavailable: {exc}"
            )
        return

    pdf_path = Path(source_pdf)
    doc = fitz.open(pdf_path)
    try:
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        snapshot_asset_by_page = _snapshot_assets_by_page(canonical)
        for b in full_page_figures:
            page = (b.get("source") or {}).get("page")
            if not isinstance(page, int) or page < 1 or page > len(doc):
                continue

            snapshot = snapshot_asset_by_page.get(page)
            if _reuse_snapshot_for_full_page_figure(canonical, b, snapshot, output_dir, page, dpi):
                continue

            _render_full_page_figure(canonical, b, doc[page - 1], matrix, output_dir, page, dpi)
    finally:
        doc.close()


def _full_page_figures(canonical: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        block
        for block in canonical.get("blocks", [])
        if block.get("type") == FIGURE
        and (block.get("attrs") or {}).get("layout_role") == "full_page_image"
    ]


def _snapshot_assets_by_page(canonical: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    snapshot_asset_by_page: Dict[int, Dict[str, Any]] = {}
    for asset in canonical.get("assets", {}).get("images", []):
        if not isinstance(asset, dict):
            continue
        page = _snapshot_page_from_asset_id(str(asset.get("image_id", "")))
        if page is not None:
            snapshot_asset_by_page[page] = asset
    return snapshot_asset_by_page


def _snapshot_page_from_asset_id(image_id: str) -> Optional[int]:
    if not image_id.endswith("-snapshot"):
        return None
    try:
        return int(image_id.split("-")[1])
    except (ValueError, IndexError):
        return None


def _reuse_snapshot_for_full_page_figure(
    canonical: Dict[str, Any],
    block: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]],
    output_dir: Path,
    page: int,
    dpi: int,
) -> bool:
    if not snapshot:
        return False
    reused_path = str(snapshot["path"])
    if not _resolve_stored_path(reused_path, output_dir).exists():
        return False

    attrs = block.setdefault("attrs", {})
    image_id = f"page-{page:04d}-full"
    original = attrs.get("image_path")
    if original:
        attrs["cropped_image_path"] = original
    attrs["image_path"] = str(Path("images") / "pages" / Path(reused_path).name)
    attrs["image_id"] = image_id
    attrs["image_render_source"] = snapshot.get("image_render_source", "source_pdf")
    attrs["image_render_dpi"] = snapshot.get("image_render_dpi", dpi)
    _upsert_image_asset(
        canonical,
        {
            "image_id": image_id,
            "path": reused_path,
            "media_type": snapshot.get("media_type", "image/png"),
            "role": "figure",
            "source": {"page": page},
            "related_block_ids": [block.get("block_id")] if block.get("block_id") else [],
        },
    )
    return True


def _render_full_page_figure(
    canonical: Dict[str, Any],
    block: Dict[str, Any],
    page_obj: Any,
    matrix: Any,
    output_dir: Path,
    page: int,
    dpi: int,
) -> None:
    asset_dir = output_dir / "images" / "full_page"
    asset_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"page_{page:04d}.png"
    image_path = asset_dir / image_name
    if not image_path.exists():
        pix = page_obj.get_pixmap(matrix=matrix, alpha=False)
        pix.save(str(image_path))
    attrs = block.setdefault("attrs", {})
    image_id = f"page-{page:04d}-full"
    original = attrs.get("image_path")
    if original:
        attrs["cropped_image_path"] = original
    attrs["image_path"] = str(Path("images") / "full_page" / image_name)
    attrs["image_id"] = image_id
    attrs["image_render_source"] = "source_pdf"
    attrs["image_render_dpi"] = dpi
    _upsert_image_asset(
        canonical,
        {
            "image_id": image_id,
            "path": _asset_path_relative_to_output_dir(image_path, output_dir),
            "media_type": "image/png",
            "role": "figure",
            "source": {"page": page},
            "related_block_ids": [block.get("block_id")] if block.get("block_id") else [],
        },
    )


def materialize_repaired_figure_image_assets(
    canonical: Dict[str, Any],
    source_pdf: Optional[str],
    output_dir: Path,
    page_sizes: Optional[Dict[int, Tuple[float, float]]] = None,
    dpi: int = 150,
) -> None:
    if not source_pdf:
        return
    repaired_figures = [
        b
        for b in canonical.get("blocks", [])
        if b.get("type") == FIGURE and _needs_repaired_figure_asset(b)
    ]
    if not repaired_figures:
        return
    try:
        import fitz  # type: ignore
    except Exception as exc:
        for b in repaired_figures:
            b.setdefault("attrs", {})["repaired_image_render_error"] = f"PyMuPDF unavailable: {exc}"
        return

    pdf_path = Path(source_pdf)
    asset_dir = output_dir / "images" / "repaired"
    asset_dir.mkdir(parents=True, exist_ok=True)
    geometry = _page_geometry(canonical, page_sizes)
    doc = fitz.open(pdf_path)
    try:
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        for b in repaired_figures:
            _materialize_repaired_figure(
                canonical,
                b,
                doc,
                matrix,
                asset_dir,
                output_dir,
                geometry,
                dpi,
            )
    finally:
        doc.close()


def _materialize_repaired_figure(
    canonical: Dict[str, Any],
    block: Dict[str, Any],
    doc: Any,
    matrix: Any,
    asset_dir: Path,
    output_dir: Path,
    geometry: PageGeometry,
    dpi: int,
) -> None:
    page = (block.get("source") or {}).get("page")
    bbox = _repaired_figure_crop_bbox(block)
    if not isinstance(page, int) or page < 1 or page > len(doc) or not bbox:
        return

    page_obj = doc[page - 1]
    rect = _repaired_figure_pdf_rect(block, page_obj, page, bbox, geometry)
    if rect is None:
        return

    block_id = str(block.get("block_id") or f"page_{page:04d}")
    image_name = f"{block_id}_page_{page:04d}.png"
    image_path = asset_dir / image_name
    pix = page_obj.get_pixmap(matrix=matrix, clip=rect, alpha=False)
    _save_optimized_png(pix, image_path)
    attrs = _update_repaired_figure_attrs(block, block_id, image_name, dpi)
    attrs["image_render_bbox"] = _pdf_rect_to_coord_bbox(page, page_obj.rect, rect, geometry)
    _upsert_image_asset(
        canonical,
        {
            "image_id": attrs["image_id"],
            "path": _asset_path_relative_to_output_dir(image_path, output_dir),
            "media_type": "image/png",
            "role": "figure",
            "source": {"page": page, "bbox": attrs.get("image_render_bbox")},
            "related_block_ids": [block.get("block_id")] if block.get("block_id") else [],
        },
    )


def _repaired_figure_pdf_rect(
    block: Dict[str, Any], page_obj: Any, page: int, bbox: list[float], geometry: PageGeometry
) -> Any | None:
    rect = _scale_bbox_to_pdf_rect(page, page_obj.rect, bbox, geometry)
    original_rect = rect
    if _should_expand_repaired_figure_crop(block):
        rect = _expand_rect_to_visible_content(page_obj, rect)
    if _is_auto_repaired_dense_text_image(block) and not _rect_expanded_bottom(original_rect, rect):
        return None
    if _is_auto_repaired_dense_text_image(block):
        rect = _trim_rect_bottom_to_horizontal_rule(page_obj, rect, original_rect)
    rect = _pad_and_clip_rect(rect, page_obj.rect)
    if rect.is_empty or rect.width <= 1 or rect.height <= 1:
        return None
    return rect


def _update_repaired_figure_attrs(
    block: Dict[str, Any], block_id: str, image_name: str, dpi: int
) -> Dict[str, Any]:
    attrs = block.setdefault("attrs", {})
    image_id = f"{block_id}-image"
    original = attrs.get("image_path")
    if original:
        attrs.setdefault("original_image_path", original)
    attrs["image_path"] = str(Path("images") / "repaired" / image_name)
    attrs["image_id"] = image_id
    attrs["image_render_source"] = "source_pdf_crop"
    attrs["image_render_dpi"] = dpi
    return attrs


def _save_optimized_png(pix: Any, image_path: Path) -> None:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        pix.save(str(image_path))
        return

    try:
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if _is_effectively_grayscale(image):
            image = image.convert("L")
        image.save(image_path, optimize=True)
    except Exception:
        pix.save(str(image_path))


def _is_effectively_grayscale(
    image: Any, *, channel_delta: int = 5, min_gray_ratio: float = 0.99
) -> bool:
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width <= 0 or height <= 0:
        return False
    x_step = max(1, width // 96)
    y_step = max(1, height // 96)
    pixels = rgb.load()
    total = 0
    gray = 0
    for y in range(0, height, y_step):
        for x in range(0, width, x_step):
            r, g, b = pixels[x, y]
            total += 1
            if max(r, g, b) - min(r, g, b) <= channel_delta:
                gray += 1
    return bool(total and gray / total >= min_gray_ratio)


def materialize_figure_path_assets(canonical: Dict[str, Any], output_dir: Path) -> None:
    doc_id = canonical.get("metadata", {}).get("doc_id", "")
    source_dirs = _source_search_dirs(canonical, output_dir)
    for b in canonical.get("blocks", []):
        if b.get("type") != FIGURE:
            continue
        attrs = b.get("attrs") or {}
        image_path = attrs.get("image_path")
        if not image_path or attrs.get("image_id"):
            continue
        resolved = _resolve_figure_image_path(image_path, output_dir, doc_id, source_dirs)
        if not resolved:
            continue
        block_id = b.get("block_id")
        if not block_id:
            continue
        image_id = f"{block_id}-image"
        attrs["image_id"] = image_id
        _upsert_image_asset(
            canonical,
            {
                "image_id": image_id,
                "path": _asset_path_relative_to_output_dir(resolved, output_dir),
                "role": "figure",
                "related_block_ids": [block_id],
            },
        )


def _source_search_dirs(canonical: Dict[str, Any], output_dir: Path) -> List[Path]:
    source_files = canonical.get("metadata", {}).get("source_files", {})
    dirs: List[Path] = [output_dir]
    for key in ("content_list_v2", "content_list", "middle", "model", "md", "source_pdf"):
        path = source_files.get(key)
        if not path:
            continue
        parent = _resolve_stored_path(str(path), output_dir).parent
        if parent.is_dir() and parent not in dirs:
            dirs.append(parent)
    return dirs


def _asset_path_relative_to_output_dir(path: str | Path, output_dir: Path) -> str:
    base = output_dir.expanduser().resolve()
    target = Path(path).expanduser()
    if not target.is_absolute():
        candidate_from_cwd = target.resolve()
        try:
            candidate_from_cwd.relative_to(base)
            target = candidate_from_cwd
        except ValueError:
            target = (base / target).resolve()
    return Path(os.path.relpath(target, base)).as_posix()


def _resolve_stored_path(path: str, output_dir: Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return output_dir / candidate


def _resolve_figure_image_path(
    image_path: str, output_dir: Path, doc_id: str = "", source_dirs: Optional[List[Path]] = None
) -> Optional[Path]:
    candidate = Path(image_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    filename = Path(image_path).name
    search_dirs = source_dirs or [output_dir]
    return (
        _resolve_from_search_dirs(image_path, filename, search_dirs)
        or _resolve_from_vlm_image_dirs(filename, search_dirs)
        or _resolve_from_doc_id_image_dirs(filename, search_dirs, doc_id)
    )


def _resolve_from_search_dirs(
    image_path: str, filename: str, search_dirs: List[Path]
) -> Optional[Path]:
    for base in search_dirs:
        joined = base / image_path
        if joined.exists():
            return joined
        candidate = base / "images" / filename
        if candidate.exists():
            return candidate
    return None


def _resolve_from_vlm_image_dirs(filename: str, search_dirs: List[Path]) -> Optional[Path]:
    for base in search_dirs:
        for vlm_dir in base.rglob("vlm/images"):
            candidate = vlm_dir / filename
            if candidate.exists():
                return candidate
    return None


def _resolve_from_doc_id_image_dirs(
    filename: str, search_dirs: List[Path], doc_id: str
) -> Optional[Path]:
    if not doc_id:
        return None
    for base in search_dirs:
        for candidate_dir in _doc_id_image_dirs(base, doc_id):
            candidate = candidate_dir / filename
            if candidate.exists():
                return candidate
    return None


def _doc_id_image_dirs(base: Path, doc_id: str) -> List[Path]:
    return [
        base / "mineru_raw" / doc_id / "vlm" / "images",
        base / doc_id / "mineru_raw" / doc_id / "vlm" / "images",
    ]


def _needs_repaired_figure_asset(block: Dict[str, Any]) -> bool:
    attrs = block.get("attrs") or {}
    if attrs.get("layout_role") == "full_page_image":
        return False
    return bool(
        attrs.get("fragment_block_ids")
        or attrs.get("embedded_text_absorb_reason")
        or _is_dense_text_image(block)
    )


def _related_block_ids_by_page(canonical: Dict[str, Any]) -> Dict[int, list[str]]:
    related: Dict[int, list[str]] = {}
    for block in canonical.get("blocks", []):
        block_id = block.get("block_id")
        if not block_id:
            continue
        source = block.get("source") or {}
        pages = source.get("pages")
        if isinstance(pages, list):
            block_pages = [p for p in pages if isinstance(p, int)]
        else:
            page = source.get("page")
            block_pages = [page] if isinstance(page, int) else []
        for page in block_pages:
            related.setdefault(page, []).append(block_id)
    return related


def _upsert_image_asset(canonical: Dict[str, Any], asset: Dict[str, Any]) -> None:
    assets = canonical.setdefault("assets", {})
    images = assets.setdefault("images", [])
    if not isinstance(images, list):
        assets["images"] = images = []
    image_id = asset.get("image_id")
    for index, existing in enumerate(images):
        if isinstance(existing, dict) and existing.get("image_id") == image_id:
            images[index] = asset
            return
    images.append(asset)


def _should_expand_repaired_figure_crop(block: Dict[str, Any]) -> bool:
    attrs = block.get("attrs") or {}
    return bool(
        attrs.get("sub_type") == "text_image"
        and (
            attrs.get("fragment_block_ids")
            or attrs.get("embedded_text_absorb_reason")
            or _is_dense_text_image(block)
        )
    )


def _is_auto_repaired_dense_text_image(block: Dict[str, Any]) -> bool:
    attrs = block.get("attrs") or {}
    return bool(
        _is_dense_text_image(block)
        and not attrs.get("fragment_block_ids")
        and not attrs.get("embedded_text_absorb_reason")
    )


def _is_dense_text_image(block: Dict[str, Any]) -> bool:
    attrs = block.get("attrs") or {}
    if attrs.get("sub_type") != "text_image":
        return False
    ocr_text = attrs.get("ocr_text_in_image")
    if not isinstance(ocr_text, str):
        return False
    label_lines = [line for line in ocr_text.splitlines() if line.strip()]
    return len(label_lines) >= 12


def _rect_expanded_bottom(original: Any, candidate: Any, threshold: float = 2.0) -> bool:
    return bool(candidate.y1 > original.y1 + threshold)


def _trim_rect_bottom_to_horizontal_rule(page: Any, rect: Any, original_rect: Any) -> Any:
    try:
        import fitz  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return rect

    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), clip=rect, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
    except Exception:
        return rect
    if pix.width <= 0 or pix.height <= 0:
        return rect

    min_dark_pixels = max(24, int(pix.width * 0.62))
    row_pdf_height = rect.height / pix.height
    pixels = image.load()
    for row in range(pix.height - 1, -1, -1):
        row_bottom = rect.y0 + (row + 1) * row_pdf_height
        if row_bottom <= original_rect.y1 + 2.0:
            break
        dark_pixels = sum(1 for col in range(pix.width) if pixels[col, row] < 220)
        if dark_pixels >= min_dark_pixels:
            return fitz.Rect(rect.x0, rect.y0, rect.x1, row_bottom)
    return rect


def _repaired_figure_crop_bbox(block: Dict[str, Any]) -> Optional[list[float]]:
    attrs = block.get("attrs") or {}
    bbox = attrs.get("image_bbox") or (block.get("source") or {}).get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    return [float(v) for v in bbox[:4]]


def _page_geometry(
    canonical: Dict[str, Any], page_sizes: Optional[Dict[int, Tuple[float, float]]]
) -> PageGeometry:
    if page_sizes:
        return PageGeometry(
            coord_widths={page: size[0] for page, size in page_sizes.items()},
            coord_heights={page: size[1] for page, size in page_sizes.items()},
        )
    return PageGeometry.from_canonical_blocks(canonical.get("blocks", []))


def _scale_bbox_to_pdf_rect(
    page: int, pdf_rect: Any, bbox: list[float], geometry: PageGeometry
) -> Any:
    import fitz  # type: ignore

    return fitz.Rect(*geometry.scale_bbox(page, bbox, pdf_rect))


def _pdf_rect_to_coord_bbox(
    page: int, pdf_page_rect: Any, rect: Any, geometry: PageGeometry
) -> list[float]:
    return geometry.scale_bbox_inverse(page, rect, pdf_page_rect)


def _expand_rect_to_visible_content(page: Any, rect: Any) -> Any:
    try:
        import fitz  # type: ignore
    except Exception:
        return rect

    page_rect = page.rect
    x_step = max(60.0, rect.width * 0.06)
    y_step = max(30.0, rect.height * 0.04)
    search = fitz.Rect(
        max(page_rect.x0, rect.x0 - max(80.0, rect.width * 0.10)),
        max(page_rect.y0, rect.y0 - y_step),
        min(page_rect.x1, rect.x1 + x_step),
        min(page_rect.y1, rect.y1 + y_step),
    )
    original_area = max(1.0, rect.width * rect.height)
    best = rect

    for _ in range(4):
        content = _visible_content_bbox(page, search)
        if content is None:
            return best
        pix, content_bbox = content
        if content_bbox is None:
            return best

        expanded = _content_rect(fitz, search, content_bbox)
        candidate = expanded | rect
        if _rect_area(candidate) > original_area * 1.45:
            return best
        best = candidate

        touches = _content_touches_search_edges(content_bbox, pix, search, page_rect)
        if not any(touches):
            return best

        next_search = _expanded_search_rect(fitz, search, page_rect, touches, x_step, y_step)
        if next_search == search:
            return best
        search = next_search

    return best


def _visible_content_bbox(page: Any, search: Any) -> Optional[Tuple[Any, Any]]:
    try:
        import fitz  # type: ignore
        from PIL import Image  # type: ignore

        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), clip=search, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
    except Exception:
        return None
    ink = image.point(lambda p: 255 if p < 245 else 0)
    return pix, ink.getbbox()


def _content_rect(fitz_module: Any, search: Any, content_bbox: Tuple[int, int, int, int]) -> Any:
    x0, y0, x1, y1 = content_bbox
    return fitz_module.Rect(search.x0 + x0, search.y0 + y0, search.x0 + x1, search.y0 + y1)


def _rect_area(rect: Any) -> float:
    return max(1.0, rect.width * rect.height)


def _content_touches_search_edges(
    content_bbox: Tuple[int, int, int, int], pix: Any, search: Any, page_rect: Any
) -> Tuple[bool, bool, bool, bool]:
    x0, y0, x1, y1 = content_bbox
    return (
        x0 <= 1 and search.x0 > page_rect.x0,
        y0 <= 1 and search.y0 > page_rect.y0,
        x1 >= pix.width - 1 and search.x1 < page_rect.x1,
        y1 >= pix.height - 1 and search.y1 < page_rect.y1,
    )


def _expanded_search_rect(
    fitz_module: Any,
    search: Any,
    page_rect: Any,
    touches: Tuple[bool, bool, bool, bool],
    x_step: float,
    y_step: float,
) -> Any:
    touches_left, touches_top, touches_right, touches_bottom = touches
    next_search = fitz_module.Rect(search)
    if touches_left:
        next_search.x0 = max(page_rect.x0, next_search.x0 - x_step)
    if touches_top:
        next_search.y0 = max(page_rect.y0, next_search.y0 - y_step)
    if touches_right:
        next_search.x1 = min(page_rect.x1, next_search.x1 + x_step)
    if touches_bottom:
        next_search.y1 = min(page_rect.y1, next_search.y1 + y_step)
    return next_search


def _pad_and_clip_rect(rect: Any, page_rect: Any, padding: float = 4.0) -> Any:
    import fitz  # type: ignore

    padded = fitz.Rect(rect.x0 - padding, rect.y0 - padding, rect.x1 + padding, rect.y1 + padding)
    return padded & page_rect
