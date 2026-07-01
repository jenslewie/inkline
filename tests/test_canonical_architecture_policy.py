from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bookgraph_contract_does_not_expose_parser_specific_raw_fields() -> None:
    checked = [
        ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph_audit.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph_projection.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/observed.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/observed_bookgraph.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/text_units.py",
    ]
    forbidden = ("raw_type", "raw_types", "source_block_id", "inline_display_block")

    leaks = {
        str(path.relative_to(ROOT)): [term for term in forbidden if term in path.read_text()]
        for path in checked
    }

    assert leaks == {str(path.relative_to(ROOT)): [] for path in checked}


def test_canonical_construction_policy_is_non_semantic() -> None:
    checked = [
        ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph_audit.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph_projection.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/observed.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/observed_bookgraph.py",
        ROOT / "packages/inkline-canonical/src/inkline/canonical/text_units.py",
    ]
    forbidden = ("llm_classify", "semantic_classifier", "looks_like_quote_by_text")

    leaks = {
        str(path.relative_to(ROOT)): [term for term in forbidden if term in path.read_text()]
        for path in checked
    }

    assert leaks == {str(path.relative_to(ROOT)): [] for path in checked}
