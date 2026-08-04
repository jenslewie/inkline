from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from inkline.canonical.artifact_dag import (
    CANONICAL_ARTIFACT_CONTRACTS,
    CanonicalArtifactBundle,
    artifact_contract,
    validate_complete_artifact_bundle,
)
from inkline.canonical.schema import ValidationError


def test_canonical_artifact_bundle_is_frozen() -> None:
    bundle = CanonicalArtifactBundle(
        observed={},
        observed_index=None,  # type: ignore[arg-type]
        skeleton={},
        page_layout={},
        page_review={},
        table_flow=None,
        text_flow=None,
        page_assets=None,
    )

    with pytest.raises(FrozenInstanceError):
        bundle.text_flow = {}  # type: ignore[misc]


def test_target_artifact_contracts_freeze_revised_dependency_direction() -> None:
    assert [contract.artifact for contract in CANONICAL_ARTIFACT_CONTRACTS] == [
        "VisualRelationReview",
        "NoteSystemReview",
        "NoteMarkerReviewPlan",
        "NoteMarkerReview",
        "TextFlow",
        "TableFlow",
        "NoteInventory",
        "SectionMap",
        "NoteResolution",
        "BookGraph assembler",
    ]
    assert artifact_contract("TextFlow").inputs[-3:] == (
        "VisualRelationReview",
        "NoteSystemReview",
        "NoteMarkerReview",
    )
    assert artifact_contract("VisualRelationReview").inputs == (
        "ObservedIndex",
        "PageLayoutAnalysis",
        "PageReview",
        "TableFlow",
        "PageAssets",
    )
    assert artifact_contract("SectionMap").inputs[-3:] == (
        "TableFlow",
        "VisualRelationReview",
        "NoteInventory",
    )
    assert artifact_contract("NoteResolution").inputs == ("NoteInventory", "SectionMap")


def test_incomplete_foundation_bundle_cannot_enter_final_assembler() -> None:
    bundle = CanonicalArtifactBundle(
        observed={},
        observed_index=None,  # type: ignore[arg-type]
        skeleton={},
        page_layout={},
        page_review={},
        table_flow=None,
        text_flow=None,
        page_assets=None,
    )

    with pytest.raises(ValidationError, match="bundle is incomplete"):
        validate_complete_artifact_bundle(bundle)
