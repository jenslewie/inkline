from __future__ import annotations

from html import escape

from inkline.epub.markup import indent_lines
from inkline.epub.text.model import (
    DisplayBlockView,
    FootnoteView,
    HeadingView,
    InlineText,
    ListView,
    NoteRef,
    TextSegment,
)


def render_inline_text(text: InlineText) -> str:
    parts: list[str] = []
    for part in text.parts:
        if isinstance(part, TextSegment):
            parts.append(escape(part.text))
            continue
        if isinstance(part, NoteRef):
            if part.target:
                parts.append(
                    f'<a epub:type="noteref" href="#{escape(str(part.target), quote=True)}" '
                    f'id="{escape(part.ref_id, quote=True)}"><sup>{escape(part.marker)}</sup></a>'
                )
            else:
                parts.append(f"<sup>{escape(part.marker)}</sup>")
    return "".join(parts)


def render_display_block_html(display: DisplayBlockView) -> str:
    class_attr = " ".join(display.classes)
    if not display.paragraphs:
        return f'<blockquote class="{escape(class_attr, quote=True)}"></blockquote>'
    paragraphs = [
        f'<div class="display-block-paragraph">{render_inline_text(paragraph)}</div>'
        for paragraph in display.paragraphs
    ]
    return "\n".join(
        [
            f'<blockquote class="{escape(class_attr, quote=True)}">',
            *indent_lines(paragraphs, "  "),
            "</blockquote>",
        ]
    )


def render_heading_html(heading: HeadingView) -> str:
    heading_text = escape(heading.text).replace("\n", "<br/>\n")
    return f"<h{heading.level}>{heading_text}</h{heading.level}>"


def render_chapter_title_page_html(heading: HeadingView) -> str:
    heading_html = render_heading_html(heading)
    return f'<div class="chapter-title-page">\n  {heading_html}\n</div>'


def render_list_html(list_view: ListView) -> str:
    items = [f"<li>{render_inline_text(item)}</li>" for item in list_view.items]
    return "<ul>" + "".join(items) + "</ul>"


def render_footnote_html(footnote: FootnoteView) -> str:
    id_attr = f' id="{escape(footnote.note_id, quote=True)}"' if footnote.note_id else ""
    return "\n".join(
        [
            f'<aside epub:type="footnote"{id_attr}>',
            f"  <p>{escape(footnote.text)}</p>",
            "</aside>",
        ]
    )
