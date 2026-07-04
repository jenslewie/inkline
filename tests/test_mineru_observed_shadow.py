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
    ]
    assert [observation["role_hint"] for observation in document["observations"]] == [
        "title_text",
        "body_text",
        "unknown",
        "unknown",
        "page_number",
        "footnote_text",
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
