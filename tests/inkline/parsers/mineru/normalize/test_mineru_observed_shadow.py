from __future__ import annotations

from copy import deepcopy

from inkline.canonical.observed import validate_observed_document
from inkline.parsers.mineru.normalize.observed_shadow import (
    build_observed_document_shadow,
    upgrade_mineru_observed_table_attrs,
)
from inkline.parsers.mineru.schema.models import NoteRef, RawBlock


def _raw(
    raw_type: str,
    text: str = "",
    bbox: list[float] | None = None,
    *,
    page: int = 1,
    index: int = 0,
) -> RawBlock:
    return RawBlock(page=page, index=index, raw_type=raw_type, text=text, bbox=bbox, raw={})


def _metadata() -> dict:
    return {
        "doc_id": "sample",
        "title": "Sample",
        "language": "en",
        "source_file": "sample.pdf",
        "parser_name": "mineru",
        "parser_mode": "vlm",
    }


def test_build_observed_document_shadow_maps_mineru_blocks_to_generic_observations() -> None:
    document = build_observed_document_shadow(
        pages={
            1: [
                _raw("title", "Chapter", [10, 20, 200, 50], index=1),
                _raw("paragraph", "Body", [10, 70, 200, 100], index=2),
                _raw("image", "", [10, 120, 300, 320], index=3),
                _raw("table", "", [10, 340, 300, 520], index=4),
                _raw("page_number", "1", [490, 960, 510, 980], index=5),
                _raw("page_footnote", "1 Note", [10, 850, 300, 900], index=6),
                _raw("ref_text", "1 Reference-like note.", [10, 910, 300, 950], index=7),
            ]
        },
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
        assets={"images": []},
    )

    validate_observed_document(document)
    assert [observation["kind"] for observation in document["observations"]] == [
        "text_region",
        "text_region",
        "image_region",
        "table_region",
        "page_marker",
        "footnote_region",
        "text_region",
    ]
    assert [observation["role_hint"] for observation in document["observations"]] == [
        "title_text",
        "body_text",
        "unknown",
        "unknown",
        "page_number",
        "footnote_text",
        "reference_text",
    ]
    assert [page["page"] for page in document["pages"]] == [1]


def test_build_observed_document_shadow_preserves_parser_payload_without_raw_top_level() -> None:
    block = _raw("paragraph", "Body1", [10, 70, 200, 100], index=2)
    block.inline_runs = [{"type": "text", "text": "Body"}]
    block.note_refs = [NoteRef(marker="1", source="inline", raw_marker="¹")]
    block.raw = {"type": "paragraph", "confidence": 0.93}

    document = build_observed_document_shadow(
        pages={1: [block]},
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
    )

    observation = document["observations"][0]
    assert observation["observation_id"] == "obs000001"
    assert observation["text"] == "Body1"
    assert observation["bbox"] == [10, 70, 200, 100]
    assert observation["attrs"]["inline_runs"] == [{"type": "text", "text": "Body"}]
    assert observation["attrs"]["note_refs"] == [
        {"marker": "1", "source": "inline", "raw_marker": "¹"}
    ]
    assert observation["parser_payload"] == {
        "raw_type": "paragraph",
        "raw": {"type": "paragraph", "confidence": 0.93},
    }
    assert "raw_type" not in observation


def test_build_observed_document_shadow_maps_mineru_index_to_toc_hint() -> None:
    document = build_observed_document_shadow(
        pages={1: [_raw("index", "Chapter 1  1", [10, 70, 900, 500], index=1)]},
        page_sizes=dict.fromkeys(range(1, 101), (1000, 1000)),
        metadata=_metadata(),
    )

    observation = document["observations"][0]
    assert observation["kind"] == "text_region"
    assert observation["role_hint"] == "toc_text"
    assert observation["parser_payload"]["raw_type"] == "index"
    assert "raw_type" not in observation


def test_build_observed_document_shadow_does_not_map_late_mineru_index_to_toc_hint() -> None:
    document = build_observed_document_shadow(
        pages={60: [_raw("index", "Late index-like region", [10, 70, 900, 500], page=60)]},
        page_sizes=dict.fromkeys(range(1, 101), (1000, 1000)),
        metadata=_metadata(),
    )

    observation = document["observations"][0]
    assert observation["role_hint"] == "unknown"
    assert observation["parser_payload"]["raw_type"] == "index"
    assert "raw_type" not in observation


