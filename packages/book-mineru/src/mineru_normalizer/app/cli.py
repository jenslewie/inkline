"""CLI entry point for the mineru-to-canonical command. Parses command-line arguments and delegates to build_canonical()."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from ..analysis.note_gap_report import build_note_ref_gap_report, note_ref_gap_report_path
from ..canonical.assets import materialize_image_assets
from ..canonical.core import build_canonical
from ..extraction.io import flatten_content_list_legacy, flatten_content_list_v2, load_json, page_sizes_from_middle
from ..schema.models import RawBlock
from ..reconcile import resolve_source_pdf_path

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Normalize MinerU VLM outputs to canonical.json")
    p.add_argument("--content-list-v2", dest="content_list_v2", help="MinerU content_list_v2.json; preferred input")
    p.add_argument("--content-list", dest="content_list", help="MinerU content_list.json fallback input")
    p.add_argument("--middle", help="MinerU middle.json; used for page sizes/layout metadata")
    p.add_argument("--model", help="MinerU model.json; stored as source metadata")
    p.add_argument("--md", help="MinerU markdown file; stored as source metadata")
    p.add_argument("--source-pdf", help="Original PDF path; stored as source metadata")
    p.add_argument("--allow-missing-pdf-text", action="store_true", help="Allow running without readable PDF text layer; cross-page paragraph merging will fall back to block bbox and may be less accurate")
    p.add_argument(
        "--marker-locator-repair",
        action="store_true",
        help="Use local Qwen visual marker locator to repair targeted problem pages; MinerU remains the primary parser",
    )
    p.add_argument(
        "--glm-ocr-repair",
        action="store_true",
        help="Deprecated alias for --marker-locator-repair",
    )
    p.add_argument(
        "--enable-glm-ocr",
        action="store_true",
        dest="glm_ocr_repair",
        help=argparse.SUPPRESS,
    )
    p.add_argument("--marker-locator-artifact-dir", help="Directory for rendered Qwen marker locator pages and evidence JSON; defaults next to the output file")
    p.add_argument("--marker-locator-model", default="qwen3.5:9b", help="Local Ollama visual model name for marker location")
    p.add_argument("--marker-locator-api-url", default="http://127.0.0.1:11434/api/chat", help="Local Ollama chat endpoint for marker location")
    p.add_argument("--marker-locator-dpi", type=int, default=300, help="DPI for rendering Qwen marker locator full pages")
    p.add_argument("--marker-locator-max-megapixels", type=float, default=0.0, help="Maximum megapixels for one Qwen marker locator image; 0 disables the limit")
    p.add_argument("--marker-locator-reuse-evidence", action="store_true", help="Reuse existing Qwen marker locator evidence JSON entries when the rendered image name matches")
    p.add_argument("--marker-locator-timing-log", help="JSONL timing log for each Qwen marker locator page and model call; defaults inside the artifact directory")
    p.add_argument("--glm-ocr-artifact-dir", help=argparse.SUPPRESS)
    p.add_argument("--glm-ocr-model", default="glm-ocr:latest", help=argparse.SUPPRESS)
    p.add_argument("--glm-ocr-api-url", default="http://127.0.0.1:11434/api/generate", help=argparse.SUPPRESS)
    p.add_argument("--glm-ocr-dpi", type=int, default=300, help=argparse.SUPPRESS)
    p.add_argument("--glm-ocr-max-megapixels", type=float, default=0.0, help=argparse.SUPPRESS)
    p.add_argument("--glm-ocr-footnote-min-y", type=float, default=0.70, help=argparse.SUPPRESS)
    p.add_argument("--glm-ocr-marker-band-width", type=float, default=0.18, help=argparse.SUPPRESS)
    p.add_argument("--glm-ocr-reuse-evidence", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--glm-ocr-refresh-footnote-evidence", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--output", default="canonical.json", help="Output canonical JSON path")
    p.add_argument("--doc-id", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--language", default="zh-CN")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.source_pdf = resolve_source_pdf_path(args.source_pdf, allow_missing=args.allow_missing_pdf_text)
    middle = load_json(args.middle)
    page_sizes = page_sizes_from_middle(middle)

    pages: Dict[int, List[RawBlock]]
    if args.content_list_v2:
        content_v2 = load_json(args.content_list_v2)
        if not isinstance(content_v2, list):
            raise ValueError("content_list_v2 must be a list of page item lists")
        pages = flatten_content_list_v2(content_v2)
    elif args.content_list:
        content = load_json(args.content_list)
        if not isinstance(content, list):
            raise ValueError("content_list must be a list")
        pages = flatten_content_list_legacy(content)
    else:
        raise SystemExit("Either --content-list-v2 or --content-list is required")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    canonical = build_canonical(pages, page_sizes, args)
    materialize_image_assets(canonical, args.source_pdf, out.parent)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(canonical, f, ensure_ascii=False, indent=2)
    report_path = note_ref_gap_report_path(out)
    report = build_note_ref_gap_report(canonical, canonical_path=out)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out} with {len(canonical['blocks'])} blocks and {len(canonical['toc'])} toc entries")
    print(
        f"Wrote {report_path} with "
        f"{report['summary']['missing_body_ref_notes']} missing body note ref(s)"
    )


if __name__ == "__main__":
    main()
