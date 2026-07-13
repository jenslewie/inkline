from __future__ import annotations

from inkline.canonical import (
    build_bookgraph_from_observed,
    make_observation,
    make_observed_document,
    make_observed_page,
)


def test_resolved_page_review_excludes_visual_only_page_text_from_bookgraph() -> None:
    document = make_observed_document(
        {
            "doc_id": "sample",
            "title": "Sample",
            "language": "zh-CN",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [
            make_observed_page(1, width=1000, height=1400),
            make_observed_page(2, width=1000, height=1400),
        ],
        [
            make_observation(
                "obs000001",
                "text_region",
                text="Book title",
                page=1,
                bbox=[250, 300, 750, 400],
                role_hint="title_text",
            ),
            make_observation(
                "obs000002",
                "text_region",
                text="Body text.",
                page=2,
                bbox=[100, 200, 900, 800],
                role_hint="body_text",
            ),
        ],
    )
    page_review = {
        "metadata": {"schema_name": "inkline_page_review", "schema_version": "0.1-shadow"},
        "candidate_pages": [1],
        "pages": [
            {
                "page": 1,
                "page_role": "title_page",
                "text_flow_action": "exclude",
                "visual_asset_action": "retain",
                "decision_source": "llm_page_review",
                "llm_review_status": "sent_and_resolved",
                "signals": [],
                "confidence": "high",
            },
            {
                "page": 2,
                "page_role": "text_flow_page",
                "text_flow_action": "include",
                "visual_asset_action": "not_needed",
                "decision_source": "layout_and_skeleton",
                "llm_review_status": "not_selected",
                "signals": ["body_profile"],
            },
        ],
    }

    graph = build_bookgraph_from_observed(document, page_review=page_review)

    assert [node["text"] for node in graph["nodes"]] == ["Body text."]
