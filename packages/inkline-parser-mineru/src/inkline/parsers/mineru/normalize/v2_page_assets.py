"""Materialize visual-page assets directly for the v2 pipeline."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


def materialize_v2_page_assets(
    observed: dict[str, Any],
    page_review: dict[str, Any],
    *,
    source_pdf: str | Path,
    output_dir: Path,
    dpi: int = 150,
) -> dict[str, Any]:
    """Return an observed copy with assets for every page whose visual asset is retained."""

    visual_pages = _visual_asset_pages(page_review)
    materialized = deepcopy(observed)
    if not visual_pages:
        return materialized
    image_paths = _render_page_assets(Path(source_pdf), visual_pages, output_dir, dpi=dpi)
    images = materialized.setdefault("assets", {}).setdefault("images", [])
    for record in page_review.get("pages") or []:
        if not isinstance(record, dict) or record.get("page") not in image_paths:
            continue
        page = int(record["page"])
        image_path = image_paths[page]
        images.append(
            {
                "image_id": f"page-{page:04d}-review",
                "path": image_path.relative_to(output_dir).as_posix(),
                "media_type": "image/png",
                "role": str(record.get("special_page_kind") or record.get("page_role") or "visual_page"),
                "source": {"page": page},
            }
        )
    return materialized


def _visual_asset_pages(page_review: dict[str, Any]) -> list[int]:
    return [
        int(record["page"])
        for record in page_review.get("pages") or []
        if isinstance(record, dict)
        and isinstance(record.get("page"), int)
        and record.get("visual_asset_action") == "retain"
    ]


def _render_page_assets(
    pdf_path: Path, pages: list[int], output_dir: Path, *, dpi: int
) -> dict[int, Path]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional runtime
        raise RuntimeError("v2 page assets require PyMuPDF (`fitz`).") from exc

    asset_dir = output_dir / "images" / "pages"
    asset_dir.mkdir(parents=True, exist_ok=True)
    rendered: dict[int, Path] = {}
    document = fitz.open(pdf_path)
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    try:
        for page in pages:
            if page < 1 or page > len(document):
                continue
            image_path = asset_dir / f"page_{page:04d}.png"
            if not image_path.exists():
                document[page - 1].get_pixmap(matrix=matrix, alpha=False).save(image_path)
            rendered[page] = image_path
    finally:
        document.close()
    return rendered
