from __future__ import annotations

from types import SimpleNamespace

from inkline.canonical import (
    build_observed_index,
    make_observation,
    make_observed_document,
    make_observed_page,
)
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


def test_visual_relation_transport_composition_is_opt_in_and_bounded(tmp_path, monkeypatch) -> None:
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "x",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=100, height=100)],
        [
            make_observation("obs000001", "image_region", page=1, bbox=[0, 0, 40, 40]),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[41, 0, 90, 20],
                text="caption",
                role_hint="caption_text",
            ),
        ],
    )
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    requests = []
    monkeypatch.setattr(
        canonical_v2,
        "vision_chat_json",
        lambda path, config, *, prompt: (
            requests.append((path, config, prompt))
            or {
                "groups": [
                    {
                        "asset_observation_ids": ["obs000001"],
                        "caption_observation_ids": ["obs000002"],
                        "confidence": "high",
                    }
                ],
                "unpaired_asset_observation_ids": [],
                "unpaired_caption_observation_ids": [],
            }
        ),
    )
    builder = canonical_v2._visual_relation_review_builder(
        output_dir=tmp_path,
        use_llm=True,
        model_name="fake-model",
        api_url="http://example.test/chat",
        timeout_seconds=12,
    )

    review = builder(
        build_observed_index(observed),
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]},
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]},
        {
            "metadata": {"doc_id": "sample"},
            "tables": [],
            "unresolved_table_observation_runs": [],
            "excluded_table_observation_runs": [],
        },
        {"images": [{"image_id": "page-0001-review", "path": "page.png", "source": {"page": 1}}]},
    )

    assert review["visual_groups"][0]["decision_source"] == "bounded_multimodal_review"
    assert requests[0][0] == image
    assert requests[0][1].model == "fake-model"


def test_note_system_transport_composition_is_opt_in_and_bounded(tmp_path, monkeypatch) -> None:
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "x",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=100, height=100)],
        [
            make_observation("obs000001", "footnote_region", page=1, bbox=[0, 80, 100, 100]),
            make_observation(
                "obs000002",
                "text_region",
                page=1,
                bbox=[0, 82, 100, 95],
                text="note",
                role_hint="footnote_text",
            ),
        ],
    )
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    requests = []
    monkeypatch.setattr(
        canonical_v2,
        "vision_chat_json",
        lambda path, config, *, prompt: (
            requests.append((path, config, prompt))
            or {
                "systems": [
                    {
                        "kind": "page_footnote",
                        "definition_ranges": [[1, 1]],
                        "reference_scope": "page",
                        "marker_styles": ["numeric"],
                        "reset_policy": "page",
                        "confidence": "high",
                    }
                ]
            }
        ),
    )
    builder = canonical_v2._note_system_review_builder(
        output_dir=tmp_path,
        use_llm=True,
        model_name="fake-model",
        api_url="http://example.test/chat",
        timeout_seconds=12,
    )

    review = builder(
        build_observed_index(observed),
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]},
        {"metadata": {"doc_id": "sample"}, "toc_entries": []},
        {"metadata": {"doc_id": "sample"}, "pages": [{"page": 1}]},
        {"images": [{"image_id": "page-0001-review", "path": "page.png", "source": {"page": 1}}]},
    )

    assert review["note_systems"][0]["kind"] == "page_footnote"
    assert review["evidence"][0]["decision_source"] == "bounded_multimodal_review"
    assert requests[0][0] == image
    assert requests[0][1].model == "fake-model"


