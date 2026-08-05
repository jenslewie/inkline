from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from inkline.parsers.mineru.app import book_skeleton_cli
from inkline.parsers.mineru.app import cli as mineru_cli
from inkline.parsers.mineru.normalize import book_skeleton_shadow


def test_cli_book_skeleton_output_passes_pdf_and_toc_image_directory(tmp_path, monkeypatch) -> None:
    source_pdf = tmp_path / "sample.pdf"
    book_skeleton_output = tmp_path / "result" / "sample_skeleton.json"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    observed = {"metadata": {"doc_id": "sample"}}
    skeleton = {"metadata": {"doc_id": "sample"}}
    captured: dict[str, object] = {}

    def fake_build_skeleton(observed_document, **kwargs):
        assert observed_document is observed
        captured.update(kwargs)
        return skeleton

    monkeypatch.setattr(mineru_cli, "build_observed_document_shadow", lambda **_: observed)
    monkeypatch.setattr(mineru_cli, "build_book_skeleton_shadow", fake_build_skeleton)
    monkeypatch.setattr(mineru_cli, "validate_observed_document", lambda _: None)
    monkeypatch.setattr(mineru_cli, "validate_book_skeleton", lambda _: None)

    args = SimpleNamespace(
        observed_output=None,
        bookgraph_from_observed_output=None,
        internal_canonical_output=None,
        book_skeleton_output=str(book_skeleton_output),
        book_skeleton_llm=True,
        book_skeleton_llm_model="qwen-test",
        book_skeleton_llm_api_url="http://example.test/api/chat",
        book_skeleton_llm_timeout_seconds=300,
        source_pdf=str(source_pdf),
        allow_missing_pdf_text=True,
        _middle=None,
    )

    mineru_cli._write_observed_shadow_outputs(
        args,
        pages=[],
        page_sizes=[],
        canonical={"metadata": {"doc_id": "sample"}},
    )

    assert captured["source_pdf"] == str(source_pdf)
    assert captured["image_output_dir"] == (
        book_skeleton_output.parent / "sample_skeleton_toc_llm_pages"
    )


def test_book_skeleton_cli_writes_skeleton_without_canonical_output(tmp_path, monkeypatch) -> None:
    source_pdf = tmp_path / "sample.pdf"
    output = tmp_path / "result" / "sample_skeleton.json"
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
        output=str(output),
        observed_output=None,
        llm=True,
        llm_model="qwen-test",
        llm_api_url="http://example.test/api/chat",
        llm_timeout_seconds=300,
    )
    observed = {"metadata": {"doc_id": "sample"}}
    skeleton = {"metadata": {"doc_id": "sample"}, "toc_entries": []}
    captured: dict[str, object] = {}

    def fake_build_observed(**kwargs):
        captured["observed_kwargs"] = kwargs
        return observed

    monkeypatch.setattr(book_skeleton_cli, "parse_args", lambda: args)
    monkeypatch.setattr(
        book_skeleton_cli,
        "resolve_source_pdf_path",
        lambda *_, **__: str(source_pdf),
    )
    monkeypatch.setattr(book_skeleton_cli, "load_inputs", lambda _: ({}, {1: (1000, 1400)}))
    monkeypatch.setattr(book_skeleton_cli, "load_json", lambda _: {"pdf_info": []})
    monkeypatch.setattr(book_skeleton_cli, "build_observed_document_shadow", fake_build_observed)
    monkeypatch.setattr(book_skeleton_cli, "validate_observed_document", lambda _: None)
    monkeypatch.setattr(
        book_skeleton_cli,
        "build_book_skeleton_shadow",
        lambda observed_document, **kwargs: (
            captured.update(skeleton_observed=observed_document, skeleton_kwargs=kwargs) or skeleton
        ),
    )
    monkeypatch.setattr(book_skeleton_cli, "validate_book_skeleton", lambda _: None)

    book_skeleton_cli.main()

    assert output.exists()
    assert captured["skeleton_observed"] is observed
    assert captured["skeleton_kwargs"] == {
        "use_llm": True,
        "source_pdf": str(source_pdf),
        "image_output_dir": output.parent / "sample_skeleton_toc_llm_pages",
        "llm_model": "qwen-test",
        "llm_api_url": "http://example.test/api/chat",
        "llm_timeout_seconds": 300,
    }
    assert "source_file" in captured["observed_kwargs"]["metadata"]  # pyright: ignore[reportIndexIssue]