def test_build_observed_document_shadow_adds_middle_title_observation_with_physical_page() -> None:
    middle = {
        "pdf_info": [
            {},
            {
                "page_idx": 466,
                "para_blocks": [
                    {
                        "type": "title",
                        "bbox": [187, 129, 257, 149],
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "type": "text",
                                        "content": "参考书目",
                                        "bbox": [187, 129, 257, 149],
                                    }
                                ]
                            }
                        ],
                    }
                ],
            },
        ]
    }

    document = build_observed_document_shadow(
        pages={467: []},
        page_sizes={467: (1000, 1000)},
        metadata=_metadata(),
        middle=middle,
    )

    validate_observed_document(document)
    observation = document["observations"][0]
    assert observation["kind"] == "text_region"
    assert observation["text"] == "参考书目"
    assert observation["page"] == 467
    assert observation["bbox"] == [187, 129, 257, 149]
    assert observation["role_hint"] == "title_text"
    assert observation["parser_payload"]["raw_type"] == "title"
    assert observation["parser_payload"]["source"] == "mineru_middle"
    assert observation["parser_payload"]["page_idx"] == 466


def test_build_observed_document_shadow_appends_table_caption_with_middle_geometry() -> None:
    table = _raw("table", "", [100, 180, 900, 700], page=347, index=4)
    table.raw = {
        "type": "table",
        "content": {
            "table_caption": [{"type": "text", "content": "Table A"}],
            "html": "<table></table>",
        },
    }
    middle = {
        "pdf_info": [
            {
                "page_idx": 346,
                "page_size": [1000, 1000],
                "preproc_blocks": [
                    {
                        "blocks": [
                            {
                                "type": "table_caption",
                                "bbox": [182, 121, 248, 139],
                                "lines": [
                                    {
                                        "spans": [
                                            {
                                                "type": "text",
                                                "content": "Table A",
                                                "bbox": [182, 121, 248, 139],
                                            }
                                        ]
                                    }
                                ],
                            }
                        ]
                    }
                ],
            },
        ]
    }

    document = build_observed_document_shadow(
        pages={347: [table, _raw("paragraph", "Body", [100, 720, 900, 760], page=347, index=5)]},
        page_sizes={347: (1000, 1000)},
        metadata=_metadata(),
        middle=middle,
    )

    validate_observed_document(document)
    table_observation, body_observation, caption_observation = document["observations"]
    assert [observation["observation_id"] for observation in document["observations"]] == [
        "obs000001",
        "obs000002",
        "obs000003",
    ]
    assert table_observation["kind"] == "table_region"
    assert table_observation["text"] == "Table A"
    assert body_observation["text"] == "Body"
    assert caption_observation["kind"] == "text_region"
    assert caption_observation["text"] == "Table A"
    assert caption_observation["page"] == 347
    assert caption_observation["bbox"] == [182, 121, 248, 139]
    assert caption_observation["role_hint"] == "caption_text"
    assert caption_observation["attrs"] == {
        "reading_order": 4,
        "visual_parent_observation_id": "obs000001",
        "source_kind": "table_caption",
        "bbox_provenance": "mineru_middle",
        "direct_anchor_eligible": True,
    }
    assert caption_observation["parser_payload"]["raw_type"] == "table_caption"
    assert caption_observation["parser_payload"]["source"] == "mineru_middle"


def test_build_observed_document_shadow_appends_chart_caption_with_region_bbox() -> None:
    chart = _raw("chart", "", [100, 180, 900, 700], page=1, index=4)
    chart.raw = {
        "type": "chart",
        "content": {
            "chart_caption": [{"type": "text", "content": "Chart A"}],
        },
    }

    document = build_observed_document_shadow(
        pages={1: [chart, _raw("paragraph", "Body", [100, 720, 900, 760], index=5)]},
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
    )

    validate_observed_document(document)
    chart_observation, body_observation, caption_observation = document["observations"]
    assert [observation["observation_id"] for observation in document["observations"]] == [
        "obs000001",
        "obs000002",
        "obs000003",
    ]
    assert chart_observation["kind"] == "image_region"
    assert chart_observation["text"] == ""
    assert body_observation["text"] == "Body"
    assert caption_observation["kind"] == "text_region"
    assert caption_observation["text"] == "Chart A"
    assert caption_observation["bbox"] == [100, 180, 900, 700]
    assert caption_observation["role_hint"] == "caption_text"
    assert caption_observation["attrs"] == {
        "reading_order": 4,
        "visual_parent_observation_id": "obs000001",
        "source_kind": "chart_caption",
        "bbox_provenance": "visual_region",
        "direct_anchor_eligible": False,
    }
    assert caption_observation["parser_payload"]["raw_type"] == "chart_caption"
    assert caption_observation["parser_payload"]["source"] == "visual_region"


