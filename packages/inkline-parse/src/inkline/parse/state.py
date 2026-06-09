from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def write_run_state(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Persist parser task state in a backend-neutral JSON format."""

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
