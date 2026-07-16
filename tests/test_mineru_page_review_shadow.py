from __future__ import annotations

from inkline.canonical import make_observed_document, make_observed_page
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
    contact_sheet_one = tmp_path / "group_g0001.png"
    contact_sheet_two = tmp_path / "group_g0002.png"
    contact_sheet_three = tmp_path / "group_g0003.png"
    image_one.write_bytes(b"page one")
    image_two.write_bytes(b"page two")
    image_three.write_bytes(b"page three")
    contact_sheet_one.write_bytes(b"contact sheet one")
    contact_sheet_two.write_bytes(b"contact sheet two")
    contact_sheet_three.write_bytes(b"contact sheet three")
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
    monkeypatch.setattr(
        page_review_shadow,
        "_render_contact_sheets",
        lambda *_args, **_kwargs: {
            "g0001": contact_sheet_one,
            "g0002": contact_sheet_two,
            "g0003": contact_sheet_three,
        },
    )
    calls = []

    def fake_chat_json(_config, *, messages):
        calls.append(messages)
        content = str(messages[0]["content"])
        if "physical pages are [1]" in content:
            pages = [1]
        elif "physical pages are [3]" in content:
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
    assert len(calls) == 3
    assert calls[0][0]["images"] == [
        "Y29udGFjdCBzaGVldCBvbmU=",
        "cGFnZSBvbmU=",
    ]
    assert '"text_flow_action"' in calls[0][0]["content"]
    by_page = {record["page"]: record for record in review["pages"]}
    assert by_page[1]["llm_group_id"] == "g0001"
    assert by_page[1]["llm_prompt_profile"] == "front_special"
    assert by_page[3]["llm_group_id"] == "g0002"
    assert by_page[3]["llm_prompt_profile"] == "front_special"
    assert by_page[2]["llm_group_id"] == "g0003"
    assert by_page[2]["llm_prompt_profile"] == "front_residual_unknown"
    assert review["llm_request_groups"] == [
        {
            "group_id": "g0001",
            "matter": "pre_body",
            "pages": [1],
            "prompt_profile": "front_special",
            "review_stage": "initial_visual",
        },
        {
            "group_id": "g0002",
            "matter": "pre_body",
            "pages": [3],
            "prompt_profile": "front_special",
            "review_stage": "initial_visual",
        },
        {
            "group_id": "g0003",
            "matter": "pre_body",
            "pages": [2],
            "prompt_profile": "front_residual_unknown",
            "review_stage": "residual_unknown",
        },
    ]


def test_page_review_uses_full_resolution_for_visual_sparse_text() -> None:
    assert page_review_shadow._needs_full_resolution_image(
        {"signals": ["visual_sparse_text"]}
    )
    assert page_review_shadow._needs_full_resolution_image(
        {"signals": ["body_profile"], "visual_kinds": ["image_region"]}
    )
    assert not page_review_shadow._needs_full_resolution_image({"signals": ["body_profile"]})


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
