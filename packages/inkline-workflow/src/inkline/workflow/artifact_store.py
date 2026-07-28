from __future__ import annotations

from typing import Any, Protocol


class ArtifactStore(Protocol):
    """Optional persistence boundary; storage formats and paths stay outside stages."""

    def has(self, name: str) -> bool: ...

    def load(self, name: str) -> Any: ...

    def save(self, name: str, artifact: Any) -> None: ...
