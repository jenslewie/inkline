from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from inkline.canonical.artifact_dag import CanonicalArtifactBundle


def test_canonical_artifact_bundle_is_frozen() -> None:
    bundle = CanonicalArtifactBundle(
        observed={},
        observed_index=None,  # type: ignore[arg-type]
        skeleton={},
        page_layout={},
        page_review={},
        text_flow=None,
        page_assets=None,
    )

    with pytest.raises(FrozenInstanceError):
        bundle.text_flow = {}  # type: ignore[misc]
