"""CLI entry point for the mineru-to-canonical command. Parses command-line arguments and delegates to build_canonical()."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from inkline.canonical import validate_document

from ..analysis.note_gap_report import build_note_ref_gap_report, note_ref_gap_report_path
from ..normalize.assets import materialize_image_assets
from ..normalize.core import build_canonical
from ..extraction.io import load_inputs
from ..reconcile import resolve_source_pdf_path
from ..bridge import find_mineru_run_version_info, get_mineru_version_info

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
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use local Qwen visual marker locator to repair targeted problem pages (disabled by default)",
    )
    p.add_argument("--marker-locator-artifact-dir", help="Directory for rendered Qwen marker locator pages and evidence JSON; defaults next to the output file")
    p.add_argument("--marker-locator-model", default="qwen3.5:9b", help="Local Ollama visual model name for marker location")
    p.add_argument("--marker-locator-api-url", default="http://127.0.0.1:11434/api/chat", help="Local Ollama chat endpoint for marker location")
    p.add_argument("--marker-locator-keep-alive", default="2h", help="Ollama keep_alive value for Qwen marker locator requests")
    p.add_argument("--marker-locator-dpi", type=int, default=None, help="Deprecated shorthand that sets both page and block DPI for Qwen marker location")
    p.add_argument("--marker-locator-page-dpi", type=int, default=300, help="DPI for Qwen full-page body-ref marker location")
    p.add_argument("--marker-locator-block-dpi", type=int, default=200, help="DPI for Qwen paragraph-block retry marker location")
    p.add_argument("--marker-locator-max-megapixels", type=float, default=0.0, help="Maximum megapixels for one Qwen marker locator image; 0 disables the limit")
    p.add_argument(
        "--marker-locator-body-mode",
        choices=["page", "block", "page_then_block"],
        default="page_then_block",
        help="How Qwen should inspect body-side note refs: full page, individual body block crops, or page first with block retry for missing pages",
    )
    p.add_argument("--marker-locator-reuse-evidence", action="store_true", help="Reuse existing Qwen marker locator evidence JSON entries when the rendered image name matches")
    p.add_argument("--marker-locator-timing-log", help="JSONL timing log for each Qwen marker locator page and model call; defaults inside the artifact directory")
    p.add_argument(
        "--note-recovery-mode",
        choices=["qwen"],
        default="qwen",
        help="Missing note-ref recovery strategy (qwen-only visual evidence recovery)",
    )
    p.add_argument("--note-trace-log", help="Write a summary JSON of reconcile.notes function/method call counts for this normalization run")
    p.add_argument("--output", default="canonical.json", help="Output canonical JSON path")
    p.add_argument("--doc-id", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--language", default="zh-CN")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.source_pdf = resolve_source_pdf_path(args.source_pdf, allow_missing=args.allow_missing_pdf_text)
    version_info = find_mineru_run_version_info(
        args.content_list_v2,
        args.content_list,
        args.middle,
        args.model,
        args.md,
    ) or get_mineru_version_info()
    args.mineru_version = version_info.get("mineru_version")
    args.mineru_vl_utils_version = version_info.get("mineru_vl_utils_version")
    args.vlm_model = version_info.get("vlm_model")
    pages, page_sizes = load_inputs(args)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    canonical = build_canonical(pages, page_sizes, args)
    materialize_image_assets(canonical, args.source_pdf, out.parent)
    validate_document(canonical)
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
