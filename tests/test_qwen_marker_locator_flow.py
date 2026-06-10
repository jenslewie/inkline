from argparse import Namespace
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from inkline.parsers.mineru.normalize.core import (
    _marker_locator_block_dpi,
    _marker_locator_page_dpi,
    _missing_or_unreliable_body_ref_pages,
)
from inkline.parsers.mineru.reconcile.notes import qwen_marker_locator
from inkline.parsers.mineru.reconcile.notes.qwen_evidence import (
    _collect_qwen_marker_evidence,
    _page_footnote_markers_by_page,
    _retry_missing_single_marker_body_refs,
)
from inkline.parsers.mineru.reconcile.notes.qwen_api import _call_qwen_marker_locator
from inkline.parsers.mineru.reconcile.notes.qwen_page_plan import _problem_page_plan
from inkline.parsers.mineru.reconcile.notes.qwen_marker_locator import (
    QwenMarkerLocatorConfig,
    QwenMarkerPageEvidence,
    run_qwen_marker_locator_repairs,
)
from inkline.parsers.mineru.reconcile.notes.qwen_types import _PROMPT_VERSION


def test_marker_locator_page_and_block_dpi_config() -> None:
    args = Namespace(marker_locator_dpi=None, marker_locator_page_dpi=300, marker_locator_block_dpi=200)

    assert _marker_locator_page_dpi(args) == 300
    assert _marker_locator_block_dpi(args) == 200

    default_args = Namespace(
        marker_locator_dpi=None,
        marker_locator_page_dpi=None,
        marker_locator_block_dpi=None,
    )

    assert _marker_locator_page_dpi(default_args) == 300
    assert _marker_locator_block_dpi(default_args) == 200

    legacy_args = Namespace(marker_locator_dpi=250, marker_locator_page_dpi=None, marker_locator_block_dpi=None)

    assert _marker_locator_page_dpi(legacy_args) == 250
    assert _marker_locator_block_dpi(legacy_args) == 250