def _book_skeleton_cli_args(tmp_path, **overrides):
    values = {
        "content_list_v2": "content_list_v2.json",
        "content_list": None,
        "middle": "middle.json",
        "source_pdf": str(tmp_path / "sample.pdf"),
        "allow_missing_pdf_text": False,
        "doc_id": "sample",
        "title": "Sample",
        "language": "zh-CN",
        "output": str(tmp_path / "skeleton" / "sample_skeleton.json"),
        "observed_output": str(tmp_path / "observed" / "sample_observed.json"),
        "llm": False,
        "llm_model": "qwen-test",
        "llm_api_url": "http://example.test/api/chat",
        "llm_timeout_seconds": 300,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_book_skeleton_cli_parses_optional_observed_output(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mineru-to-book-skeleton",
            "--content-list-v2",
            "content_list_v2.json",
            "--output",
            "skeleton.json",
            "--observed-output",
            "observed.json",
        ],
    )

    args = book_skeleton_cli.parse_args()

    assert args.observed_output == "observed.json"


def test_mineru_cli_parses_opt_in_bounded_review_arguments(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mineru-to-canonical",
            "--canonical-version",
            "v2",
            "--visual-relation-review-llm",
            "--visual-relation-review-output",
            "visual.json",
            "--note-system-review-llm",
            "--note-system-review-output",
            "notes.json",
        ],
    )

    args = mineru_cli.parse_args()

    assert args.visual_relation_review_llm is True
    assert args.visual_relation_review_output == "visual.json"
    assert args.note_system_review_llm is True
    assert args.note_system_review_output == "notes.json"


def test_book_skeleton_cli_rejects_equal_resolved_output_paths(tmp_path, monkeypatch) -> None:
    output = tmp_path / "artifacts" / "sample.json"
    args = _book_skeleton_cli_args(
        tmp_path,
        source_pdf=None,
        output=str(output),
        observed_output=str(output.parent / "." / "sample.json"),
    )
    observed = {"metadata": {}, "pages": [], "observations": []}
    skeleton = {"metadata": {}, "toc_entries": []}

    monkeypatch.setattr(book_skeleton_cli, "parse_args", lambda: args)
    monkeypatch.setattr(book_skeleton_cli, "resolve_source_pdf_path", lambda *_, **__: None)
    monkeypatch.setattr(book_skeleton_cli, "load_inputs", lambda _: ({}, {}))
    monkeypatch.setattr(book_skeleton_cli, "load_json", lambda _: None)
    monkeypatch.setattr(book_skeleton_cli, "build_observed_document_shadow", lambda **_: observed)
    monkeypatch.setattr(book_skeleton_cli, "validate_observed_document", lambda _: None)
    monkeypatch.setattr(
        book_skeleton_cli, "build_book_skeleton_shadow", lambda *_args, **_kwargs: skeleton
    )
    monkeypatch.setattr(book_skeleton_cli, "validate_book_skeleton", lambda _: None)

    with pytest.raises(ValueError, match="different files"):
        book_skeleton_cli.main()

    assert not output.exists()


def test_book_skeleton_cli_validation_failure_writes_no_output_or_skeleton(
    tmp_path, monkeypatch
) -> None:
    args = _book_skeleton_cli_args(tmp_path, source_pdf=None)
    observed_output = Path(args.observed_output)
    skeleton_output = Path(args.output)
    observed = {"metadata": {}, "pages": [], "observations": []}

    monkeypatch.setattr(book_skeleton_cli, "parse_args", lambda: args)
    monkeypatch.setattr(book_skeleton_cli, "resolve_source_pdf_path", lambda *_, **__: None)
    monkeypatch.setattr(book_skeleton_cli, "load_inputs", lambda _: ({}, {}))
    monkeypatch.setattr(book_skeleton_cli, "load_json", lambda _: None)
    monkeypatch.setattr(book_skeleton_cli, "build_observed_document_shadow", lambda **_: observed)
    monkeypatch.setattr(
        book_skeleton_cli,
        "validate_observed_document",
        lambda _: (_ for _ in ()).throw(ValueError("invalid observed document")),
    )
    monkeypatch.setattr(
        book_skeleton_cli,
        "build_book_skeleton_shadow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Skeleton construction must not start")
        ),
    )

    with pytest.raises(ValueError, match="invalid observed document"):
        book_skeleton_cli.main()

    assert not observed_output.exists()
    assert not skeleton_output.exists()