def test_build_observed_document_shadow_scales_real_egypt_middle_caption_geometry() -> None:
    chart = _raw("chart", "", [113, 163, 886, 879], page=939, index=0)
    chart.raw = {
        "type": "chart",
        "content": {"chart_caption": [{"type": "text", "content": "Chart Caption"}]},
    }
    middle = {
        "pdf_info": [
            {
                "page_idx": 938,
                "page_size": [677, 433],
                "preproc_blocks": [
                    {
                        "blocks": [
                            {
                                "type": "chart_caption",
                                "bbox": [241, 48, 433, 67],
                                "lines": [
                                    {"spans": [{"type": "text", "content": "Chart Caption"}]}
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }

    document = build_observed_document_shadow(
        pages={939: [chart]},
        page_sizes={939: (1000, 1000)},
        metadata=_metadata(),
        middle=middle,
    )

    caption_observation = document["observations"][1]
    assert caption_observation["bbox"] == [355.982, 110.855, 639.586, 154.734]
    assert caption_observation["attrs"]["bbox_provenance"] == "mineru_middle"
    assert caption_observation["attrs"]["direct_anchor_eligible"] is True


def test_build_observed_document_shadow_supports_legacy_top_level_string_caption_list() -> None:
    table = _raw("table", "", [100, 180, 900, 700], page=1, index=4)
    table.raw = {
        "type": "table",
        "table_caption": ["Legacy Caption"],
    }

    document = build_observed_document_shadow(
        pages={1: [table]},
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
    )

    table_observation, caption_observation = document["observations"]
    assert table_observation["text"] == "Legacy Caption"
    assert caption_observation["text"] == "Legacy Caption"
    assert caption_observation["attrs"]["visual_parent_observation_id"] == "obs000001"
    assert caption_observation["attrs"]["direct_anchor_eligible"] is False


def test_build_observed_document_shadow_matches_identical_captions_to_enclosing_visuals() -> None:
    left_table = _raw("table", "", [100, 100, 400, 300], page=1, index=0)
    left_table.raw = {
        "type": "table",
        "content": {"table_caption": [{"type": "text", "content": "Shared Caption"}]},
    }
    right_table = _raw("table", "", [600, 100, 900, 300], page=1, index=1)
    right_table.raw = {
        "type": "table",
        "content": {"table_caption": [{"type": "text", "content": "Shared Caption"}]},
    }
    middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [1000, 1000],
                "preproc_blocks": [
                    {
                        "blocks": [
                            {
                                "type": "table_caption",
                                "bbox": [650, 320, 850, 340],
                                "lines": [
                                    {"spans": [{"type": "text", "content": "Shared Caption"}]}
                                ],
                            },
                            {
                                "type": "table_caption",
                                "bbox": [150, 320, 350, 340],
                                "lines": [
                                    {"spans": [{"type": "text", "content": "Shared Caption"}]}
                                ],
                            },
                        ]
                    }
                ],
            }
        ]
    }

    document = build_observed_document_shadow(
        pages={1: [left_table, right_table]},
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
        middle=middle,
    )

    left_caption, right_caption = document["observations"][2:]
    assert left_caption["attrs"]["visual_parent_observation_id"] == "obs000001"
    assert left_caption["bbox"] == [150, 320, 350, 340]
    assert right_caption["attrs"]["visual_parent_observation_id"] == "obs000002"
    assert right_caption["bbox"] == [650, 320, 850, 340]


def test_build_observed_document_shadow_deduplicates_identical_caption_items_per_visual() -> None:
    table = _raw("table", "", [100, 180, 900, 700], page=1, index=4)
    table.raw = {
        "type": "table",
        "content": {
            "table_caption": [
                {"type": "text", "content": "Repeated Caption"},
                {"type": "text", "content": "Repeated Caption"},
            ]
        },
    }

    document = build_observed_document_shadow(
        pages={1: [table]},
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
    )

    assert [observation["text"] for observation in document["observations"]] == [
        "Repeated Caption",
        "Repeated Caption",
    ]
    assert [observation["observation_id"] for observation in document["observations"]] == [
        "obs000001",
        "obs000002",
    ]


def test_build_observed_document_shadow_uses_table_caption_as_table_region_text() -> None:
    table = _raw("table", "", [10, 20, 900, 500], page=1, index=1)
    table.raw = {
        "type": "table",
        "content": {
            "table_caption": [{"type": "text", "content": "资料来源"}],
            "html": "<table></table>",
        },
    }

    document = build_observed_document_shadow(
        pages={1: [table]},
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
    )

    validate_observed_document(document)
    observation = document["observations"][0]
    assert observation["kind"] == "table_region"
    assert observation["text"] == "资料来源"
    assert observation["role_hint"] == "unknown"
    assert observation["attrs"]["table"] == {
        "html": "<table></table>",
        "caption_texts": ["资料来源"],
        "footnote_texts": [],
        "table_type": None,
        "nest_level": None,
        "is_continuation": False,
    }
    assert observation["parser_payload"]["raw_type"] == "table"
    assert "raw_type" not in observation


def test_build_observed_document_shadow_normalizes_table_content_without_parser_payload() -> None:
    table = _raw("table", "", [10, 20, 900, 500], page=2, index=3)
    table.raw = {
        "type": "table",
        "content": {
            "table_caption": [{"type": "text", "content": "人口统计"}],
            "table_footnote": [{"type": "text", "content": "资料来源：年鉴"}],
            "html": "<table><tr><td>甲</td><td>1</td></tr></table>",
            "table_type": "body",
            "table_nest_level": 2,
        },
    }

    document = build_observed_document_shadow(
        pages={2: [table]},
        page_sizes={2: (1000, 1000)},
        metadata=_metadata(),
    )

    assert document["observations"][0]["attrs"]["table"] == {
        "html": "<table><tr><td>甲</td><td>1</td></tr></table>",
        "caption_texts": ["人口统计"],
        "footnote_texts": ["资料来源：年鉴"],
        "table_type": "body",
        "nest_level": 2,
        "is_continuation": False,
    }


def test_build_observed_document_shadow_marks_empty_html_table_as_continuation() -> None:
    table = _raw("table", "", [10, 20, 900, 500], page=2, index=3)
    table.raw = {"type": "table", "content": {"html": ""}}

    document = build_observed_document_shadow(
        pages={2: [table]},
        page_sizes={2: (1000, 1000)},
        metadata=_metadata(),
    )

    assert document["observations"][0]["attrs"]["table"]["is_continuation"] is True


def test_upgrade_mineru_observed_table_attrs_only_reads_payload_inside_adapter() -> None:
    table = _raw("table", "", [10, 20, 900, 500], page=2, index=3)
    table.raw = {
        "type": "table",
        "content": {"html": "<table><tr><td>A</td></tr></table>"},
    }
    document = build_observed_document_shadow(
        pages={2: [table]},
        page_sizes={2: (1000, 1000)},
        metadata=_metadata(),
    )
    legacy = deepcopy(document)
    del legacy["observations"][0]["attrs"]["table"]

    upgraded = upgrade_mineru_observed_table_attrs(legacy)

    assert "table" not in legacy["observations"][0]["attrs"]
    assert upgraded["observations"][0]["attrs"]["table"]["html"].startswith("<table>")


def test_build_observed_document_shadow_deduplicates_middle_title_observation() -> None:
    middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "type": "title",
                        "bbox": [10, 20, 200, 50],
                        "lines": [{"spans": [{"type": "text", "content": "Chapter"}]}],
                    }
                ],
            }
        ]
    }

    document = build_observed_document_shadow(
        pages={1: [_raw("title", "Chapter", [10, 20, 200, 50], page=1, index=1)]},
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
        middle=middle,
    )

    assert [observation["text"] for observation in document["observations"]] == ["Chapter"]
    assert document["observations"][0]["parser_payload"]["middle_title_sources"][0]["page_idx"] == 0


