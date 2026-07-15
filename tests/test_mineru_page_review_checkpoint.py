from __future__ import annotations

import json

import pytest

from inkline.canonical import make_observed_document, make_observed_page
from inkline.parsers.mineru.normalize import page_review_shadow


def test_page_review_checkpoint_resumes_after_a_failed_group(tmp_path, monkeypatch) -> None:
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, 4)],
        [],
    )
    image_one = tmp_path / "page_0001.png"
    image_three = tmp_path / "page_0003.png"
    group_one = tmp_path / "group_g0001.jpg"
    group_two = tmp_path / "group_g0002.jpg"
    for image in (image_one, image_three, group_one, group_two):
        image.write_bytes(b"image")
    checkpoint_path = tmp_path / "page_review.checkpoint.json"
    monkeypatch.setattr(
        page_review_shadow,
        "classify_observed_page_roles",
        lambda *_args, **_kwargs: [
            {"page": 1, "page_role": "visual_page", "signals": ["visual_dominant"]},
            {"page": 2, "page_role": "text_flow_page", "signals": ["body_profile"]},
            {"page": 3, "page_role": "visual_page", "signals": ["visual_dominant"]},
        ],
    )
    monkeypatch.setattr(
        page_review_shadow,
        "_render_page_images",
        lambda *_args, **_kwargs: {1: image_one, 3: image_three},
    )
    monkeypatch.setattr(
        page_review_shadow,
        "_render_contact_sheets",
        lambda *_args, **_kwargs: {"g0001": group_one, "g0002": group_two},
    )
    monkeypatch.setattr(page_review_shadow, "PAGE_REVIEW_MAX_GROUP_PAGES", 1)

    first_run_pages: list[int] = []

    def fail_second_group(_config, *, messages):
        page = _page_from_message(messages)
        first_run_pages.append(page)
        if page == 3:
            raise RuntimeError("temporary model failure")
        return {"page_reviews": [_decision(page)]}

    monkeypatch.setattr(page_review_shadow, "chat_json", fail_second_group)
    with pytest.raises(RuntimeError, match="temporary model failure"):
        page_review_shadow.build_page_review_shadow(
            observed,
            {
                "boundaries": {"first_body_page": 4},
                "toc_entries": [{"role": "front_matter", "selected_start_page": 1}],
            },
            use_llm=True,
            source_pdf="sample.pdf",
            checkpoint_path=checkpoint_path,
            llm_model="qwen-test",
        )

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert first_run_pages == [1, 3]
    assert checkpoint["checkpoint"]["status"] == "failed"
    assert checkpoint["checkpoint"]["completed_group_ids"] == ["g0001"]
    assert checkpoint["checkpoint"]["failed_group_id"] == "g0002"
    assert checkpoint["group_decisions"]["g0001"] == [_decision(1)]

    resumed_pages: list[int] = []

    def resolve_remaining_group(_config, *, messages):
        page = _page_from_message(messages)
        resumed_pages.append(page)
        return {"page_reviews": [_decision(page)]}

    monkeypatch.setattr(page_review_shadow, "chat_json", resolve_remaining_group)
    review = page_review_shadow.build_page_review_shadow(
        observed,
        {
            "boundaries": {"first_body_page": 4},
            "toc_entries": [{"role": "front_matter", "selected_start_page": 1}],
        },
        use_llm=True,
        source_pdf="sample.pdf",
        checkpoint_path=checkpoint_path,
        llm_model="qwen-test",
    )

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert resumed_pages == [3]
    assert checkpoint["checkpoint"]["status"] == "complete"
    assert checkpoint["checkpoint"]["completed_group_ids"] == ["g0001", "g0002"]
    assert review["llm"]["model"] == "qwen-test"
    assert review["llm"]["prompt_version"] == page_review_shadow.PAGE_REVIEW_PROMPT_VERSION


def test_page_review_checkpoint_preserves_invalid_model_response(tmp_path) -> None:
    checkpoint_path = tmp_path / "page_review.checkpoint.json"
    checkpoint = {
        "checkpoint": {
            "status": "in_progress",
            "completed_group_ids": [],
            "failed_group_id": None,
            "error": None,
        },
        "group_decisions": {},
    }
    response = {
        "page_reviews": [
            {
                "page": 267,
                "page_role": "body_page",
                "book_block_position": "body",
                "special_page_kind": None,
                "text_flow_action": "include",
                "visual_asset_action": "retain",
                "confidence": "high",
            }
        ]
    }

    page_review_shadow._record_checkpoint_failure(
        checkpoint_path,
        checkpoint,
        "g0018",
        ValueError("page_role is invalid"),
        raw_response=response,
    )

    written = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert written["checkpoint"]["failed_group_id"] == "g0018"
    assert written["failed_group_response"] == response


def test_page_review_checkpoint_archives_an_older_review_contract_and_restarts(tmp_path) -> None:
    checkpoint_path = tmp_path / "page_review.checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "fingerprint": {
                    "doc_id": "sample",
                    "candidate_pages": [1],
                    "request_groups": [{"group_id": "g0001", "pages": [1]}],
                    "llm_model": "qwen-test",
                }
            }
        ),
        encoding="utf-8",
    )
    plan = {
        "metadata": {
            "schema_name": "inkline_page_review",
            "schema_version": "0.4-shadow",
            "doc_id": "sample",
            "title": "Sample",
        },
        "candidate_pages": [1],
    }

    checkpoint = page_review_shadow._load_page_review_checkpoint(
        checkpoint_path,
        plan=plan,
        request_groups=[{"group_id": "g0001", "pages": [1]}],
        llm_model="qwen-test",
    )

    stale_path = checkpoint_path.with_name(f"{checkpoint_path.name}.stale")
    assert stale_path.exists()
    assert json.loads(stale_path.read_text(encoding="utf-8"))["fingerprint"]["candidate_pages"] == [1]
    assert checkpoint["checkpoint"]["status"] == "in_progress"
    assert checkpoint["group_decisions"] == {}
    assert json.loads(checkpoint_path.read_text(encoding="utf-8")) == checkpoint


def _page_from_message(messages: list[dict[str, object]]) -> int:
    content = str(messages[0]["content"])
    if "physical pages are [1]" in content:
        return 1
    if "physical pages are [3]" in content:
        return 3
    raise AssertionError(f"Unexpected LLM message: {content}")


def _decision(page: int) -> dict[str, str | int]:
    return {
        "page": page,
        "page_role": "visual_page",
        "book_block_position": "front_matter",
        "special_page_kind": None,
        "text_flow_action": "exclude",
        "visual_asset_action": "retain",
        "confidence": "high",
    }
