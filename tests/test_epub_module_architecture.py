from __future__ import annotations

import ast
from pathlib import Path

EPUB_DIR = (
    Path(__file__).resolve().parents[1] / "packages" / "inkline-epub" / "src" / "inkline" / "epub"
)


def _tree(path: str | Path) -> ast.Module:
    return ast.parse((EPUB_DIR / path).read_text())


def _top_level_names(path: str | Path) -> set[str]:
    tree = _tree(path)
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.ClassDef)}


def _function(name: str, function_name: str) -> ast.FunctionDef:
    return next(
        node
        for node in _tree(name).body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )


def _called_function_names(function: ast.FunctionDef) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def _imported_modules(path: str | Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_root_has_no_legacy_private_modules() -> None:
    legacy_modules = {
        "_assets.py",
        "_chapter.py",
        "_figures.py",
        "_html.py",
        "_nav.py",
        "_opf.py",
        "_render.py",
        "_style.py",
        "_tables.py",
        "_text.py",
    }
    for module_name in legacy_modules:
        assert not (EPUB_DIR / module_name).exists(), module_name

    assert (EPUB_DIR / "assets" / "resolver.py").exists()
    assert (EPUB_DIR / "chapter" / "model.py").exists()
    assert (EPUB_DIR / "markup.py").exists()
    assert (EPUB_DIR / "renderer.py").exists()
    assert (EPUB_DIR / "theme" / "style.py").exists()


def test_table_rendering_uses_table_view_boundary() -> None:
    assert (EPUB_DIR / "table" / "__init__.py").exists()
    assert (EPUB_DIR / "table" / "model.py").exists()
    assert (EPUB_DIR / "table" / "resolver.py").exists()
    assert (EPUB_DIR / "table" / "html.py").exists()
    assert not (EPUB_DIR / "_table_model.py").exists()
    assert not (EPUB_DIR / "_table_resolver.py").exists()
    assert not (EPUB_DIR / "_table_html.py").exists()

    assert {"TableView"} <= _top_level_names(Path("table") / "model.py")
    assert {"resolve_table_view"} <= _top_level_names(Path("table") / "resolver.py")
    assert {"render_table_html"} <= _top_level_names(Path("table") / "html.py")


def test_inline_text_rendering_uses_text_view_boundary() -> None:
    assert (EPUB_DIR / "text" / "__init__.py").exists()
    assert (EPUB_DIR / "text" / "model.py").exists()
    assert (EPUB_DIR / "text" / "resolver.py").exists()
    assert (EPUB_DIR / "text" / "html.py").exists()
    assert not (EPUB_DIR / "_text_model.py").exists()
    assert not (EPUB_DIR / "_text_resolver.py").exists()
    assert not (EPUB_DIR / "_text_html.py").exists()

    assert {
        "DisplayBlockView",
        "FootnoteView",
        "HeadingView",
        "InlineText",
        "ListView",
        "NoteRef",
        "TextSegment",
    } <= _top_level_names(Path("text") / "model.py")
    assert {
        "resolve_display_block_view",
        "resolve_footnote_view",
        "resolve_heading_view",
        "resolve_inline_text",
        "resolve_list_view",
    } <= _top_level_names(Path("text") / "resolver.py")
    assert {
        "render_display_block_html",
        "render_chapter_title_page_html",
        "render_footnote_html",
        "render_heading_html",
        "render_inline_text",
        "render_list_html",
    } <= _top_level_names(Path("text") / "html.py")


def test_nav_rendering_uses_nav_view_boundary() -> None:
    assert (EPUB_DIR / "navigation" / "__init__.py").exists()
    assert (EPUB_DIR / "navigation" / "model.py").exists()
    assert (EPUB_DIR / "navigation" / "resolver.py").exists()
    assert (EPUB_DIR / "navigation" / "html.py").exists()
    assert not (EPUB_DIR / "_nav_model.py").exists()
    assert not (EPUB_DIR / "_nav_resolver.py").exists()
    assert not (EPUB_DIR / "_nav_html.py").exists()

    assert {"NavItem", "NavView"} <= _top_level_names(Path("navigation") / "model.py")
    assert {"resolve_nav_view"} <= _top_level_names(Path("navigation") / "resolver.py")
    assert {"render_nav_xhtml"} <= _top_level_names(Path("navigation") / "html.py")
    assert {"toc_heading_block_ids"} <= _top_level_names(Path("navigation") / "resolver.py")


def test_opf_rendering_uses_package_view_boundary() -> None:
    assert (EPUB_DIR / "package" / "__init__.py").exists()
    assert (EPUB_DIR / "package" / "model.py").exists()
    assert (EPUB_DIR / "package" / "resolver.py").exists()
    assert (EPUB_DIR / "package" / "xml.py").exists()
    assert not (EPUB_DIR / "_opf_model.py").exists()
    assert not (EPUB_DIR / "_opf_resolver.py").exists()
    assert not (EPUB_DIR / "_opf_xml.py").exists()

    assert {"ManifestItem", "PackageView"} <= _top_level_names(Path("package") / "model.py")
    assert {"resolve_package_view"} <= _top_level_names(Path("package") / "resolver.py")
    assert {"container_xml", "render_opf_xml", "wrap_chapter"} <= _top_level_names(
        Path("package") / "xml.py"
    )


def test_render_uses_figure_package_boundary() -> None:
    imported_modules = _imported_modules("renderer.py")
    assert not any(module.startswith("inkline.epub._") for module in imported_modules)
    assert {
        "inkline.epub.figure.html",
        "inkline.epub.figure.resolver",
        "inkline.epub.figure.visual_pages",
        "inkline.epub.figure.layout",
        "inkline.epub.table.html",
        "inkline.epub.table.resolver",
        "inkline.epub.text.html",
        "inkline.epub.text.resolver",
    } <= imported_modules
    assert "html" not in imported_modules
    assert "inkline.canonical" not in imported_modules
