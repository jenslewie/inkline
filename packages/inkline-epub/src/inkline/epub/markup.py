from __future__ import annotations


def indent_lines(lines: list[str], prefix: str) -> list[str]:
    return [prefix + line if line.strip() else line for line in lines]
