from __future__ import annotations

from types import SimpleNamespace

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
    assert "source_file" in captured["observed_kwargs"]["metadata"]


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
