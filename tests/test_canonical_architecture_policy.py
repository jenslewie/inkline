from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKED_CANONICAL_FILES = [
    ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph/schema.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph/audit.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph/projection.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/bookgraph/from_observed.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/observed/schema.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/observed/text_unit_layout.py",
    ROOT / "packages/inkline-canonical/src/inkline/canonical/observed/text_units.py",
]


def test_bookgraph_contract_does_not_expose_parser_specific_raw_fields() -> None:
    checked = CHECKED_CANONICAL_FILES
    forbidden = ("raw_type", "raw_types", "source_block_id", "inline_display_block")

    leaks = {
        str(path.relative_to(ROOT)): [term for term in forbidden if term in path.read_text()]
        for path in checked
    }

    assert leaks == {str(path.relative_to(ROOT)): [] for path in checked}


def test_canonical_construction_policy_is_non_semantic() -> None:
    checked = CHECKED_CANONICAL_FILES
    forbidden = ("llm_classify", "semantic_classifier", "looks_like_quote_by_text")

    leaks = {
        str(path.relative_to(ROOT)): [term for term in forbidden if term in path.read_text()]
        for path in checked
    }

    assert leaks == {str(path.relative_to(ROOT)): [] for path in checked}
