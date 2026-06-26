#!/usr/bin/env python3
"""Check display_block architecture invariants.

This checker is intentionally narrow: it guards the geometry-first
display_block pipeline from drifting back to text-triggered or propagation-based
classification rules.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPLAY_BLOCK_RECONCILE_DIR = (
    REPO_ROOT / "packages/inkline-parser-mineru/src/inkline/parsers/mineru/reconcile/display_block"
)

DISPLAY_ARCH_EXTRA_FILES = (
    "packages/inkline-parser-mineru/src/inkline/parsers/mineru/normalize/builders.py",
    "packages/inkline-parser-mineru/src/inkline/parsers/mineru/normalize/display_geometry.py",
    "packages/inkline-parser-mineru/src/inkline/parsers/mineru/normalize/normal_flow.py",
    "packages/inkline-parser-mineru/src/inkline/parsers/mineru/normalize/page_handlers.py",
    "packages/inkline-parser-mineru/src/inkline/parsers/mineru/normalize/raw_display_blocks.py",
    "packages/inkline-parser-mineru/src/inkline/parsers/mineru/reconcile/cross_page.py",
    "packages/inkline-parser-mineru/src/inkline/parsers/mineru/reconcile/layout_helpers.py",
)

TEXT_GATE_METHODS = {"endswith", "startswith"}
TEXT_GATE_HELPERS = {
    "_ends_with_terminal",
    "_ends_with_terminal_punctuation",
    "ends_with_terminal_punctuation",
    "has_attribution_line",
}
TEXT_GATE_REGEXES = {"ATTR_RE"}
TEXT_GATE_ALLOWLIST: dict[str, set[str]] = {
    "packages/inkline-parser-mineru/src/inkline/parsers/mineru/reconcile/cross_page.py": {
        "merge_cross_page_paragraphs",
    },
}
UNSCALED_LAYOUT_ATTRS = {
    "body_left",
    "body_right",
    "body_width",
    "page_width",
    "page_height",
}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: Path
    line: int
    detail: str

    def format(self, root: Path = REPO_ROOT) -> str:
        try:
            display_path = self.path.relative_to(root)
        except ValueError:
            display_path = self.path
        return f"{self.rule} {display_path}:{self.line}: {self.detail}"


class _ArchitectureVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, source: str, *, canonical_reconcile: bool) -> None:
        self.path = path
        self.source = source
        self.canonical_reconcile = canonical_reconcile
        self.findings: list[Finding] = []
        self._function_stack: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "previous_display":
                self.findings.append(
                    Finding(
                        "display-no-previous-display-promotion",
                        self.path,
                        node.lineno,
                        "`previous_display` can propagate display_block classification without a fresh geometry group.",
                    )
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in TEXT_GATE_METHODS
            and not _is_private_key_filter(node)
        ):
            self.findings.append(
                Finding(
                    "display-no-text-punctuation-gates",
                    self.path,
                    node.lineno,
                    f"`.{node.func.attr}()` is a text-content gate; display_block classification must be geometry-first.",
                )
            )
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in TEXT_GATE_HELPERS
            and not self._is_allowed_text_gate()
        ):
            self.findings.append(
                Finding(
                    "display-no-text-punctuation-helper-gates",
                    self.path,
                    node.lineno,
                    f"`{node.func.id}()` is a text-content gate; display_block classification must be geometry-first.",
                )
            )
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "match"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in TEXT_GATE_REGEXES
        ):
            self.findings.append(
                Finding(
                    "display-no-text-regex-gates",
                    self.path,
                    node.lineno,
                    f"`{node.func.value.id}.match()` is a text-form gate; display_block classification must be geometry-first.",
                )
            )
        self.generic_visit(node)

    def _is_allowed_text_gate(self) -> bool:
        try:
            rel = self.path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return False
        allowed_functions = TEXT_GATE_ALLOWLIST.get(rel, set())
        return bool(self._function_stack and self._function_stack[-1] in allowed_functions)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            self.canonical_reconcile
            and isinstance(node.value, ast.Name)
            and node.value.id == "layout"
            and node.attr in UNSCALED_LAYOUT_ATTRS
            and not _is_dict_get_default(node)
        ):
            self.findings.append(
                Finding(
                    "display-no-unscaled-layout-metrics",
                    self.path,
                    node.lineno,
                    f"`layout.{node.attr}` is used in canonical reconcile code; use scaled page/body metrics.",
                )
            )
        self.generic_visit(node)


def _is_dict_get_default(node: ast.AST) -> bool:
    parent = getattr(node, "_parent", None)
    if not isinstance(parent, ast.Call):
        return False
    if not isinstance(parent.func, ast.Attribute) or parent.func.attr != "get":
        return False
    return len(parent.args) >= 2 and parent.args[1] is node


def _is_private_key_filter(node: ast.Call) -> bool:
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "startswith"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"k", "key"}
    ):
        return False
    return bool(node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "_")


def _attach_parents(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent  # type: ignore[attr-defined]


def check_file(path: Path, *, canonical_reconcile: bool) -> list[Finding]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    _attach_parents(tree)
    visitor = _ArchitectureVisitor(path, source, canonical_reconcile=canonical_reconcile)
    visitor.visit(tree)
    return visitor.findings


def check_paths(paths: Iterable[Path], root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        resolved = path.resolve()
        findings.extend(
            check_file(resolved, canonical_reconcile=_is_display_reconcile_path(resolved))
        )
    return sorted(findings, key=lambda item: (str(item.path), item.line, item.rule))


def _is_display_reconcile_path(path: Path) -> bool:
    try:
        path.relative_to(DISPLAY_BLOCK_RECONCILE_DIR)
    except ValueError:
        return False
    return True


def default_paths(root: Path = REPO_ROOT) -> list[Path]:
    display_reconcile_paths = sorted(
        path for path in DISPLAY_BLOCK_RECONCILE_DIR.glob("*.py") if path.name != "__init__.py"
    )
    extra_paths = [root / rel for rel in DISPLAY_ARCH_EXTRA_FILES]
    return [*extra_paths, *display_reconcile_paths]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Optional files to check. Defaults to display_block architecture files.",
    )
    args = parser.parse_args(argv)

    paths = args.paths or default_paths()
    findings = check_paths(paths)
    for finding in findings:
        print(finding.format())
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
