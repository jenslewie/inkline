from __future__ import annotations

from inkline.canonical import make_observation, make_observed_document, make_observed_page
from inkline.parsers.mineru.normalize import page_review_shadow


def test_page_review_shadow_sends_only_selected_pages_to_llm(tmp_path, monkeypatch) -> None:
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
    image_two = tmp_path / "page_0002.png"
    image_three = tmp_path / "page_0003.png"
    image_one.write_bytes(b"page one")
    image_two.write_bytes(b"page two")
    image_three.write_bytes(b"page three")
    monkeypatch.setattr(
        page_review_shadow,
        "classify_observed_page_roles",
        lambda *_args, **_kwargs: [
            {"page": 1, "page_role": "title_like_page", "signals": ["sparse_centered_text"]},
            {"page": 2, "page_role": "text_flow_page", "signals": ["body_profile"]},
            {"page": 3, "page_role": "visual_page", "signals": ["visual_dominant"]},
        ],
    )
    monkeypatch.setattr(
        page_review_shadow,
        "_render_page_images",
        lambda *_args, **_kwargs: {1: image_one, 2: image_two, 3: image_three},
    )
    calls = []

    def fake_chat_json(_config, *, messages):
        calls.append(messages)
        content = str(messages[0]["content"])
        if "physical PDF page 1" in content:
            pages = [1]
        elif "physical PDF page 3" in content:
            pages = [3]
        else:
            pages = [2]
        return {
            "page_reviews": [
                {
                    "page": page,
                    "page_role": "visual_page" if page != 2 else "text_flow_page",
                    "book_block_position": "front_matter",
                    "special_page_kind": "title_page" if page == 1 else None,
                    "text_flow_action": "exclude" if page != 2 else "include",
                    "visual_asset_action": "retain" if page != 2 else "not_needed",
                    "confidence": "high",
                }
                for page in pages
            ]
        }

    monkeypatch.setattr(page_review_shadow, "chat_json", fake_chat_json)

    review = page_review_shadow.build_page_review_shadow(
        observed,
        {"boundaries": {"first_body_page": 4}},
        use_llm=True,
        source_pdf="sample.pdf",
        llm_model="qwen-test",
    )

    assert review["candidate_pages"] == [1, 2, 3]
    assert review["llm"] == {
        "model": "qwen-test",
        "prompt_version": page_review_shadow.PAGE_REVIEW_PROMPT_VERSION,
    }
    for page in (1, 2, 3):
        record = next(item for item in review["pages"] if item["page"] == page)
        assert "llm_review_matter" not in record
        assert "llm_prompt_version" not in record
        assert "llm_review_stage" not in record
    assert len(calls) == 3
    assert calls[0][0]["images"] == ["cGFnZSBvbmU="]
    assert '"text_flow_action"' in calls[0][0]["content"]
    by_page = {record["page"]: record for record in review["pages"]}
    assert by_page[1]["llm_prompt_profile"] == "front_special"
    assert by_page[3]["llm_prompt_profile"] == "front_special"
    assert by_page[2]["llm_prompt_profile"] == "front_residual_unknown"


def test_page_review_shadow_requests_each_external_page_independently(
    tmp_path, monkeypatch
) -> None:
    observed = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [make_observed_page(page, width=1000, height=1400) for page in (1, 2)],
        [
            make_observation("obs000001", "image_region", page=1, bbox=[0, 0, 1000, 1400]),
            make_observation("obs000002", "image_region", page=2, bbox=[0, 0, 1000, 1400]),
        ],
    )
    images = {page: tmp_path / f"page_{page:04d}.png" for page in (1, 2)}
    for image in images.values():
        image.write_bytes(b"image")
    monkeypatch.setattr(
        page_review_shadow,
        "classify_observed_page_roles",
        lambda *_args, **_kwargs: [
            {"page": 1, "page_role": "visual_page", "signals": ["visual_dominant"]},
            {"page": 2, "page_role": "visual_page", "signals": ["visual_dominant"]},
        ],
    )
    monkeypatch.setattr(page_review_shadow, "_render_page_images", lambda *_args, **_kwargs: images)
    prompts: list[str] = []

    def fake_chat_json(_config, *, messages):
        content = str(messages[0]["content"])
        prompts.append(content)
        page = 1 if "physical PDF page 1" in content else 2
        kind = "front_exterior_page" if page == 1 else "back_exterior_page"
        return {
            "page_reviews": [
                {
                    "page": page,
                    "page_role": "visual_page",
                    "book_block_position": "external_wrap",
                    "special_page_kind": kind,
                    "text_flow_action": "exclude",
                    "visual_asset_action": "retain",
                    "confidence": "high",
                }
            ]
        }

    monkeypatch.setattr(page_review_shadow, "chat_json", fake_chat_json)
    page_review_shadow.build_page_review_shadow(
        observed,
        {"boundaries": {"first_body_page": 3}},
        use_llm=True,
        source_pdf="sample.pdf",
        llm_model="qwen-test",
    )

    assert '"preceding_page_decision": {' not in prompts[0]
    assert '"preceding_page_decision": {' in prompts[1]
    assert '"special_page_kind": "front_exterior_page"' in prompts[1]
    assert "Review profile: after_front_exterior." in prompts[1]


def test_page_review_uses_back_exterior_followup_profile() -> None:
    assert (
        page_review_shadow._effective_prompt_profile(
            "front_visual_identity", {"special_page_kind": "back_exterior_page"}
        )
        == "after_back_exterior"
    )


def test_page_review_uses_dust_jacket_followup_profile() -> None:
    assert (
        page_review_shadow._effective_prompt_profile(
            "front_visual_identity", {"special_page_kind": "dust_jacket_spread"}
        )
        == "after_dust_jacket_spread"
    )


def test_page_review_llm_payload_excludes_provisional_actions_and_roles() -> None:
    payload = page_review_shadow._llm_page_payload(
        {
            "page": 195,
            "page_role": "text_flow_page",
            "text_flow_action": "include",
            "visual_asset_action": "not_needed",
            "skeleton_context": {"matter": "body", "is_body_section_start": False},
            "signals": ["visual_sparse_text"],
        }
    )

    assert payload == {
        "page": 195,
        "skeleton_context": {"matter": "body", "is_body_section_start": False},
        "signals": ["visual_sparse_text"],
        "visual_kinds": [],
    }
