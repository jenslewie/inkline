import re
import zipfile

from inkline.canonical import sample_document
from inkline.epub import export_epub


def test_export_epub_writes_standard_container(tmp_path):
    output = tmp_path / "book.epub"

    export_epub(sample_document(), output)

    assert output.stat().st_size > 0
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        assert "mimetype" in names
        assert "META-INF/container.xml" in names
        assert "EPUB/content.opf" in names
        assert "EPUB/nav.xhtml" in names
        assert any(name.startswith("EPUB/chapter_") and name.endswith(".xhtml") for name in names)


def test_export_epub_renders_figure_placeholder(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "figure",
            "text": "",
            "source": {"page": 3, "bbox": [1, 2, 3, 4]},
            "attrs": {"parser_raw_id": "#/pictures/0"},
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert "Image placeholder" in html
    assert "page 3" in html
    assert "#/pictures/0" in html


def test_export_epub_renders_inline_note_refs(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "paragraph",
            "text": "前文。后文。",
            "source": {"page": 1, "bbox": None},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "前文。"},
                    {"type": "note_ref", "marker": "1", "target_note_id": "note_b000002"},
                    {"type": "text", "text": "后文。"},
                ]
            },
        },
        {
            "block_id": "b000002",
            "type": "footnote",
            "text": "1 注释。",
            "source": {"page": 1, "bbox": None},
            "attrs": {"note_id": "note_b000002"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert 'epub:type="noteref"' in html
    assert 'href="#note_b000002"' in html
    assert '<aside epub:type="footnote" id="note_b000002">' in html


def test_export_epub_renders_display_blocks_and_list_items(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "display_block",
            "text": "第一行\n第二行",
            "source": {"page": 1, "bbox": None},
            "attrs": {
                "layout_role": "standalone_display_page",
                "inline_runs": [
                    {"type": "text", "text": "第一行\n第二行"},
                    {"type": "note_ref", "marker": "1", "target_note_id": "note_b000004"},
                ],
            },
        },
        {
            "block_id": "b000002",
            "type": "display_block",
            "text": "右对齐",
            "source": {"page": 1, "bbox": None},
            "attrs": {"layout_role": "flush_right_terminal_block"},
        },
        {
            "block_id": "b000003",
            "type": "list_item",
            "text": "列表一",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
        },
        {
            "block_id": "b000004",
            "type": "list_item",
            "text": "列表二",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
        css = zf.read("EPUB/styles/book.css").decode("utf-8")
    assert 'class="display-block display-block-standalone"' in html
    assert 'class="display-block display-block-right"' in html
    assert 'epub:type="noteref"' in html
    assert html.count("<ul>") == 1
    assert "<li>列表一</li><li>列表二</li>" in html
    assert ".epigraph" not in css
    assert ".blockquote" not in css
    assert ".signature" not in css


def test_export_epub_marks_cover_asset(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
        b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    document = sample_document()
    document["assets"]["images"] = [
        {
            "image_id": "page-0001-snapshot",
            "path": str(cover),
            "media_type": "image/png",
            "role": "cover",
            "source": {"page": 1},
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        opf = zf.read("EPUB/content.opf").decode("utf-8")
        names = set(zf.namelist())
    assert 'properties="cover-image"' in opf
    assert '<meta name="cover" content="page-0001-snapshot"/>' in opf
    assert "EPUB/images/page-0001-snapshot_cover.png" in names


def test_export_epub_renders_table_from_attrs_html(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "table",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {
                "html": '<table><tr><td colspan="2">Title</td></tr><tr><td>A</td><td>B</td></tr></table>'
            },
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert 'colspan="2"' in html
    assert "<td>A</td>" in html
    assert "<td>B</td>" in html


def test_export_epub_sanitizes_attrs_html_with_unescaped_ampersand(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "table",
            "text": "A & B | C",
            "source": {"page": 1, "bbox": None},
            "attrs": {"html": "<table><tr><td>A & B</td></tr></table>"},
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = [n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n]
        for name in chapter_names:
            from xml.etree import ElementTree as ET

            content = zf.read(name).decode("utf-8")
            ET.fromstring(content)
        html = "\n".join(zf.read(name).decode("utf-8") for name in chapter_names)
    assert "A &amp; B" in html


def test_export_epub_renders_table_from_markdown_text(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "table",
            "text": "| Name | Value |\n| --- | --- |\n| A | 1 |\n| B | 2 |",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert "<td>Name</td>" in html
    assert "<td>A</td>" in html
    assert "<td>1</td>" in html


def test_export_epub_caption_merged_into_figure(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "figure",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {"parser_raw_id": "#/pictures/0"},
        },
        {
            "block_id": "b000002",
            "type": "caption",
            "text": "图例说明",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert "图例说明" in html
    figcaption_positions = [m.start() for m in re.finditer(r"<figcaption>", html)]
    figure_starts = [m.start() for m in re.finditer(r"<figure", html)]
    figure_ends = [m.start() for m in re.finditer(r"</figure>", html)]
    for cap_pos in figcaption_positions:
        inside = any(fs < cap_pos < fe for fs, fe in zip(figure_starts, figure_ends, strict=True))
        assert inside, f"<figcaption> at {cap_pos} is outside <figure>"


def test_export_epub_orphan_caption_renders_as_paragraph(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "heading",
            "text": "地图",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b000002",
            "type": "caption",
            "text": "印度洋",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert '<p class="caption">印度洋</p>' in html
    assert "<figcaption>" not in html


def test_export_epub_dynamic_modified_timestamp(tmp_path):
    document = sample_document()
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        opf = zf.read("EPUB/content.opf").decode("utf-8")
    match = re.search(r'<meta property="dcterms:modified">([^<]+)</meta>', opf)
    assert match is not None
    assert match.group(1) != "2026-06-03T00:00:00Z"


def test_export_epub_toc_with_page_labels(tmp_path):
    document = sample_document()
    document["toc"] = [
        {"title": "第一章", "level": 1, "target_page_label": "1", "source_block_id": "b000001"},
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode("utf-8")
    assert "第一章 (1)" in nav


def test_export_epub_toc_page_label_by_title_match(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "序言",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "内容",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
        },
        {
            "block_id": "b_h2",
            "type": "heading",
            "text": "第一章",
            "source": {"page": 5, "bbox": None},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p2",
            "type": "paragraph",
            "text": "正文",
            "source": {"page": 5, "bbox": None},
            "attrs": {},
        },
    ]
    document["toc"] = [
        {"title": "序言", "level": 1, "target_page_label": "1", "source_block_id": "b_h1"},
        {"title": "第一章", "level": 1, "target_page_label": "5", "source_block_id": "b_h2"},
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode("utf-8")
    assert "序言 (1)" in nav
    assert "第一章 (5)" in nav


def test_export_epub_toc_no_mismatch_when_extra_toc_entry(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "第一章",
            "source": {"page": 5, "bbox": None},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "正文",
            "source": {"page": 5, "bbox": None},
            "attrs": {},
        },
    ]
    document["toc"] = [
        {"title": "封面", "level": 1, "target_page_label": "1", "source_block_id": "b_cover"},
        {"title": "第一章", "level": 1, "target_page_label": "5", "source_block_id": "b_h1"},
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode("utf-8")
    assert "第一章 (5)" in nav
    assert "封面" not in nav


def test_export_epub_empty_table_and_continuation_skipped(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "table",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {"html": "<table><tr><td>A</td></tr></table>"},
        },
        {
            "block_id": "b000002",
            "type": "table_continuation",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {"html_empty": True},
        },
        {
            "block_id": "b000003",
            "type": "table_continuation",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert "<td>A</td>" in html
    assert html.count("<table>") == 1


def test_export_epub_figure_with_inline_image_path(tmp_path):
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    img_file = img_dir / "test.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "figure",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {"image_path": "images/test.jpg"},
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
        names = set(zf.namelist())
    assert '<img src="images/b000001_test.jpg"' in html
    assert "EPUB/images/b000001_test.jpg" in names


def test_export_epub_toc_duplicate_titles_no_cross_contamination(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Intro",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "Part one",
            "source": {"page": 1, "bbox": None},
            "attrs": {},
        },
        {
            "block_id": "b_h2",
            "type": "heading",
            "text": "Intro",
            "source": {"page": 9, "bbox": None},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p2",
            "type": "paragraph",
            "text": "Part two",
            "source": {"page": 9, "bbox": None},
            "attrs": {},
        },
    ]
    document["toc"] = [
        {"title": "Intro", "level": 1, "target_page_label": "1", "source_block_id": "b_h1"},
        {"title": "Intro", "level": 1, "target_page_label": "9", "source_block_id": "b_h2"},
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode("utf-8")
    items = re.findall(r'<li><a href="[^"]+">([^<]+)</a></li>', nav)
    assert len(items) == 2
    assert items[0] == "Intro (1)"
    assert items[1] == "Intro (9)"


def test_export_epub_figure_with_broken_image_id_falls_back_to_image_path(tmp_path):
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    img_file = img_dir / "fallback.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "figure",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {"image_id": "missing_asset", "image_path": "images/fallback.jpg"},
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
        names = set(zf.namelist())
    assert '<img src="images/b000001_fallback.jpg"' in html
    assert "EPUB/images/b000001_fallback.jpg" in names


def test_export_epub_figure_with_missing_asset_file_falls_back_to_image_path(tmp_path):
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    img_file = img_dir / "fallback.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    document = sample_document()
    document["assets"]["images"] = [
        {
            "image_id": "missing_file",
            "path": str(tmp_path / "nonexistent.jpg"),
            "media_type": "image/jpeg",
        }
    ]
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "figure",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {"image_id": "missing_file", "image_path": "images/fallback.jpg"},
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
        names = set(zf.namelist())
    assert '<img src="images/b000001_fallback.jpg"' in html
    assert "EPUB/images/b000001_fallback.jpg" in names
    assert "EPUB/images/missing_file_nonexistent.jpg" not in names


def test_export_epub_sanitizes_attrs_html_with_nbsp_entity(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "table",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {"html": "<table><tr><td>A&nbsp;B</td></tr></table>"},
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = [n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n]
        from xml.etree import ElementTree as ET

        for name in chapter_names:
            content = zf.read(name).decode("utf-8")
            ET.fromstring(content)
        html = "\n".join(zf.read(name).decode("utf-8") for name in chapter_names)
    assert "<table>" in html
    assert "\u00a0" in html or "&#160;" in html
