from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any


def normalize_mineru_outputs(
    *,
    content_list_v2: str | Path,
    middle: str | Path,
    markdown: str | Path | None,
    source_pdf: str | Path | None,
    output: str | Path,
    doc_id: str | None = None,
    title: str | None = None,
    language: str = "zh-CN",
) -> dict[str, Any]:
    """Run the migrated MinerU normalizer programmatically.

    Heavy optional dependencies are imported inside the function so the rest of
    the monorepo can run without a MinerU/PyMuPDF environment.
    """

    from mineru_normalizer.canonical.core import build_canonical
    from mineru_normalizer.canonical.assets import materialize_image_assets
    from mineru_normalizer.extraction.io import load_inputs

    args = SimpleNamespace(
        content_list=None,
        content_list_v2=str(content_list_v2),
        middle=str(middle),
        model=None,
        md=str(markdown) if markdown else None,
        source_pdf=str(source_pdf) if source_pdf else None,
        allow_missing_pdf_text=False,
        output=str(output),
        doc_id=doc_id,
        title=title,
        language=language,
        glm_ocr_repair=False,
        enable_glm_ocr=False,
        glm_ocr_dpi=300,
        glm_ocr_max_megapixels=0,
    )
    pages, page_sizes = load_inputs(args)
    canonical = build_canonical(pages, page_sizes, args)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    materialize_image_assets(canonical, args.source_pdf, out.parent)

    import json

    out.write_text(json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8")
    return canonical


def ingest_pdf_with_mineru(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise RuntimeError(
        "Direct PDF -> MinerU -> canonical is intentionally isolated for the first monorepo pass. "
        "Run MinerU to produce content_list_v2/middle/md, then call normalize_mineru_outputs "
        "or the mineru-to-canonical console script."
    )
