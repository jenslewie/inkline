from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class ParseRequest:
    """Backend-neutral request for converting a source document to canonical form."""

    input_path: Path
    output_path: Path
    language: str = "zh-CN"
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_path", Path(self.input_path).expanduser().resolve())
        object.__setattr__(self, "output_path", Path(self.output_path).expanduser().resolve())


@dataclass(frozen=True)
class ParseResult:
    document: dict[str, Any]
    parser: str
    raw_output_dir: Path | None = None


@runtime_checkable
class DocumentParser(Protocol):
    @property
    def name(self) -> str:
        ...

    def parse(self, request: ParseRequest) -> ParseResult:
        """Parse one source document into the canonical contract."""
        ...
