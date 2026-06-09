"""Optional call tracing for note reconciliation internals."""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any, Dict, Iterator, Optional


@contextmanager
def trace_note_calls(path: str | Path | None) -> Iterator[None]:
    """Count calls to functions/methods under ``reconcile.notes``.

    The trace is intentionally summary-only: it avoids a huge per-call log while
    still making it clear which fallback helpers were actually exercised.
    """

    if not path:
        yield
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    notes_dir = Path(__file__).resolve().parent
    notes_prefix = f"{notes_dir}{os.sep}"
    counts: Dict[str, Dict[str, Any]] = {}
    started = _now_iso()
    timer = time.perf_counter()
    previous_profile = sys.getprofile()

    def profiler(frame: FrameType, event: str, _arg: Any) -> Optional[Any]:
        if event != "call":
            return profiler
        filename_text = frame.f_code.co_filename
        if not filename_text.startswith(notes_prefix):
            return profiler
        filename = Path(filename_text)
        try:
            relative = filename.relative_to(notes_dir)
        except ValueError:
            return profiler
        qualname = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
        key = f"{relative.as_posix()}::{qualname}"
        item = counts.setdefault(
            key,
            {
                "file": relative.as_posix(),
                "qualname": qualname,
                "line": frame.f_code.co_firstlineno,
                "calls": 0,
            },
        )
        item["calls"] += 1
        return profiler

    sys.setprofile(profiler)
    try:
        yield
    finally:
        sys.setprofile(previous_profile)
        definitions = _collect_note_definitions(notes_dir)
        called_keys = set(counts)
        uncalled = [item for key, item in sorted(definitions.items()) if key not in called_keys]
        payload = {
            "schema": "mineru_note_call_trace.v1",
            "started_at": started,
            "finished_at": _now_iso(),
            "duration_seconds": round(time.perf_counter() - timer, 6),
            "notes_dir": str(notes_dir),
            "called_count": len(called_keys),
            "defined_count": len(definitions),
            "uncalled_count": len(uncalled),
            "called": sorted(counts.values(), key=lambda item: (-int(item["calls"]), str(item["file"]), str(item["qualname"]))),
            "uncalled": uncalled,
        }
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _collect_note_definitions(notes_dir: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted(notes_dir.glob("*.py")):
        if path.name == "trace.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        relative = path.relative_to(notes_dir).as_posix()
        _collect_defs_from_body(tree.body, relative, [], out)
    return out


def _collect_defs_from_body(nodes: list[ast.stmt], relative: str, parents: list[str], out: Dict[str, Dict[str, Any]]) -> None:
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            _collect_defs_from_body(node.body, relative, [*parents, node.name], out)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = ".".join([*parents, node.name])
            key = f"{relative}::{qualname}"
            out[key] = {
                "file": relative,
                "qualname": qualname,
                "line": node.lineno,
            }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
