from __future__ import annotations

import json
from pathlib import Path

from inkline.canonical import (
    build_bookgraph_from_artifacts,
    build_internal_canonical_from_artifacts,
)
from inkline.workflow import build_canonical_artifacts, canonical_artifact_stages

ROOT = Path(__file__).resolve().parents[3]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_resolved_workflow_builds_text_flow_once_and_assembly_reuses_it(monkeypatch) -> None:
    observed = _load(ROOT / "data/outputs/golden/observed/中日交流两千年_observed.json")
    skeleton = _load(ROOT / "data/outputs/golden/skeleton/中日交流两千年_skeleton.json")
    page_review = _load(
        ROOT / "data/outputs/golden/page-review/中日交流两千年/中日交流两千年_page_review.json"
    )
    from inkline.workflow import canonical_v2

    actual = canonical_v2.build_text_flow
    calls = []

    def counted(*args, **kwargs):
        calls.append(args)
        return actual(*args, **kwargs)

    monkeypatch.setattr(canonical_v2, "build_text_flow", counted)
    stages = canonical_artifact_stages(
        skeleton_builder=lambda observed, observed_index: skeleton,
        page_review_builder=lambda observed, skeleton, page_layout: page_review,
    )

    bundle = build_canonical_artifacts(observed, stages=stages)
    public = build_bookgraph_from_artifacts(bundle)
    internal = build_internal_canonical_from_artifacts(bundle, public)

    assert len(calls) == 1
    assert bundle.table_flow is not None
    assert bundle.text_flow is not None
    assert bundle.page_assets == observed["assets"]
    assert bundle.page_assets is not observed["assets"]
    source_unit_ids = {
        record["debug"]["attrs"]["source_text_unit_id"] for record in internal["nodes"]
    }
    assert source_unit_ids <= {unit["unit_id"] for unit in bundle.text_flow["text_units"]}


def test_unresolved_review_returns_intermediate_bundle_without_text_flow() -> None:
    observed = _load(ROOT / "data/outputs/golden/observed/中日交流两千年_observed.json")
    skeleton = _load(ROOT / "data/outputs/golden/skeleton/中日交流两千年_skeleton.json")
    unresolved = _load(
        ROOT / "data/outputs/golden/page-review/中日交流两千年/中日交流两千年_page_review.json"
    )
    unresolved["pages"][0]["text_flow_action"] = "needs_review"
    unresolved["pages"][0]["llm_review_status"] = "not_sent"
    unresolved["pages"][0]["decision_source"] = "llm_required"
    stages = canonical_artifact_stages(
        skeleton_builder=lambda observed, observed_index: skeleton,
        page_review_builder=lambda observed, skeleton, page_layout: unresolved,
    )

    bundle = build_canonical_artifacts(observed, stages=stages)

    assert bundle.table_flow is None
    assert bundle.text_flow is None
