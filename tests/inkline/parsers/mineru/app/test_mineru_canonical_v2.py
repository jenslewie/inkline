from __future__ import annotations

from types import SimpleNamespace

from inkline.parsers.mineru.app import canonical_v2


def test_v2_pipeline_builds_skeleton_and_review_before_bookgraph(monkeypatch, tmp_path) -> None:
    observed = {"assets": {}, "metadata": {"doc_id": "sample"}}
    page_layout = {"metadata": {"doc_id": "sample", "schema_name": "layout"}}
    skeleton = {"boundaries": {"first_body_page": 3}}
    review = {"candidate_pages": [], "pages": []}
    events = []
    stages = []

    monkeypatch.setattr(
        canonical_v2,
        "build_observed_document_shadow",
        lambda **_kwargs: events.append("observed") or observed,
    )
    monkeypatch.setattr(
        canonical_v2,
        "build_book_skeleton_shadow",
        lambda value, **_kwargs: events.append(("skeleton", value)) or skeleton,
    )
    monkeypatch.setattr(
        canonical_v2,
        "build_page_review_shadow",
        lambda value, supplied_skeleton, **kwargs: (
            events.append(
                (
                    "review",
                    value,
                    supplied_skeleton,
                    kwargs["page_layout"],
                    kwargs["checkpoint_path"],
                )
            )
            or review
        ),
    )
    monkeypatch.setattr(
        canonical_v2,
        "materialize_v2_page_assets_value",
        lambda value, supplied_review, **_kwargs: (
            events.append(("assets", value, supplied_review)) or {"images": []}
        ),
    )
    monkeypatch.setattr(
        canonical_v2,
        "build_bookgraph_from_artifacts",
        lambda bundle: events.append(("bookgraph", bundle)) or {"nodes": []},
    )
    monkeypatch.setattr(
        canonical_v2,
        "build_internal_canonical_from_artifacts",
        lambda bundle, public: events.append(("internal", bundle, public)) or {"pages": []},
    )

    bundle = SimpleNamespace(
        skeleton=skeleton,
        page_review=review,
        text_flow={"text_units": []},
        page_assets={"images": []},
    )

    def run_workflow(value, *, stages, on_stage_complete):
        skeleton_stage = next(stage for stage in stages if stage.name == "skeleton")
        review_stage = next(stage for stage in stages if stage.name == "page_review")
        assets_stage = next(stage for stage in stages if stage.name == "page_assets")
        built_skeleton = skeleton_stage.run(observed=value, observed_index=object())
        on_stage_complete("skeleton", built_skeleton)
        built_review = review_stage.run(
            observed=value,
            skeleton=built_skeleton,
            page_layout=page_layout,
        )
        on_stage_complete("page_review", built_review)
        assets_stage.run(observed=value, page_review=built_review)
        return bundle

    monkeypatch.setattr(canonical_v2, "build_canonical_artifacts", run_workflow)

    artifacts = canonical_v2.build_v2_artifacts(
        pages={},
        page_sizes={},
        metadata={"doc_id": "sample"},
        middle=None,
        source_pdf="sample.pdf",
        output_dir=tmp_path,
        use_skeleton_llm=True,
        use_page_review_llm=True,
        on_stage_complete=lambda name, payload: stages.append((name, payload)),
    )

    assert events == [
        "observed",
        ("skeleton", observed),
        (
            "review",
            observed,
            skeleton,
            page_layout,
            tmp_path / "page_review.checkpoint.json",
        ),
        ("assets", observed, review),
        ("bookgraph", bundle),
        ("internal", bundle, {"nodes": []}),
    ]
    assert artifacts["public_graph"] == {"nodes": []}
    assert artifacts["internal_canonical"] == {"pages": []}
    assert stages == [
        ("observed", observed),
        ("book_skeleton", skeleton),
        ("page_review", review),
    ]


def test_v2_cli_writes_public_only_after_resolved_review(tmp_path, monkeypatch) -> None:
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    args = SimpleNamespace(
        source_pdf=str(source_pdf),
        allow_missing_pdf_text=False,
        content_list_v2="content_list_v2.json",
        content_list=None,
        middle="middle.json",
        output=str(tmp_path / "canonical_v2.json"),
        observed_output=str(tmp_path / "observed.json"),
        book_skeleton_output=str(tmp_path / "skeleton.json"),
        page_review_output=str(tmp_path / "review.json"),
        internal_canonical_output=str(tmp_path / "internal.json"),
        doc_id="sample",
        title="Sample",
        language="zh-CN",
        book_skeleton_llm=True,
        page_review_llm=True,
        book_skeleton_llm_model="qwen-test",
        book_skeleton_llm_api_url="http://example.test/api/chat",
        book_skeleton_llm_timeout_seconds=300,
    )
    artifacts = {
        "observed": {"metadata": {"doc_id": "sample"}},
        "book_skeleton": {"metadata": {"doc_id": "sample"}},
        "page_review": {"metadata": {"doc_id": "sample"}},
        "public_graph": {"metadata": {"doc_id": "sample"}, "nodes": []},
        "internal_canonical": {"metadata": {"doc_id": "sample"}},
    }
    monkeypatch.setattr(canonical_v2, "resolve_source_pdf_path", lambda value, **_: value)
    monkeypatch.setattr(canonical_v2, "load_inputs", lambda _: ({}, {}))
    monkeypatch.setattr(canonical_v2, "load_json", lambda _: {"pdf_info": []})
    monkeypatch.setattr(canonical_v2, "build_v2_artifacts", lambda **_: artifacts)
    monkeypatch.setattr(canonical_v2, "validate_observed_document", lambda _: None)
    monkeypatch.setattr(canonical_v2, "validate_book_skeleton", lambda _: None)
    monkeypatch.setattr(canonical_v2, "validate_bookgraph", lambda _: None)
    monkeypatch.setattr(canonical_v2, "validate_internal_canonical", lambda _: None)

    canonical_v2.run_v2_cli(args)

    assert (tmp_path / "canonical_v2.json").exists()
    assert (tmp_path / "observed.json").exists()
    assert (tmp_path / "skeleton.json").exists()
    assert (tmp_path / "review.json").exists()
    assert (tmp_path / "internal.json").exists()
