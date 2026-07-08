from __future__ import annotations

from pathlib import Path


def test_canonical_top_level_modules_stay_grouped() -> None:
    canonical_dir = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "inkline-canonical"
        / "src"
        / "inkline"
        / "canonical"
    )
    modules = sorted(
        path.name
        for path in canonical_dir.glob("*.py")
        if path.name != "__init__.py"
    )

    assert len(modules) <= 10, (
        "inkline.canonical has too many top-level modules; "
        f"consider grouping related files into subpackages: {modules}"
    )
