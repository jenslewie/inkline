from __future__ import annotations

from html import escape

from inkline.epub.figure.layout import format_percent
from inkline.epub.figure.model import Caption, FigureView, ImageRef
from inkline.epub.markup import indent_lines


def render_figure_html(figure: FigureView) -> str:
    figure_html = (
        render_side_caption_figure_html(figure)
        if figure.side_layout
        else render_stacked_figure_html(figure)
    )
    if figure.page_break_before:
        return '<div class="figure-page-break" aria-hidden="true"></div>\n' + figure_html
    return figure_html


def render_caption_html(caption: Caption) -> str:
    parts = [f'<p class="caption-title">{escape(caption.title)}</p>']
    parts.extend(f'<p class="caption-body">{escape(line)}</p>' for line in caption.body)
    return "\n".join(["<figcaption>", *indent_lines(parts, "  "), "</figcaption>"])


def render_image_html(image: ImageRef) -> str:
    if image.kind == "placeholder" or not image.src:
        return '<div role="img" aria-label="Image">[Image]</div>'
    style = ""
    if image.max_width_percent is not None:
        style = f' style="max-width: {format_percent(image.max_width_percent)}%;"'
    return (
        f'<img src="images/{escape(image.src, quote=True)}" '
        f'alt="{escape(image.alt, quote=True)}"{style}/>'
    )


def render_stacked_figure_html(figure: FigureView) -> str:
    class_attr = _figure_class_attr(figure)
    parts = [f"<figure{class_attr}>", *indent_lines([render_image_html(figure.image)], "  ")]
    if figure.caption:
        parts.extend(indent_lines(render_caption_html(figure.caption).splitlines(), "  "))
    parts.append("</figure>")
    return "\n".join(parts)


def render_side_caption_figure_html(figure: FigureView) -> str:
    if figure.side_layout is None or figure.caption is None:
        return render_stacked_figure_html(figure)
    image_part = "\n".join(
        [
            '<div class="figure-side-image" '
            f'style="flex-basis: {format_percent(figure.side_layout.image_percent)}%;">',
            *indent_lines([render_image_html(figure.image)], "  "),
            "</div>",
        ]
    )
    caption_html = render_caption_html(figure.caption).replace(
        "<figcaption>",
        f'<figcaption style="flex-basis: {format_percent(figure.side_layout.caption_percent)}%;">',
        1,
    )
    content_parts = (
        [caption_html, image_part]
        if figure.side_layout.side == "left"
        else [image_part, caption_html]
    )
    content_lines: list[str] = []
    for part in content_parts:
        content_lines.extend(indent_lines(part.splitlines(), "  "))
    return "\n".join([f"<figure{_figure_class_attr(figure)}>", *content_lines, "</figure>"])


def render_standalone_caption_html(text: str) -> str:
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) <= 1:
        return f'<p class="caption">{escape(text)}</p>'
    parts: list[str] = [f'<p class="caption-title">{escape(lines[0])}</p>']
    parts.extend(f'<p class="caption-body">{escape(line)}</p>' for line in lines[1:])
    return "\n".join(['<div class="caption">', *indent_lines(parts, "  "), "</div>"])


def render_legacy_figcaption_html(text: str) -> str:
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) <= 1:
        return f"<figcaption>{escape(text)}</figcaption>"
    parts: list[str] = [f'<p class="caption-title">{escape(lines[0])}</p>']
    parts.extend(f'<p class="caption-body">{escape(line)}</p>' for line in lines[1:])
    return "\n".join(["<figcaption>", *indent_lines(parts, "  "), "</figcaption>"])


def render_caption_block_html(text: str, *, follows_figure: bool) -> str:
    if follows_figure:
        return render_legacy_figcaption_html(text)
    return render_standalone_caption_html(text)


def _figure_class_attr(figure: FigureView) -> str:
    return ' class="' + " ".join(figure.classes) + '"'
