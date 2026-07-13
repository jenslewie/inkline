from __future__ import annotations

import json
from types import SimpleNamespace

from inkline.parsers.mineru.app import page_review_cli


def test_page_review_cli_accepts_narrow_review_arguments(monkeypatch, tmp_path) -> None:
    output_path = tmp_path / "page_review.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "mineru-page-review",
            "--content-list-v2",
            "content_list_v2.json",
            "--middle",
            "middle.json",
            "--source-pdf",
            "sample.pdf",
            "--output",
            str(output_path),
            "--skeleton-llm",
            "--llm",
        ],
    )

    args = page_review_cli.parse_args()

    assert args.content_list_v2 == "content_list_v2.json"
    assert args.output == str(output_path)
    assert args.skeleton_llm is True
    assert args.llm is True


def test_page_review_cli_writes_only_page_review_artifact(monkeypatch, tmp_path) -> None:
    output_path = tmp_path / "page_review.json"
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    args = SimpleNamespace(
        content_list_v2="content_list_v2.json",
        content_list=None,
        middle="middle.json",
        source_pdf=str(source_pdf),
        allow_missing_pdf_text=False,
        doc_id="sample",
        title="Sample",
        language="zh-CN",
        output=str(output_path),
        skeleton_llm=True,
        llm=True,
        llm_model="qwen-test",
        llm_api_url="http://example.test/api/chat",
        llm_timeout_seconds=300,
    )
    calls = []
    observed = {"metadata": {"doc_id": "sample"}}
    skeleton = {"metadata": {"doc_id": "sample"}}
    review = {"metadata": {"doc_id": "sample"}, "candidate_pages": [], "pages": []}

    monkeypatch.setattr(page_review_cli, "parse_args", lambda: args)
    monkeypatch.setattr(page_review_cli, "resolve_source_pdf_path", lambda value, **_: value)
    monkeypatch.setattr(page_review_cli, "load_inputs", lambda _: ({}, {}))
    monkeypatch.setattr(page_review_cli, "load_json", lambda _: {"pdf_info": []})
    monkeypatch.setattr(
        page_review_cli,
        "build_observed_document_shadow",
        lambda **_kwargs: observed,
    )
    monkeypatch.setattr(
        page_review_cli,
        "build_book_skeleton_shadow",
        lambda value, **_kwargs: skeleton if value is observed else None,
    )
    monkeypatch.setattr(
        page_review_cli,
        "build_page_review_shadow",
        lambda value, supplied_skeleton, **kwargs: calls.append((value, supplied_skeleton, kwargs))
        or review,
    )
    monkeypatch.setattr(page_review_cli, "validate_observed_document", lambda _: None)
    monkeypatch.setattr(page_review_cli, "validate_book_skeleton", lambda _: None)

    page_review_cli.main()

    assert json.loads(output_path.read_text(encoding="utf-8")) == review
    assert calls == [
        (
            observed,
            skeleton,
            {
                "use_llm": True,
                "source_pdf": str(source_pdf),
                "image_output_dir": tmp_path / "page_review_llm_pages",
                "llm_model": "qwen-test",
                "llm_api_url": "http://example.test/api/chat",
                "llm_timeout_seconds": 300,
                "checkpoint_path": tmp_path / "page_review.checkpoint.json",
            },
        )
    ]
