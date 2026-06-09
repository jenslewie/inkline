from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points
from typing import Iterable

from inkline.canonical import validate_document

from .types import DocumentParser, ParseRequest, ParseResult

PARSER_ENTRY_POINT_GROUP = "inkline.parsers"


class ParserNotFoundError(LookupError):
    pass


_PARSERS: dict[str, DocumentParser] = {}
_LOADED_ENTRY_POINTS: set[str] = set()


def _parser_entry_points() -> Iterable[EntryPoint]:
    discovered = entry_points()
    if hasattr(discovered, "select"):
        return discovered.select(group=PARSER_ENTRY_POINT_GROUP)
    return discovered.get(PARSER_ENTRY_POINT_GROUP, ())  # type: ignore[union-attr]


def discover_parsers() -> None:
    """Load parser adapters advertised through the ``inkline.parsers`` group."""

    for entry_point in _parser_entry_points():
        key = f"{entry_point.name}={entry_point.value}"
        if key in _LOADED_ENTRY_POINTS:
            continue
        target = entry_point.load()
        parser = target() if isinstance(target, type) else target
        if not isinstance(parser, DocumentParser):
            raise TypeError(
                f"Parser entry point {entry_point.name!r} did not provide a DocumentParser"
            )
        if parser.name.strip().lower() != entry_point.name.strip().lower():
            raise ValueError(
                f"Parser entry point {entry_point.name!r} returned parser {parser.name!r}"
            )
        register_parser(parser, replace=True)
        _LOADED_ENTRY_POINTS.add(key)


def register_parser(parser: DocumentParser, *, replace: bool = False) -> None:
    name = parser.name.strip().lower()
    if not name:
        raise ValueError("parser.name must not be empty")
    if name in _PARSERS and not replace:
        raise ValueError(f"Parser already registered: {name}")
    _PARSERS[name] = parser


def available_parsers() -> tuple[str, ...]:
    discover_parsers()
    return tuple(sorted(_PARSERS))


def get_parser(name: str) -> DocumentParser:
    discover_parsers()
    try:
        return _PARSERS[name.strip().lower()]
    except KeyError:
        available = ", ".join(available_parsers()) or "none"
        raise ParserNotFoundError(f"Unknown parser {name!r}; available parsers: {available}") from None


def parse_document(request: ParseRequest, parser: str | DocumentParser) -> ParseResult:
    selected = get_parser(parser) if isinstance(parser, str) else parser
    result = selected.parse(request)
    validate_document(result.document)
    return result
