from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from inkline.canonical.observed.index import ObservedIndex


@dataclass(frozen=True)
class CanonicalArtifactBundle:
    """Immutable references to one coherent set of canonical pipeline artifacts."""

    observed: dict[str, Any]
    observed_index: ObservedIndex
    skeleton: dict[str, Any]
    page_layout: dict[str, Any]
    page_review: dict[str, Any]
    table_flow: dict[str, Any] | None
    text_flow: dict[str, Any] | None
    page_assets: dict[str, Any] | None
