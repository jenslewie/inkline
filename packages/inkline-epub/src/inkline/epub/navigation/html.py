from __future__ import annotations

from html import escape

from inkline.epub.navigation.model import NavView


def render_nav_xhtml(nav: NavView) -> str:
    items = "\n".join(
        f'    <li><a href="{escape(item.href, quote=True)}">{escape(item.label)}</a></li>'
        for item in nav.items
    )
    lang = escape(nav.language, quote=True)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">
<head>
  <title>Contents</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Contents</h1>
    <ol>
{items}
    </ol>
  </nav>
</body>
</html>
"""