def test_book_skeleton_cli_writes_exact_observed_object_before_skeleton(
    tmp_path, monkeypatch
) -> None:
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    args = _book_skeleton_cli_args(tmp_path, source_pdf=str(source_pdf))
    observed_output = Path(args.observed_output)
    observed = {"metadata": {"doc_id": "sample"}, "pages": [], "observations": []}
    skeleton = {"metadata": {"doc_id": "sample"}, "toc_entries": []}

    monkeypatch.setattr(book_skeleton_cli, "parse_args", lambda: args)
    monkeypatch.setattr(
        book_skeleton_cli,
        "resolve_source_pdf_path",
        lambda *_, **__: str(source_pdf),
    )
    monkeypatch.setattr(book_skeleton_cli, "load_inputs", lambda _: ({}, {}))
    monkeypatch.setattr(book_skeleton_cli, "load_json", lambda _: None)
    monkeypatch.setattr(book_skeleton_cli, "build_observed_document_shadow", lambda **_: observed)
    monkeypatch.setattr(book_skeleton_cli, "validate_observed_document", lambda _: None)

    def build_skeleton(value, **_):
        assert value is observed
        assert json.loads(observed_output.read_text(encoding="utf-8")) == observed
        return skeleton

    monkeypatch.setattr(book_skeleton_cli, "build_book_skeleton_shadow", build_skeleton)
    monkeypatch.setattr(book_skeleton_cli, "validate_book_skeleton", lambda _: None)

    book_skeleton_cli.main()

    assert observed_output.parent.is_dir()
    assert json.loads(observed_output.read_text(encoding="utf-8")) == observed


def test_book_skeleton_cli_stops_when_observed_output_cannot_be_written(
    tmp_path, monkeypatch
) -> None:
    args = _book_skeleton_cli_args(tmp_path, source_pdf=None)
    observed = {"metadata": {}, "pages": [], "observations": []}

    monkeypatch.setattr(book_skeleton_cli, "parse_args", lambda: args)
    monkeypatch.setattr(book_skeleton_cli, "resolve_source_pdf_path", lambda *_, **__: None)
    monkeypatch.setattr(book_skeleton_cli, "load_inputs", lambda _: ({}, {}))
    monkeypatch.setattr(book_skeleton_cli, "load_json", lambda _: None)
    monkeypatch.setattr(book_skeleton_cli, "build_observed_document_shadow", lambda **_: observed)
    monkeypatch.setattr(book_skeleton_cli, "validate_observed_document", lambda _: None)
    monkeypatch.setattr(
        book_skeleton_cli,
        "_write_json",
        lambda *_: (_ for _ in ()).throw(OSError("read-only output")),
    )
    monkeypatch.setattr(
        book_skeleton_cli,
        "build_book_skeleton_shadow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Skeleton construction must not start")
        ),
    )

    with pytest.raises(OSError, match="read-only output"):
        book_skeleton_cli.main()


def test_book_skeleton_llm_messages_keep_toc_images_separate_and_ordered(tmp_path) -> None:
    first_image = tmp_path / "toc_page_0004.png"
    second_image = tmp_path / "toc_page_0005.png"
    first_image.write_bytes(b"first image")
    second_image.write_bytes(b"second image")

    messages = book_skeleton_shadow._llm_messages(
        "Return the combined TOC JSON.",
        [first_image, second_image],
    )

    assert len(messages) == 3
    assert messages[0]["content"] == (
        "This is TOC page image 1 of 2. It comes before every later TOC page image. "
        "Read and retain its entries; do not return the final JSON yet."
    )
    assert messages[0]["images"] == ["Zmlyc3QgaW1hZ2U="]
    assert messages[1]["content"] == (
        "This is TOC page image 2 of 2. It comes after every earlier TOC page image. "
        "Read and retain its entries; do not return the final JSON yet."
    )
    assert messages[1]["images"] == ["c2Vjb25kIGltYWdl"]
    assert messages[2] == {"role": "user", "content": "Return the combined TOC JSON."}


def test_book_skeleton_llm_config_uses_fixed_sampling_seed() -> None:
    config = book_skeleton_shadow._llm_config("qwen-test", "http://example.test/api/chat", 300)

    assert config.options["temperature"] == 0
    assert config.options["seed"] == 0
