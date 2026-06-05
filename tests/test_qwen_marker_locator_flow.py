from pathlib import Path
from types import SimpleNamespace

from mineru_normalizer.canonical.core import _marker_locator_block_dpi, _marker_locator_page_dpi
from mineru_normalizer.reconcile.notes import qwen_marker_locator
from mineru_normalizer.reconcile.notes.qwen_marker_locator import (
    QwenMarkerLocatorConfig,
    QwenMarkerPageEvidence,
    run_qwen_marker_locator_repairs,
)


def test_marker_locator_page_and_block_dpi_config() -> None:
    args = SimpleNamespace(marker_locator_dpi=None, marker_locator_page_dpi=300, marker_locator_block_dpi=200)

    assert _marker_locator_page_dpi(args) == 300
    assert _marker_locator_block_dpi(args) == 200

    legacy_args = SimpleNamespace(marker_locator_dpi=250, marker_locator_page_dpi=None, marker_locator_block_dpi=None)

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

    monkeypatch.setattr(qwen_marker_locator, "_problem_page_plan", fake_problem_page_plan)
    monkeypatch.setattr(qwen_marker_locator, "_collect_qwen_marker_evidence", fake_collect)

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
