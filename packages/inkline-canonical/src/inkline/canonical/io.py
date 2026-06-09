from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Any

from inkline.canonical.schema import migrate_document, validate_document


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def read_canonical(path: str | Path) -> dict[str, Any]:
    document = migrate_document(read_json(path))
    validate_document(document)
    return document


def write_canonical(path: str | Path, document: Mapping[str, Any]) -> None:
    payload = dict(document)
    validate_document(payload)
    write_json(path, payload)


def read_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield json.loads(stripped)


def write_jsonl(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> int:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
            count += 1
    return count
