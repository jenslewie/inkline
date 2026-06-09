from __future__ import annotations

from dataclasses import dataclass

import pytest

from inkline.canonical import sample_document
from inkline.parse import registry
from inkline.parse import (
    ParseRequest,
    ParseResult,
    ParserNotFoundError,
    parse_document,
    register_parser,
)


@dataclass(frozen=True)
class _SampleParser:
    name: str = "test-sample"

    def parse(self, request: ParseRequest) -> ParseResult:
        return ParseResult(document=sample_document(), parser=self.name)


@dataclass(frozen=True)
class _DiscoveredParser:
    name: str = "discovered"

    def parse(self, request: ParseRequest) -> ParseResult:
        return ParseResult(document=sample_document(), parser=self.name)


@dataclass(frozen=True)
class _FakeEntryPoint:
    name: str = "discovered"
    value: str = "tests:_DiscoveredParser"

    def load(self):
        return _DiscoveredParser


def test_parse_document_dispatches_through_registered_parser(tmp_path) -> None:
    register_parser(_SampleParser(), replace=True)
    request = ParseRequest(tmp_path / "input.pdf", tmp_path / "canonical.json")

    result = parse_document(request, "test-sample")

    assert result.parser == "test-sample"
    assert result.document["metadata"]["schema_version"] == "1.0"


def test_parse_document_rejects_unknown_parser(tmp_path) -> None:
    request = ParseRequest(tmp_path / "input.pdf", tmp_path / "canonical.json")

    with pytest.raises(ParserNotFoundError):
        parse_document(request, "not-installed")


def test_registry_discovers_installed_parser_entry_points(monkeypatch) -> None:
    registry._PARSERS.pop("discovered", None)
    registry._LOADED_ENTRY_POINTS.clear()
    monkeypatch.setattr(registry, "_parser_entry_points", lambda: [_FakeEntryPoint()])

    parser = registry.get_parser("discovered")

    assert parser.name == "discovered"
