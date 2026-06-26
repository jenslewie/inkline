from __future__ import annotations

import ast
from pathlib import Path

RENDER_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "inkline-epub"
    / "src"
    / "inkline"
    / "epub"
    / "renderer.py"
)


def _module_tree() -> ast.Module:
    return ast.parse(RENDER_PATH.read_text())


def _top_level_names(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.ClassDef)}


def test_chapter_documents_delegates_render_flow_to_small_helpers() -> None:
    tree = _module_tree()
    names = _top_level_names(tree)

    assert {
        "_RenderContext",
        "_RenderState",
        "_block_page",
        "_is_printed_toc_block",
        "_should_split_chapter",
        "_render_visual_page_block",
        "_render_flow_block",
    } <= names

    chapter_documents = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "chapter_documents"
    )
    assert not any(isinstance(node, ast.Continue) for node in ast.walk(chapter_documents))
    assert sum(isinstance(node, ast.If) for node in ast.walk(chapter_documents)) <= 4
