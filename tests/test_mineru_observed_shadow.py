from __future__ import annotations

from inkline.canonical.observed import validate_observed_document
from inkline.parsers.mineru.normalize.observed_shadow import build_observed_document_shadow
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


def test_build_observed_document_shadow_uses_middle_table_caption_as_title_location() -> None:
    middle = {
        "pdf_info": [
            {
                "page_idx": 346,
                "para_blocks": [
                    {
                        "type": "table_caption",
                        "bbox": [182, 121, 248, 139],
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "type": "text",
                                        "content": "帝王姓名表",
                                        "bbox": [182, 121, 248, 139],
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
        pages={347: []},
        page_sizes={347: (1000, 1000)},
        metadata=_metadata(),
        middle=middle,
    )

    validate_observed_document(document)
    observation = document["observations"][0]
    assert observation["kind"] == "text_region"
    assert observation["text"] == "帝王姓名表"
    assert observation["page"] == 347
    assert observation["role_hint"] == "title_text"
    assert observation["parser_payload"]["raw_type"] == "table_caption"
    assert "raw_type" not in observation


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
    assert observation["parser_payload"]["raw_type"] == "table"
    assert "raw_type" not in observation


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