def test_build_observed_document_shadow_deduplicates_middle_title_by_page_and_text() -> None:
    middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "type": "title",
                        "bbox": [10, 20, 200, 50],
                        "lines": [{"spans": [{"type": "text", "content": "Chapter"}]}],
                    }
                ],
            }
        ]
    }

    document = build_observed_document_shadow(
        pages={1: [_raw("title", "Chapter", [20, 30, 210, 60], page=1, index=1)]},
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
        middle=middle,
    )

    assert [observation["text"] for observation in document["observations"]] == ["Chapter"]
    middle_sources = document["observations"][0]["parser_payload"]["middle_title_sources"]
    assert middle_sources[0]["source"] == "mineru_middle"
    assert middle_sources[0]["bbox"] == [10, 20, 200, 50]


def test_build_observed_document_shadow_deduplicates_middle_title_collections() -> None:
    middle_title = {
        "type": "title",
        "bbox": [10, 20, 200, 50],
        "lines": [{"spans": [{"type": "text", "content": "Chapter"}]}],
    }
    middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [middle_title],
                "preproc_blocks": [middle_title],
            }
        ]
    }

    document = build_observed_document_shadow(
        pages={1: []},
        page_sizes={1: (1000, 1000)},
        metadata=_metadata(),
        middle=middle,
    )

    assert [observation["text"] for observation in document["observations"]] == ["Chapter"]
