from __future__ import annotations

import pytest

from inkline.canonical import (
    ValidationError,
    build_observed_index,
    make_observation,
    make_observed_document,
    make_observed_page,
)
from inkline.canonical.table_flow import (
    build_table_flow,
    validate_table_flow_against_sources,
)


def _document(observations: list[dict], pages: int = 4) -> dict:
    return make_observed_document(
        {
            "doc_id": "table-book",
            "title": "Table Book",
            "language": "zh",
            "source_file": "table.pdf",
            "parser_name": "test",
            "parser_mode": "fixture",
        },
        [make_observed_page(page, width=1000, height=1400) for page in range(1, pages + 1)],
        observations,
    )


def _table(
    observation_id: str,
    page: int,
    html: str,
    *,
    reading_order: int = 1,
    captions: list[str] | None = None,
    footnotes: list[str] | None = None,
) -> dict:
    return make_observation(
        observation_id,
        "table_region",
        page=page,
        bbox=[100, 200, 900, 1200],
        attrs={
            "reading_order": reading_order,
            "table": {
                "html": html,
                "caption_texts": captions or [],
                "footnote_texts": footnotes or [],
                "table_type": "body",
                "nest_level": 0,
                "is_continuation": not html.strip(),
            },
        },
    )


def _page_review(
    pages: int,
    *,
    excluded: set[int] | None = None,
) -> dict:
    excluded = excluded or set()
    return {
        "metadata": {"doc_id": "table-book"},
        "candidate_pages": [],
        "pages": [
            {
                "page": page,
                "page_role": "visual_page" if page in excluded else "text_flow_page",
                "book_block_position": "body",
                "special_page_kind": None,
                "text_flow_action": "exclude" if page in excluded else "include",
                "visual_asset_action": "retain" if page in excluded else "not_needed",
            }
            for page in range(1, pages + 1)
        ],
    }


def test_build_table_flow_keeps_complete_html_and_adjacent_continuation_pages() -> None:
    html = "<table><tr><th>地名</th><th>英文</th></tr><tr><td>楼兰</td><td>Loulan</td></tr></table>"
    observed = _document(
        [
            _table(
                "obs000001",
                1,
                html,
                captions=["丝绸之路主要地名中英古今对照表"],
                footnotes=["资料来源：附录"],
            ),
            _table("obs000002", 2, ""),
            _table("obs000003", 3, ""),
            _table("obs000004", 4, ""),
            make_observation(
                "obs000005",
                "text_region",
                text="丝绸之路主要地名中英古今对照表",
                page=1,
                bbox=[100, 100, 900, 160],
                role_hint="caption_text",
                attrs={
                    "reading_order": 0,
                    "visual_parent_observation_id": "obs000001",
                    "source_kind": "table_caption",
                },
            ),
        ]
    )
    index = build_observed_index(observed)

    table_flow = build_table_flow(observed, index, _page_review(4))

    assert table_flow["unresolved_table_observation_runs"] == []
    assert table_flow["excluded_table_observation_runs"] == []
    assert table_flow["tables"] == [
        {
            "table_id": "tbl000001",
            "html": html,
            "text": "地名\t英文\n楼兰\tLoulan",
            "pages": [1, 2, 3, 4],
            "spans": [
                {
                    "observation_id": f"obs{number:06d}",
                    "page": number,
                    "bbox": [100, 200, 900, 1200],
                }
                for number in range(1, 5)
            ],
            "observation_ids": [
                "obs000001",
                "obs000002",
                "obs000003",
                "obs000004",
            ],
            "primary_observation_id": "obs000001",
            "caption_observation_ids": ["obs000005"],
            "caption_texts": ["丝绸之路主要地名中英古今对照表"],
            "footnote_texts": ["资料来源：附录"],
            "attrs": {"table_type": "body", "nest_level": 0},
        }
    ]


def test_build_table_flow_keeps_adjacent_non_empty_tables_separate() -> None:
    observed = _document(
        [
            _table("obs000001", 1, "<table><tr><td>A</td></tr></table>"),
            _table("obs000002", 2, "<table><tr><td>B</td></tr></table>"),
        ],
        pages=2,
    )

    table_flow = build_table_flow(
        observed,
        build_observed_index(observed),
        _page_review(2),
    )

    assert [table["observation_ids"] for table in table_flow["tables"]] == [
        ["obs000001"],
        ["obs000002"],
    ]


def test_build_table_flow_exposes_continuation_without_primary() -> None:
    observed = _document([_table("obs000001", 2, "")], pages=2)

    table_flow = build_table_flow(
        observed,
        build_observed_index(observed),
        _page_review(2),
    )

    assert table_flow["tables"] == []
    assert table_flow["unresolved_table_observation_runs"] == [
        {
            "observation_ids": ["obs000001"],
            "pages": [2],
            "reason": "continuation_without_primary",
        }
    ]


def test_build_table_flow_refuses_parser_private_table_payload() -> None:
    observed = _document(
        [
            make_observation(
                "obs000001",
                "table_region",
                page=1,
                bbox=[100, 200, 900, 1200],
                parser_payload={
                    "raw_type": "table",
                    "raw": {"content": {"html": "<table><tr><td>A</td></tr></table>"}},
                },
            )
        ],
        pages=1,
    )

    table_flow = build_table_flow(
        observed,
        build_observed_index(observed),
        _page_review(1),
    )

    assert table_flow["tables"] == []
    assert table_flow["unresolved_table_observation_runs"][0]["reason"] == (
        "missing_normalized_table_content"
    )


def test_validate_table_flow_rejects_source_span_drift() -> None:
    observed = _document(
        [_table("obs000001", 1, "<table><tr><td>A</td></tr></table>")],
        pages=1,
    )
    index = build_observed_index(observed)
    review = _page_review(1)
    table_flow = build_table_flow(observed, index, review)
    table_flow["tables"][0]["spans"][0]["page"] = 2

    with pytest.raises(ValidationError, match=r"pages must match spans|differs from source"):
        validate_table_flow_against_sources(table_flow, observed, index, review)


def test_build_table_flow_excludes_visual_page_table_candidate() -> None:
    observed = _document(
        [_table("obs000001", 1, "<table><tr><td>A</td></tr></table>")],
        pages=1,
    )

    table_flow = build_table_flow(
        observed,
        build_observed_index(observed),
        _page_review(1, excluded={1}),
    )

    assert table_flow["tables"] == []
    assert table_flow["unresolved_table_observation_runs"] == []
    assert table_flow["excluded_table_observation_runs"] == [
        {
            "observation_ids": ["obs000001"],
            "pages": [1],
            "reason": "excluded_by_page_review",
        }
    ]


def test_build_table_flow_exposes_page_review_split_across_one_table() -> None:
    observed = _document(
        [
            _table("obs000001", 1, "<table><tr><td>A</td></tr></table>"),
            _table("obs000002", 2, ""),
        ],
        pages=2,
    )

    table_flow = build_table_flow(
        observed,
        build_observed_index(observed),
        _page_review(2, excluded={1}),
    )

    assert table_flow["tables"] == []
    assert table_flow["unresolved_table_observation_runs"] == [
        {
            "observation_ids": ["obs000001", "obs000002"],
            "pages": [1, 2],
            "reason": "page_review_splits_table_candidate",
        }
    ]
