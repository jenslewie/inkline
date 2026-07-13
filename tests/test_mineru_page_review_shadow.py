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
    image_three = tmp_path / "page_0003.png"
    contact_sheet = tmp_path / "group_g0001.png"
    image_one.write_bytes(b"page one")
    image_three.write_bytes(b"page three")
    contact_sheet.write_bytes(b"contact sheet")
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
        lambda *_args, **_kwargs: {1: image_one, 3: image_three},
    )
    monkeypatch.setattr(
        page_review_shadow,
        "_render_contact_sheets",
        lambda *_args, **_kwargs: {"g0001": contact_sheet},
    )
    calls = []

    def fake_chat_json(_config, *, messages):
        calls.append(messages)
        return {
            "page_reviews": [
                {
                    "page": 1,
                    "page_role": "title_page",
                    "text_flow_action": "exclude",
                    "visual_asset_action": "retain",
                    "confidence": "high",
                },
                {
                    "page": 3,
                    "page_role": "visual_page",
                    "text_flow_action": "exclude",
                    "visual_asset_action": "retain",
                    "confidence": "high",
                },
            ]
        }

    monkeypatch.setattr(page_review_shadow, "chat_json", fake_chat_json)

    review = page_review_shadow.build_page_review_shadow(
        observed,
        {"boundaries": {"first_body_page": 3}},
        use_llm=True,
        source_pdf="sample.pdf",
    )

    assert review["candidate_pages"] == [1, 3]
    assert review["llm"]["reviewed_pages"] == [1, 3]
    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert calls[0][0]["images"] == ["Y29udGFjdCBzaGVldA=="]
    assert '"text_flow_action"' in calls[0][0]["content"]
    by_page = {record["page"]: record for record in review["pages"]}
    assert by_page[1]["llm_group_id"] == "g0001"
    assert by_page[3]["llm_group_id"] == "g0001"