def test_page_then_block_retries_missing_pages_with_block_dpi(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_problem_page_plan(_blocks):
        return SimpleNamespace(footnote_pages={1}, body_ref_pages={1, 2})

    def fake_collect(_blocks, pages, config, *, pass_name, footnote_pages, body_ref_pages, expected_body_markers_by_page):
        calls.append(
            {
                "pages": list(pages),
                "dpi": config.dpi,
                "body_mode": config.body_mode,
                "pass_name": pass_name,
                "footnote_pages": sorted(footnote_pages),
                "body_ref_pages": sorted(body_ref_pages),
                "expected_body_markers_by_page": expected_body_markers_by_page,
            }
        )
        return [
            QwenMarkerPageEvidence(
                page=page,
                image=f"page_{page}.png",
                crop_bbox_pdf=[],
                dpi=config.dpi,
                raw_json={},
            )
            for page in pages
        ]

    # Patch at the definition module (monkeypatch principle)
    monkeypatch.setattr("inkline.parsers.mineru.reconcile.notes.qwen_page_plan._problem_page_plan", fake_problem_page_plan)
    monkeypatch.setattr("inkline.parsers.mineru.reconcile.notes.qwen_evidence._collect_qwen_marker_evidence", fake_collect)

    config = QwenMarkerLocatorConfig(
        source_pdf=tmp_path / "source.pdf",
        artifact_dir=tmp_path / "qwen",
        page_dpi=300,
        block_dpi=200,
        body_mode="page_then_block",
    )
    evidence = run_qwen_marker_locator_repairs(
        [],
        config,
        missing_body_ref_pages_after_page=lambda page_evidence: [2, 5],
    )

    assert [(item.page, item.dpi) for item in evidence] == [(1, 300), (2, 300), (2, 200), (5, 200)]
    assert calls == [
        {
            "pages": [1, 2],
            "dpi": 300,
            "body_mode": "page",
            "pass_name": "initial",
            "footnote_pages": [1],
            "body_ref_pages": [1, 2],
            "expected_body_markers_by_page": {},
        },
        {
            "pages": [2, 5],
            "dpi": 200,
            "body_mode": "block",
            "pass_name": "body_ref_retry",
            "footnote_pages": [],
            "body_ref_pages": [2, 5],
            "expected_body_markers_by_page": {},
        },
    ]


def test_missing_pages_include_resolved_refs_without_inline_run() -> None:
    blocks = [
        {
            "block_id": "b_body",
            "type": "paragraph",
            "text": "正文里有一个脚注引用位置。",
            "source": {"page": 76},
            "attrs": {
                "note_refs": [
                    {
                        "marker": "1",
                        "source": "equation_inline",
                        "source_page": 76,
                        "target_note_id": "note_1",
                    }
                ]
            },
        },
        {
            "block_id": "b_note",
            "type": "footnote",
            "text": "1 脚注内容",
            "source": {"page": 76},
            "attrs": {"note_id": "note_1", "note_marker": "1"},
        },
    ]

    assert _missing_or_unreliable_body_ref_pages(blocks) == []

    evidence = [
        QwenMarkerPageEvidence(
            page=76,
            image="page_76.png",
            crop_bbox_pdf=[],
            dpi=150,
            raw_json={},
            body_refs=[{"marker": "1"}],
        )
    ]

    assert _missing_or_unreliable_body_ref_pages(blocks, qwen_marker_pages=evidence) == [76]

    blocks[0]["attrs"]["inline_runs"] = [
        {"type": "text", "text": "正文里有一个"},
        {
            "type": "note_ref",
            "marker": "1",
            "source": "equation_inline",
            "source_page": 76,
            "target_note_id": "note_1",
        },
        {"type": "text", "text": "脚注引用位置。"},
    ]

    assert _missing_or_unreliable_body_ref_pages(blocks, qwen_marker_pages=evidence) == []


def test_qwen_definition_hints_split_merged_middle_footnote() -> None:
    blocks = [
        {
            "block_id": "b_note",
            "type": "footnote",
            "text": "1 Times of London, December 24, 1948.\nVia Appia, 古罗马时期的大路。",
            "source": {"page": 22, "bbox": [100, 800, 900, 900]},
            "attrs": {"raw_type": "page_footnote", "role": "page_footnote"},
        }
    ]
    evidence = [
        QwenMarkerPageEvidence(
            page=22,
            image="page_22.png",
            crop_bbox_pdf=[],
            dpi=150,
            raw_json={},
            footnote_defs=[
                {"marker": "1", "near_text": "Times of London", "confidence": "medium"},
                {"marker": "*", "near_text": "Via Appia", "confidence": "medium"},
            ],
        )
    ]

    qwen_marker_locator.apply_qwen_footnote_markers(blocks, evidence)

    assert [block["block_id"] for block in blocks] == ["b_note", "b_note_2"]
    assert [block["text"] for block in blocks] == [
        "1 Times of London, December 24, 1948.",
        "*Via Appia, 古罗马时期的大路。",
    ]
    assert [block["attrs"]["note_marker"] for block in blocks] == ["1", "*"]
    assert blocks[1]["attrs"]["split_reason"] == "qwen_footnote_definition_count"


def test_single_marker_retry_merges_missing_marker(monkeypatch, tmp_path: Path) -> None:
    prompts = []

    def fake_call(_image_path, _config, *, prompt):
        prompts.append(prompt)
        return {
            "body_refs": [
                {
                    "marker": "2",
                    "before_text": "左侧文字",
                    "after_text": "右侧文字",
                    "quote": "左侧文字2右侧文字",
                    "confidence": "high",
                }
            ]
        }

    # Patch at the definition module (monkeypatch principle)
    monkeypatch.setattr("inkline.parsers.mineru.reconcile.notes.qwen_api._call_qwen_marker_locator", fake_call)
    config = QwenMarkerLocatorConfig(
        source_pdf=tmp_path / "source.pdf",
        artifact_dir=tmp_path / "qwen",
    )

    refs, model_calls = _retry_missing_single_marker_body_refs(
        tmp_path / "page.png",
        config,
        ["1", "2"],
        [
            {
                "marker": "1",
                "before_text": "已有左",
                "after_text": "已有右",
                "quote": "已有左1已有右",
                "confidence": "high",
            }
        ],
    )

    assert [ref["marker"] for ref in refs] == ["1", "2"]
    assert len(prompts) == 1
    assert "marker：2" in prompts[0]
    assert model_calls[0]["kind"] == "body_refs_single_marker_retry"
    assert model_calls[0]["marker"] == "2"


def test_problem_page_plan_keeps_scoped_endnote_body_candidates() -> None:
    blocks = [
        {"block_id": "b_chapter", "type": "heading", "text": "1 第一章", "source": {"page": 1}, "attrs": {}},
        {
            "block_id": "b_ref_1",
            "type": "paragraph",
            "text": "已有引用一。",
            "source": {"page": 2, "bbox": [10, 10, 100, 30]},
            "attrs": {"note_refs": [{"marker": "1"}]},
        },
        {
            "block_id": "b_missing",
            "type": "paragraph",
            "text": "这里应有第二条引用。",
            "source": {"page": 2, "bbox": [10, 40, 100, 60]},
            "attrs": {},
        },
        {
            "block_id": "b_ref_3",
            "type": "paragraph",
            "text": "已有引用三。",
            "source": {"page": 2, "bbox": [10, 70, 100, 90]},
            "attrs": {"note_refs": [{"marker": "3"}]},
        },
        {"block_id": "b_notes", "type": "heading", "text": "注释", "source": {"page": 10}, "attrs": {}},
        {"block_id": "b_note_1", "type": "list_item", "text": "1. 第一条注释。", "source": {"page": 10}, "attrs": {}},
        {"block_id": "b_note_2", "type": "list_item", "text": "2. 第二条注释。", "source": {"page": 10}, "attrs": {}},
        {"block_id": "b_note_3", "type": "list_item", "text": "3. 第三条注释。", "source": {"page": 10}, "attrs": {}},
    ]

    plan = _problem_page_plan(blocks)

    assert 2 in plan.body_ref_pages
    assert id(blocks[2]) in plan.body_candidate_block_ids


def test_complete_cache_hit_does_not_raise_unboundlocalerror(monkeypatch, tmp_path: Path) -> None:
    """Regression test: when cached evidence fully covers both footnote and body
    refs, the conditional branch is skipped and `item` must come from
    cached_item — otherwise evidence.append(item) raises UnboundLocalError."""

    # Build a fully-satisfied cached item (has footnote_defs + matching body_ref_source)
    cached_item = QwenMarkerPageEvidence(
        page=1,
        image=str(tmp_path / "qwen" / "page_0001_200dpi_qwen_full_page.png"),
        crop_bbox_pdf=[0.0, 0.0, 595.0, 842.0],
        dpi=200,
        raw_json={"footnote_defs": [{"marker": "1"}], "body_ref_source": "full_page"},
        body_refs=[{"marker": "1"}],
        footnote_defs=[{"marker": "1"}],
        prompt_version=_PROMPT_VERSION,
    )
    cache_key = (1, "page_0001_200dpi_qwen_full_page.png")
    fake_cache = {cache_key: cached_item}

    # Mock fitz (PyMuPDF) — injected via sys.modules since it's imported inside the function
    fake_page = MagicMock()
    fake_page.rect = MagicMock(x0=0, y0=0, x1=595, y1=842)
    fake_doc = MagicMock()
    fake_doc.page_count = 1
    fake_doc.__getitem__ = MagicMock(return_value=fake_page)
    fake_doc.__enter__ = MagicMock(return_value=fake_doc)
    fake_doc.__exit__ = MagicMock(return_value=False)
    fake_fitz = MagicMock(open=MagicMock(return_value=fake_doc))
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    # Patch _read_existing_evidence to return our cache
    monkeypatch.setattr("inkline.parsers.mineru.reconcile.notes.qwen_evidence._read_existing_evidence", MagicMock(return_value=fake_cache))
    # Patch render to avoid real PDF rendering
    monkeypatch.setattr("inkline.parsers.mineru.reconcile.notes.qwen_prompt._render_full_page", MagicMock())
    # Patch timing to avoid needing a real config with all fields
    monkeypatch.setattr("inkline.parsers.mineru.reconcile.notes.qwen_evidence._write_timing_event", MagicMock())

    config = QwenMarkerLocatorConfig(
        source_pdf=tmp_path / "source.pdf",
        artifact_dir=tmp_path / "qwen",
        reuse_evidence=True,
    )

    evidence = _collect_qwen_marker_evidence(
        [],
        [1],
        config,
        pass_name="initial",
        footnote_pages={1},
        body_ref_pages={1},
    )

    assert len(evidence) == 1
    assert evidence[0].page == 1
    assert evidence[0].footnote_defs == [{"marker": "1"}]
    assert evidence[0].body_refs == [{"marker": "1"}]