def test_note_marker_transport_composition_is_opt_in_and_bounded(tmp_path, monkeypatch) -> None:
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "x",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [make_observed_page(1, width=100, height=100)],
        [
            make_observation(
                "obs000001",
                "footnote_region",
                page=1,
                bbox=[0, 80, 100, 100],
                text="1 Note",
                role_hint="footnote_text",
            )
        ],
    )
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    requests = []
    monkeypatch.setattr(
        canonical_v2,
        "vision_chat_json",
        lambda path, config, *, prompt: (
            requests.append((path, config, prompt))
            or {
                "markers": [
                    {
                        "marker": "1",
                        "page": 1,
                        "observation_id": "obs000001",
                        "bbox": [0, 80, 5, 85],
                        "adjacent_text": "1 Note",
                        "confidence": "high",
                    }
                ]
            }
        ),
    )
    builder = canonical_v2._note_marker_review_builder(
        output_dir=tmp_path,
        use_llm=True,
        model_name="fake-model",
        api_url="http://example.test/chat",
        timeout_seconds=12,
    )
    plan = {
        "metadata": {
            "schema_name": "inkline_note_marker_review_plan",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "review_requests": [
            {
                "review_request_id": "nmp000001",
                "note_system_id": "ns000001",
                "region_kind": "definition",
                "regions": [
                    {"page": 1, "bbox": [0, 80, 100, 100], "observation_ids": ["obs000001"]}
                ],
                "reasons": ["definition_marker_unreadable"],
                "evidence_ids": ["nse000001"],
            }
        ],
        "not_required_note_system_ids": [],
        "unresolved_note_system_ids": [],
    }

    review = builder(
        build_observed_index(observed),
        {"images": [{"image_id": "page-0001-review", "path": "page.png", "source": {"page": 1}}]},
        plan,
    )

    assert review is not None
    assert review["outcomes"][0]["status"] == "found"
    assert requests[0][0] == image
    assert requests[0][1].model == "fake-model"


def test_note_marker_transport_handles_multi_page_multi_asset_requests(tmp_path, monkeypatch) -> None:
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "x",
            "parser_name": "test",
            "parser_mode": "structured",
        },
        [
            make_observed_page(1, width=100, height=100),
            make_observed_page(2, width=100, height=100),
        ],
        [
            make_observation(
                "obs000001",
                "footnote_region",
                page=1,
                bbox=[0, 80, 100, 100],
                text="1 Note page one",
                role_hint="footnote_text",
            ),
            make_observation(
                "obs000002",
                "footnote_region",
                page=2,
                bbox=[0, 80, 100, 100],
                text="2 Note page two",
                role_hint="footnote_text",
            ),
        ],
    )
    image_one = tmp_path / "page-one.png"
    image_two = tmp_path / "page-two.png"
    image_one.write_bytes(b"fake-one")
    image_two.write_bytes(b"fake-two")
    responses = []
    monkeypatch.setattr(
        canonical_v2,
        "vision_chat_json",
        lambda path, config, *, prompt: (
            responses.append((path, config, prompt))
            or {
                "markers": [
                    {
                        "marker": "1" if path == image_one else "2",
                        "page": 1 if path == image_one else 2,
                        "observation_id": "obs000001" if path == image_one else "obs000002",
                        "bbox": [0, 80, 5, 85],
                        "adjacent_text": "1 Note page one" if path == image_one else "2 Note page two",
                        "confidence": "high",
                    }
                ]
            }
        ),
    )
    builder = canonical_v2._note_marker_review_builder(
        output_dir=tmp_path,
        use_llm=True,
        model_name="fake-model",
        api_url="http://example.test/chat",
        timeout_seconds=12,
    )
    plan = {
        "metadata": {
            "schema_name": "inkline_note_marker_review_plan",
            "schema_version": "0.1-shadow",
            "doc_id": "sample",
        },
        "review_requests": [
            {
                "review_request_id": "nmp000001",
                "note_system_id": "ns000001",
                "region_kind": "definition",
                "regions": [
                    {"page": 1, "bbox": [0, 80, 100, 100], "observation_ids": ["obs000001"]},
                    {"page": 2, "bbox": [0, 80, 100, 100], "observation_ids": ["obs000002"]},
                ],
                "reasons": ["definition_marker_unreadable"],
                "evidence_ids": ["nse000001"],
            }
        ],
        "not_required_note_system_ids": [],
        "unresolved_note_system_ids": [],
    }

    review = builder(
        build_observed_index(observed),
        {
            "images": [
                {"image_id": "page-0001-review", "path": "page-one.png", "source": {"page": 1}},
                {"image_id": "page-0002-review", "path": "page-two.png", "source": {"page": 2}},
            ]
        },
        plan,
    )

    assert review is not None
    assert review["outcomes"][0]["status"] == "found"
    assert [call[0] for call in responses] == [image_one, image_two]


def test_v2_cli_writes_opt_in_note_marker_outputs(tmp_path) -> None:
    plan_path = tmp_path / "marker-plan.json"
    review_path = tmp_path / "markers.json"
    args = SimpleNamespace(
        observed_output=None,
        book_skeleton_output=None,
        page_review_output=None,
        visual_relation_review_output=None,
        note_system_review_output=None,
        note_marker_review_plan_output=str(plan_path),
        note_marker_review_output=str(review_path),
    )
    artifacts = {
        "note_marker_review_plan": {"metadata": {"doc_id": "sample"}},
        "note_marker_review": {"metadata": {"doc_id": "sample"}},
    }

    canonical_v2._write_optional_artifacts(args, artifacts)

    assert plan_path.exists()
    assert review_path.exists()
