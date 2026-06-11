"""Canonical asset path resolution. Resolves image/file paths from MinerU source data into paths referenced in canonical output metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..analysis.page_geometry import PageGeometry


def materialize_image_assets(
    canonical: Dict[str, Any],
    source_pdf: Optional[str],
    output_dir: Path,
    page_sizes: Optional[Dict[int, Tuple[float, float]]] = None,
    dpi: int = 150,
) -> None:
    materialize_page_snapshot_assets(canonical, source_pdf, output_dir, dpi=dpi)
    materialize_full_page_image_assets(canonical, source_pdf, output_dir, dpi=dpi)
    materialize_repaired_figure_image_assets(canonical, source_pdf, output_dir, page_sizes=page_sizes, dpi=dpi)


def materialize_page_snapshot_assets(canonical: Dict[str, Any], source_pdf: Optional[str], output_dir: Path, dpi: int = 150) -> None:
    pages = [
        p for p in canonical.get("pages", [])
        if isinstance(p, dict) and isinstance(p.get("snapshot"), dict) and p["snapshot"].get("required")
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
            role = page.get("page_role") if page.get("page_role") in {"cover", "back_cover"} else "page_snapshot"
            _upsert_image_asset(
                canonical,
                {
                    "image_id": image_id,
                    "path": str(image_path),
                    "media_type": "image/png",
                    "role": role,
                    "snapshot_role": snapshot.get("role"),
                    "source": {"page": page_num},
                    "related_block_ids": related_by_page.get(page_num, []),
                },
            )
    finally:
        doc.close()


def materialize_full_page_image_assets(canonical: Dict[str, Any], source_pdf: Optional[str], output_dir: Path, dpi: int = 150) -> None:
    if not source_pdf:
        return
    full_page_figures = [
        b for b in canonical.get("blocks", [])
        if b.get("type") == "figure" and (b.get("attrs") or {}).get("layout_role") == "full_page_image"
    ]
    if not full_page_figures:
        return
    try:
        import fitz  # type: ignore
    except Exception as exc:
        for b in full_page_figures:
            b.setdefault("attrs", {})["full_page_image_render_error"] = f"PyMuPDF unavailable: {exc}"
        return

    pdf_path = Path(source_pdf)
    asset_dir = output_dir / "images" / "full_page"
    asset_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        for b in full_page_figures:
            page = (b.get("source") or {}).get("page")
            if not isinstance(page, int) or page < 1 or page > len(doc):
                continue
            image_name = f"page_{page:04d}.png"
            image_path = asset_dir / image_name
            if not image_path.exists():
                pix = doc[page - 1].get_pixmap(matrix=matrix, alpha=False)
                pix.save(str(image_path))
            attrs = b.setdefault("attrs", {})
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
                    "path": str(image_path),
                    "media_type": "image/png",
                    "role": "figure",
                    "source": {"page": page},
                    "related_block_ids": [b.get("block_id")] if b.get("block_id") else [],
                },
            )
    finally:
        doc.close()


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
        b for b in canonical.get("blocks", [])
        if b.get("type") == "figure" and _needs_repaired_figure_asset(b)
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
            page = (b.get("source") or {}).get("page")
            bbox = _repaired_figure_crop_bbox(b)
            if not isinstance(page, int) or page < 1 or page > len(doc) or not bbox:
                continue
            rect = _scale_bbox_to_pdf_rect(page, doc[page - 1].rect, bbox, geometry)
            if _should_expand_repaired_figure_crop(b):
                rect = _expand_rect_to_visible_content(doc[page - 1], rect)
            rect = _pad_and_clip_rect(rect, doc[page - 1].rect)
            if rect.is_empty or rect.width <= 1 or rect.height <= 1:
                continue
            block_id = str(b.get("block_id") or f"page_{page:04d}")
            image_name = f"{block_id}_page_{page:04d}.png"
            image_path = asset_dir / image_name
            if not image_path.exists():
                pix = doc[page - 1].get_pixmap(matrix=matrix, clip=rect, alpha=False)
                pix.save(str(image_path))
            attrs = b.setdefault("attrs", {})
            image_id = f"{block_id}-image"
            original = attrs.get("image_path")
            if original:
                attrs.setdefault("original_image_path", original)
            attrs["image_path"] = str(Path("images") / "repaired" / image_name)
            attrs["image_id"] = image_id
            attrs["image_render_source"] = "source_pdf_crop"
            attrs["image_render_dpi"] = dpi
            attrs["image_render_bbox"] = _pdf_rect_to_coord_bbox(page, doc[page - 1].rect, rect, geometry)
            _upsert_image_asset(
                canonical,
                {
                    "image_id": image_id,
                    "path": str(image_path),
                    "media_type": "image/png",
                    "role": "figure",
                    "source": {"page": page, "bbox": attrs.get("image_render_bbox")},
                    "related_block_ids": [b.get("block_id")] if b.get("block_id") else [],
                },
            )
    finally:
        doc.close()


def _needs_repaired_figure_asset(block: Dict[str, Any]) -> bool:
    attrs = block.get("attrs") or {}
    if attrs.get("layout_role") == "full_page_image":
        return False
    return bool(attrs.get("fragment_block_ids") or attrs.get("embedded_text_absorb_reason"))


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
    return bool(attrs.get("fragment_block_ids") and attrs.get("sub_type") == "text_image")


def _repaired_figure_crop_bbox(block: Dict[str, Any]) -> Optional[list[float]]:
    attrs = block.get("attrs") or {}
    bbox = attrs.get("image_bbox") or (block.get("source") or {}).get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    return [float(v) for v in bbox[:4]]


def _page_geometry(canonical: Dict[str, Any], page_sizes: Optional[Dict[int, Tuple[float, float]]]) -> PageGeometry:
    if page_sizes:
        return PageGeometry(
            coord_widths={page: size[0] for page, size in page_sizes.items()},
            coord_heights={page: size[1] for page, size in page_sizes.items()},
        )
    return PageGeometry.from_canonical_blocks(canonical.get("blocks", []))


def _scale_bbox_to_pdf_rect(page: int, pdf_rect: Any, bbox: list[float], geometry: PageGeometry) -> Any:
    import fitz  # type: ignore

    return fitz.Rect(*geometry.scale_bbox(page, bbox, pdf_rect))


def _pdf_rect_to_coord_bbox(page: int, pdf_page_rect: Any, rect: Any, geometry: PageGeometry) -> list[float]:
    return geometry.scale_bbox_inverse(page, rect, pdf_page_rect)


def _expand_rect_to_visible_content(page: Any, rect: Any) -> Any:
    try:
        from PIL import Image  # type: ignore
        import fitz  # type: ignore
    except Exception:
        return rect

    page_rect = page.rect
    search = fitz.Rect(
        max(page_rect.x0, rect.x0 - max(80.0, rect.width * 0.10)),
        max(page_rect.y0, rect.y0 - max(30.0, rect.height * 0.04)),
        min(page_rect.x1, rect.x1 + max(60.0, rect.width * 0.06)),
        min(page_rect.y1, rect.y1 + max(30.0, rect.height * 0.04)),
    )
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), clip=search, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
    except Exception:
        return rect
    ink = image.point(lambda p: 255 if p < 245 else 0)
    content_bbox = ink.getbbox()
    if not content_bbox:
        return rect
    x0, y0, x1, y1 = content_bbox
    expanded = fitz.Rect(search.x0 + x0, search.y0 + y0, search.x0 + x1, search.y0 + y1)
    original_area = max(1.0, rect.width * rect.height)
    expanded_area = max(1.0, expanded.width * expanded.height)
    if expanded_area > original_area * 1.45:
        return rect
    return expanded | rect


def _pad_and_clip_rect(rect: Any, page_rect: Any, padding: float = 4.0) -> Any:
    import fitz  # type: ignore

    padded = fitz.Rect(rect.x0 - padding, rect.y0 - padding, rect.x1 + padding, rect.y1 + padding)
    return padded & page_rect
