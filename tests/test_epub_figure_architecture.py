from __future__ import annotations

import ast
from pathlib import Path

EPUB_DIR = (
    Path(__file__).resolve().parents[1] / "packages" / "inkline-epub" / "src" / "inkline" / "epub"
)


def _tree(path: str | Path) -> ast.Module:
    return ast.parse((EPUB_DIR / path).read_text())


def _top_level_names(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.ClassDef)}


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_figure_rendering_uses_view_model_boundary() -> None:
    assert (EPUB_DIR / "figure" / "__init__.py").exists()
    assert (EPUB_DIR / "figure" / "model.py").exists()
    assert (EPUB_DIR / "figure" / "resolver.py").exists()
    assert (EPUB_DIR / "figure" / "html.py").exists()
    assert not (EPUB_DIR / "_figure_model.py").exists()
    assert not (EPUB_DIR / "_figure_resolver.py").exists()
    assert not (EPUB_DIR / "_figure_html.py").exists()

    model_names = _top_level_names(_tree(Path("figure") / "model.py"))
    assert {"ImageRef", "Caption", "SideCaptionLayout", "FigureView"} <= model_names

    resolver_names = _top_level_names(_tree(Path("figure") / "resolver.py"))
    assert {"resolve_figure_view", "normalize_figure_caption"} <= resolver_names

    html_tree = _tree(Path("figure") / "html.py")
    html_names = _top_level_names(html_tree)
    assert {
        "render_caption_block_html",
        "render_figure_html",
        "render_caption_html",
        "render_image_html",
    } <= html_names

    renderer = _function(html_tree, "render_figure_html")
    assert [arg.arg for arg in renderer.args.args] == ["figure"]
    assert not any(
        isinstance(node, ast.Attribute) and node.attr in {"get", "exists"}
        for node in ast.walk(renderer)
    )

    render_tree = _tree("renderer.py")
    render_imports = {
        node.name
        for node in ast.walk(render_tree)
        if isinstance(node, ast.alias)
        and node.name in {"render_legacy_figcaption_html", "render_standalone_caption_html"}
    }
    assert not render_imports
