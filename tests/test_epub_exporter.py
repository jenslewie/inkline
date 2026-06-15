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
    """Figure blocks without image assets produce a clean placeholder
    without debug metadata (page, bbox, parser_raw_id)."""
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
    # Placeholder should be present but WITHOUT debug metadata
    assert "[Image]" in html
    assert "Image placeholder" not in html
    assert "page 3" not in html
    assert "bbox" not in html
    assert "#/pictures/0" not in html


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
    assert 'class="display-block display-block-signature"' in html
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
    assert "第一章" in nav
    assert "(1)" not in nav


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
    assert "序言" in nav
    assert "第一章" in nav
    assert "(1)" not in nav
    assert "(5)" not in nav


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
    assert "第一章" in nav
    assert "(5)" not in nav
    # "封面" has no matching heading but still appears in nav (linked to fallback chapter)
    assert "封面" in nav


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
    assert items[0] == "Intro"
    assert items[1] == "Intro"


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


def test_export_epub_sanitizes_attrs_html_with_para_entity(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000001",
            "type": "table",
            "text": "",
            "source": {"page": 1, "bbox": None},
            "attrs": {"html": "<table><tr><td>A&para;B</td></tr></table>"},
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
    assert "\u00b6" in html or "&#182;" in html
    assert "\u00a6" not in html


def test_visual_page_snapshot_only(tmp_path):
    """A page with snapshot.required=true but no full_page_image figure
    should output the snapshot image at the first block's position and
    skip all other text blocks on that page."""
    document = sample_document()
    document["pages"] = [
        {
            "physical_page": 5,
            "snapshot": {"required": True, "asset_id": "page-0005-snapshot"},
        }
    ]
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "Intro text",
            "source": {"page": 5},
            "attrs": {},
        },
        {
            "block_id": "b_p2",
            "type": "paragraph",
            "text": "More text on page 5",
            "source": {"page": 5},
            "attrs": {},
        },
        {
            "block_id": "b_p3",
            "type": "paragraph",
            "text": "Normal page text",
            "source": {"page": 6},
            "attrs": {},
        },
    ]
    # Create a snapshot image asset
    img_dir = tmp_path / "images" / "pages"
    img_dir.mkdir(parents=True)
    img_file = img_dir / "page_0005.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    document["assets"]["images"] = [
        {
            "image_id": "page-0005-snapshot",
            "path": str(img_file),
            "media_type": "image/png",
            "role": "page_snapshot",
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    # Snapshot should appear as a visual-page figure
    assert "visual-page" in html
    assert "page-0005-snapshot" in html
    # Text blocks on the visual page should be suppressed
    assert "Intro text" not in html
    assert "More text on page 5" not in html
    # Normal text on other pages should still appear
    assert "Normal page text" in html


def test_visual_page_with_full_page_image_figure(tmp_path):
    """A page with snapshot.required=true AND a full_page_image figure:
    the figure at its position emits the image, no other blocks on that
    page appear, and no duplicate snapshot image is emitted."""
    document = sample_document()
    document["pages"] = [
        {
            "physical_page": 12,
            "snapshot": {"required": True, "asset_id": "page-0012-snapshot"},
        }
    ]
    img_dir = tmp_path / "images" / "pages"
    img_dir.mkdir(parents=True)
    snap_file = img_dir / "page_0012.png"
    snap_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter",
            "source": {"page": 11},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_fig",
            "type": "figure",
            "text": "",
            "source": {"page": 12},
            "attrs": {"layout_role": "full_page_image", "image_id": "page-0012-full"},
        },
        {
            "block_id": "b_p_skip",
            "type": "paragraph",
            "text": "Should be skipped",
            "source": {"page": 12},
            "attrs": {},
        },
        {
            "block_id": "b_p_after",
            "type": "paragraph",
            "text": "After visual page",
            "source": {"page": 13},
            "attrs": {},
        },
    ]
    document["assets"]["images"] = [
        {
            "image_id": "page-0012-snapshot",
            "path": str(snap_file),
            "media_type": "image/png",
            "role": "page_snapshot",
        },
        {
            "image_id": "page-0012-full",
            "path": str(snap_file),
            "media_type": "image/png",
            "role": "figure",
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    # The figure should appear as a <figure> with the image
    assert "page-0012-full" in html
    # Text block on the visual page should be suppressed
    assert "Should be skipped" not in html
    # After-visual-page text should appear
    assert "After visual page" in html
    # Snapshot should NOT appear separately (dedup)
    # Count figure elements \u2014 should have exactly one for the visual page
    figure_count = html.count("<figure")
    assert figure_count == 1


def test_no_debug_metadata_in_epub(tmp_path):
    """EPUB XHTML should never contain 'Image placeholder (...)',
    bbox coordinates, or parser_raw_id values."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b1",
            "type": "paragraph",
            "text": "Normal text",
            "source": {"page": 1},
            "attrs": {},
        },
        {
            "block_id": "b2",
            "type": "figure",
            "text": "",
            "source": {"page": 3, "bbox": [10, 20, 300, 400]},
            "attrs": {"parser_raw_id": "#/pictures/5"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert "Image placeholder" not in html
    assert "bbox" not in html
    assert "#/pictures/" not in html


def test_toc_item_suppressed_in_chapter_body(tmp_path):
    """toc_item blocks should not appear in EPUB chapter body;
    nav.xhtml still provides navigation."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_toc1",
            "type": "toc_item",
            "text": "Table of contents entry",
            "source": {"page": 1},
            "attrs": {},
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "Body text",
            "source": {"page": 1},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_html = "\n".join(
            zf.read(name).decode("utf-8")
            for name in zf.namelist()
            if name.endswith(".xhtml") and "chapter" in name
        )
    # toc_item text should NOT appear in chapter body
    assert "Table of contents entry" not in chapter_html
    # Body text should appear
    assert "Body text" in chapter_html
    # nav.xhtml should still exist
    assert "EPUB/nav.xhtml" in zf.namelist()


def test_figure_caption_rendered_as_figcaption(tmp_path):
    """Figure blocks with caption text (in attrs.captions or trailing
    caption blocks) should render as <figcaption> in EPUB."""
    document = sample_document()
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    img_file = img_dir / "fig.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    document["blocks"] = [
        {
            "block_id": "b_fig",
            "type": "figure",
            "text": "Figure caption text",
            "source": {"page": 5},
            "attrs": {"image_path": "images/fig.jpg"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert "<figcaption>" in html
    assert "Figure caption text" in html


def test_chapter_local_footnote_numbering(tmp_path):
    """Footnote references should be renumbered as sequential natural
    numbers within each chapter, resetting in the next chapter.
    The canonical note_id links remain unchanged."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text1"},
                    {"type": "note_ref", "marker": "*", "target_note_id": "note_1"},
                    {"type": "text", "text": "Text2"},
                    {"type": "note_ref", "marker": "**", "target_note_id": "note_2"},
                    {"type": "text", "text": "Text3"},
                ]
            },
        },
        {
            "block_id": "b_fn1",
            "type": "footnote",
            "text": "Note 1",
            "source": {"page": 1},
            "attrs": {"note_id": "note_1"},
        },
        {
            "block_id": "b_fn2",
            "type": "footnote",
            "text": "Note 2",
            "source": {"page": 1},
            "attrs": {"note_id": "note_2"},
        },
        {
            "block_id": "b_h2",
            "type": "heading",
            "text": "Chapter 2",
            "source": {"page": 5},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p2",
            "type": "paragraph",
            "text": "",
            "source": {"page": 5},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "TextA"},
                    {"type": "note_ref", "marker": "\u2020", "target_note_id": "note_3"},
                    {"type": "text", "text": "TextB"},
                ]
            },
        },
        {
            "block_id": "b_fn3",
            "type": "footnote",
            "text": "Note 3",
            "source": {"page": 5},
            "attrs": {"note_id": "note_3"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_files = sorted(
            name for name in zf.namelist() if name.endswith(".xhtml") and "chapter" in name
        )
        ch1_html = zf.read(chapter_files[0]).decode("utf-8")
        ch2_html = zf.read(chapter_files[1]).decode("utf-8")

    # Chapter 1: markers should be renumbered 1, 2
    assert "<sup>1</sup>" in ch1_html
    assert "<sup>2</sup>" in ch1_html
    # Original markers (* and **) should not appear
    assert "<sup>*</sup>" not in ch1_html
    # Links should still point to canonical note_id
    assert "note_1" in ch1_html
    assert "note_2" in ch1_html

    # Chapter 2: footnote numbering resets \u2014 first reference is 1 again
    assert "<sup>1</sup>" in ch2_html
    # Original marker (\u2020) should not appear
    assert "\u2020" not in ch2_html


def test_visual_page_figure_anchor_not_first_block(tmp_path):
    """When a visual page has a full_page_image figure preceded by other
    blocks (heading, paragraph), the image should be emitted at the figure
    anchor position, NOT at the first block.  Blocks before the figure
    on that page are skipped."""
    document = sample_document()
    document["pages"] = [
        {
            "physical_page": 5,
            "snapshot": {"required": True, "asset_id": "page-0005-snapshot"},
        }
    ]
    img_dir = tmp_path / "images" / "pages"
    img_dir.mkdir(parents=True)
    snap_file = img_dir / "page_0005.png"
    snap_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_heading_on_vp",
            "type": "heading",
            "text": "Heading on visual page",
            "source": {"page": 5},
            "attrs": {},
            "level": 2,
        },
        {
            "block_id": "b_para_on_vp",
            "type": "paragraph",
            "text": "Paragraph on visual page",
            "source": {"page": 5},
            "attrs": {},
        },
        {
            "block_id": "b_fig",
            "type": "figure",
            "text": "",
            "source": {"page": 5},
            "attrs": {"layout_role": "full_page_image", "image_id": "page-0005-fig"},
        },
        {
            "block_id": "b_p_after",
            "type": "paragraph",
            "text": "After visual page",
            "source": {"page": 6},
            "attrs": {},
        },
    ]
    document["assets"]["images"] = [
        {
            "image_id": "page-0005-snapshot",
            "path": str(snap_file),
            "media_type": "image/png",
            "role": "page_snapshot",
        },
        {
            "image_id": "page-0005-fig",
            "path": str(snap_file),
            "media_type": "image/png",
            "role": "figure",
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    # The figure image should appear (emitted at the figure anchor)
    assert "page-0005-fig" in html
    # Blocks before the figure on the visual page should be suppressed
    assert "Heading on visual page" not in html
    assert "Paragraph on visual page" not in html
    # After-visual-page text should appear
    assert "After visual page" in html
    # Only one figure for the visual page (no duplicate snapshot)
    assert html.count("<figure") == 1


def test_footnote_numbering_across_paragraphs_in_same_chapter(tmp_path):
    """Footnote references in two separate paragraphs within the same
    chapter should get sequential chapter-local numbers (1, 2), not
    reset to (1, 1) in each paragraph."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text1"},
                    {"type": "note_ref", "marker": "*", "target_note_id": "note_a"},
                    {"type": "text", "text": " end1"},
                ]
            },
        },
        {
            "block_id": "b_p2",
            "type": "paragraph",
            "text": "",
            "source": {"page": 2},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text2"},
                    {"type": "note_ref", "marker": "\u2020", "target_note_id": "note_b"},
                    {"type": "text", "text": " end2"},
                ]
            },
        },
        {
            "block_id": "b_fn_a",
            "type": "footnote",
            "text": "Note A",
            "source": {"page": 1},
            "attrs": {"note_id": "note_a"},
        },
        {
            "block_id": "b_fn_b",
            "type": "footnote",
            "text": "Note B",
            "source": {"page": 2},
            "attrs": {"note_id": "note_b"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_files = sorted(
            name for name in zf.namelist() if name.endswith(".xhtml") and "chapter" in name
        )
        ch1_html = zf.read(chapter_files[0]).decode("utf-8")

    # First paragraph note_ref should be <sup>1</sup>
    assert "<sup>1</sup>" in ch1_html
    # Second paragraph note_ref should be <sup>2</sup> (sequential, not reset)
    assert "<sup>2</sup>" in ch1_html
    # Original markers should not appear
    assert "<sup>*</sup>" not in ch1_html


def test_figure_attrs_captions_rendered_as_figcaption(tmp_path):
    """Figure blocks with attrs.captions (a list of caption strings)
    should render those captions in <figcaption> in EPUB output."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    img_file = img_dir / "fig.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_fig",
            "type": "figure",
            "text": "",
            "source": {"page": 5},
            "attrs": {
                "image_path": "images/fig.jpg",
                "captions": ["ATTR CAPTION TEXT"],
            },
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert "ATTR CAPTION TEXT" in html
    assert "<figcaption>" in html


def test_snapshot_asset_id_from_canonical_metadata(tmp_path):
    """The snapshot image should be looked up using the asset_id from
    canonical page metadata (pages[*].snapshot.asset_id), not a
    hardcoded page-XXXX-snapshot naming convention."""
    document = sample_document()
    # Use a custom asset_id that differs from the convention
    document["pages"] = [
        {
            "physical_page": 5,
            "snapshot": {"required": True, "asset_id": "custom-snap-id"},
        }
    ]
    img_dir = tmp_path / "images" / "pages"
    img_dir.mkdir(parents=True)
    img_file = img_dir / "custom_snap.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "Text on visual page",
            "source": {"page": 5},
            "attrs": {},
        },
    ]
    # The image asset uses the custom asset_id from page metadata
    document["assets"]["images"] = [
        {
            "image_id": "custom-snap-id",
            "path": str(img_file),
            "media_type": "image/png",
            "role": "page_snapshot",
        }
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    # The custom-snap-id asset should be found and rendered
    assert "custom-snap-id" in html
    assert "visual-page" in html
    # Text on the visual page should be suppressed
    assert "Text on visual page" not in html


def test_visual_page_heading_creates_chapter_boundary(tmp_path):
    """A TOC-referenced heading that sits on a visual page should still
    create a chapter boundary, but the heading text itself should not
    appear in the chapter body (replaced by the snapshot)."""
    document = sample_document()
    # Page 5 is a visual page
    document["pages"] = [
        {
            "physical_page": 5,
            "snapshot": {"required": True, "asset_id": "page-0005-snapshot"},
        }
    ]
    img_dir = tmp_path / "images" / "pages"
    img_dir.mkdir(parents=True)
    img_file = img_dir / "page_0005.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "First chapter content",
            "source": {"page": 1},
            "attrs": {},
        },
        {
            "block_id": "b_h2_on_vp",
            "type": "heading",
            "text": "年表",
            "source": {"page": 5},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_vp_text",
            "type": "paragraph",
            "text": "Should be suppressed",
            "source": {"page": 5},
            "attrs": {},
        },
        {
            "block_id": "b_h3",
            "type": "heading",
            "text": "Chapter 3",
            "source": {"page": 10},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p3",
            "type": "paragraph",
            "text": "Third chapter content",
            "source": {"page": 10},
            "attrs": {},
        },
    ]
    document["assets"]["images"] = [
        {
            "image_id": "page-0005-snapshot",
            "path": str(img_file),
            "media_type": "image/png",
            "role": "page_snapshot",
        }
    ]
    # Clear sample_document TOC so it doesn't interfere
    document["toc"] = [
        {"title": "Chapter 1", "level": 1, "source_block_id": "b_h1"},
        {"title": "年表", "level": 1, "source_block_id": "b_h2_on_vp"},
        {"title": "Chapter 3", "level": 1, "source_block_id": "b_h3"},
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        chapter_files = sorted(
            name for name in zf.namelist() if name.endswith(".xhtml") and "chapter" in name
        )
        nav = zf.read("EPUB/nav.xhtml").decode("utf-8")
        chapters_html = []
        for cf in chapter_files:
            html = zf.read(cf).decode("utf-8")
            chapters_html.append(html)

    # The heading on the visual page should create a chapter boundary in nav
    assert "年表" in nav
    # But the heading text should NOT appear in any chapter body
    all_body = "".join(chapters_html)
    assert "年表" not in all_body
    # The snapshot should appear somewhere
    assert "page-0005-snapshot" in all_body
    # There should be exactly 3 chapters
    assert len(chapter_files) == 3
    # First chapter should have content
    assert "First chapter content" in chapters_html[0]
    # Third chapter should have content
    assert "Third chapter content" in chapters_html[2]


def test_toc_heading_role_suppressed_in_chapter_body(tmp_path):
    """Blocks with attrs.role='toc_heading' or 'toc_entry' should not
    appear in EPUB chapter body, alongside toc_item blocks."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_preamble",
            "type": "paragraph",
            "text": "Some intro",
            "source": {"page": 1},
            "attrs": {},
        },
        {
            "block_id": "b_toc_h",
            "type": "heading",
            "text": "目录",
            "source": {"page": 2},
            "attrs": {"role": "toc_heading"},
            "level": 2,
        },
        {
            "block_id": "b_toc_e1",
            "type": "toc_item",
            "text": "第一章",
            "source": {"page": 2},
            "attrs": {"role": "toc_entry"},
        },
        {
            "block_id": "b_toc_e2",
            "type": "paragraph",
            "text": "第二章",
            "source": {"page": 2},
            "attrs": {"role": "toc_entry"},
        },
        {
            "block_id": "b_body",
            "type": "paragraph",
            "text": "Real body text",
            "source": {"page": 3},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_html = "\n".join(
            zf.read(name).decode("utf-8")
            for name in zf.namelist()
            if name.endswith(".xhtml") and "chapter" in name
        )
        nav_html = zf.read("EPUB/nav.xhtml").decode("utf-8")

    # TOC role blocks should not appear in chapter body
    assert "目录" not in chapter_html
    assert "第一章" not in chapter_html
    assert "第二章" not in chapter_html
    # Non-TOC body text should appear
    assert "Some intro" in chapter_html
    assert "Real body text" in chapter_html


def test_snapshot_asset_missing_shows_placeholder(tmp_path):
    """When a visual page has no snapshot image asset available, the
    page should show a placeholder image instead of being silently
    blank and dropping all text content."""
    document = sample_document()
    document["pages"] = [
        {
            "physical_page": 5,
            "snapshot": {"required": True, "asset_id": "page-0005-snapshot"},
        }
    ]
    # No image asset for the snapshot — asset is missing
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "Text on visual page without image",
            "source": {"page": 5},
            "attrs": {},
        },
        {
            "block_id": "b_p2",
            "type": "paragraph",
            "text": "After visual page text",
            "source": {"page": 6},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    # A placeholder should appear instead of being silently blank
    assert "image-placeholder" in html
    # Text on the visual page should still be suppressed (snapshot/placeholder replaces it)
    assert "Text on visual page without image" not in html
    # Text after the visual page should appear
    assert "After visual page text" in html


def test_all_blocks_suppressed_produces_fallback_chapter(tmp_path):
    """When every block is suppressed (e.g., all are toc_item/toc_heading/
    toc_entry), the exporter should still produce at least one chapter
    so the EPUB is structurally valid (not zero spine items)."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_toc1",
            "type": "toc_item",
            "text": "第一章",
            "source": {"page": 1},
            "attrs": {"role": "toc_entry"},
        },
        {
            "block_id": "b_toc2",
            "type": "heading",
            "text": "目录",
            "source": {"page": 1},
            "attrs": {"role": "toc_heading"},
            "level": 2,
        },
        {
            "block_id": "b_toc3",
            "type": "toc_item",
            "text": "第二章",
            "source": {"page": 1},
            "attrs": {"role": "toc_entry"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        chapter_files = [n for n in names if n.startswith("EPUB/chapter_") and n.endswith(".xhtml")]
        opf = zf.read("EPUB/content.opf").decode("utf-8")

    # There should be at least one chapter XHTML file
    assert len(chapter_files) >= 1
    # The OPF spine should have at least one itemref
    assert "<itemref" in opf


# ─── Readability & Layout Polish: new tests ───────────────────────────


def test_chapter_xhtml_readable_block_formatting_and_xml_parseable(tmp_path):
    """Chapter XHTML output should have readable block-level formatting
    (wrapper/body/main on separate lines, body indented) and remain
    XML-parseable."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "First paragraph text.",
            "source": {"page": 1},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = [n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n]
        from xml.etree import ElementTree as ET

        for name in chapter_names:
            content = zf.read(name).decode("utf-8")
            # Must be valid XML
            ET.fromstring(content)
            # Wrapper elements should be on separate lines
            assert "<body>\n" in content
            assert "<main>\n" in content
            # Body content should be indented by 2 spaces
            assert "  <h1>" in content or "  <h2>" in content


def test_figure_caption_newlines_render_as_structured_paragraphs(tmp_path):
    """Figure captions with embedded newlines should render as
    <figcaption><p class="caption-title">...</p><p class="caption-body">...</p>
    inside <figure>."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    img_file = img_dir / "fig.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_fig",
            "type": "figure",
            "text": "",
            "source": {"page": 5},
            "attrs": {
                "image_path": "images/fig.jpg",
                "captions": ["Line one\nLine two"],
            },
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    # Newline in caption becomes structured paragraphs
    assert '<p class="caption-title">Line one</p>' in html
    assert '<p class="caption-body">Line two</p>' in html
    # No <br/> should appear inside figcaption
    assert "<br/>" not in html
    # figcaption must be inside <figure>
    figcaption_positions = [m.start() for m in re.finditer(r"<figcaption>", html)]
    figure_starts = [m.start() for m in re.finditer(r"<figure", html)]
    figure_ends = [m.start() for m in re.finditer(r"</figure>", html)]
    for cap_pos in figcaption_positions:
        inside = any(fs < cap_pos < fe for fs, fe in zip(figure_starts, figure_ends, strict=True))
        assert inside, f"<figcaption> at {cap_pos} is outside <figure>"


def test_captioned_figure_has_new_css_classes(tmp_path):
    """Captioned figures should include figure-block and has-caption CSS
    classes, and remain inside <figure>. The CSS stylesheet should contain
    .figure-block break-inside rules and constrained image max-height."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    img_file = img_dir / "fig.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_fig",
            "type": "figure",
            "text": "",
            "source": {"page": 5},
            "attrs": {
                "image_path": "images/fig.jpg",
                "captions": ["A caption"],
            },
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output, base_dir=tmp_path)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    # XHTML: figure should have figure-block and has-caption classes
    assert "figure-block" in html
    assert "has-caption" in html
    # CSS: figure-block should have break-inside rules
    assert "break-inside: avoid" in css
    assert "page-break-inside: avoid" in css
    # CSS: figure-block img should have constrained max-height
    assert ".figure-block img" in css
    assert "max-height: 85vh" in css


def test_footnote_marker_stripped_with_note_marker_attr(tmp_path):
    """Footnote text like '³ Lothar...' should render without the leading
    marker when attrs.note_marker is provided, while noteref links still
    show chapter-local numbers."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Main text"},
                    {"type": "note_ref", "marker": "3", "target_note_id": "note_fn1"},
                    {"type": "text", "text": " more"},
                ],
            },
        },
        {
            "block_id": "b_fn1",
            "type": "footnote",
            "text": "3 Lothar explains this.",
            "source": {"page": 1},
            "attrs": {"note_id": "note_fn1", "note_marker": "3"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    # Footnote body should NOT contain leading "3" marker
    assert "Lothar explains this." in html
    # The stripped footnote should not start with "3 Lothar"
    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    aside_content = aside_match.group()
    # "3" should NOT appear as the leading text in the footnote body
    assert "<p>3 Lothar" not in aside_content
    # Noteref link should still show chapter-local number (1)
    assert "<sup>1</sup>" in html


def test_footnote_marker_stripped_without_note_marker_attr(tmp_path):
    """Footnote text like '3 Lothar...' should strip the leading numeric
    marker via the fallback heuristic when attrs.note_marker is absent."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text"},
                    {"type": "note_ref", "marker": "3", "target_note_id": "note_fn2"},
                ],
            },
        },
        {
            "block_id": "b_fn2",
            "type": "footnote",
            "text": "3 Lothar explains this.",
            "source": {"page": 1},
            "attrs": {"note_id": "note_fn2"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    # Fallback heuristic should strip the leading "3"
    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    assert "<p>3 Lothar" not in aside_match.group()
    assert "Lothar explains this." in html


def test_footnote_marker_stripped_with_dot_delimiter(tmp_path):
    """When note_marker="3" and footnote text is "3. Note text", the marker
    plus the dot delimiter should both be consumed, yielding "Note text"
    (not ". Note text")."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text"},
                    {"type": "note_ref", "marker": "3", "target_note_id": "note_dot"},
                ],
            },
        },
        {
            "block_id": "b_fn_dot",
            "type": "footnote",
            "text": "3. Note text",
            "source": {"page": 1},
            "attrs": {"note_id": "note_dot", "note_marker": "3"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    # Should strip "3." completely, not leave ". Note text"
    assert ". Note text" not in aside_match.group()
    assert "Note text" in aside_match.group()
    # Should NOT leave the bare marker as leading text
    assert "<p>3. Note text" not in aside_match.group()


def test_footnote_superscript_marker_stripped(tmp_path):
    """When note_marker="3" and footnote text starts with superscript "³",
    the superscript form should be recognised and stripped."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text"},
                    {"type": "note_ref", "marker": "3", "target_note_id": "note_sup"},
                ],
            },
        },
        {
            "block_id": "b_fn_sup",
            "type": "footnote",
            "text": "³ Lothar explains this.",
            "source": {"page": 1},
            "attrs": {"note_id": "note_sup", "note_marker": "3"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    # Superscript ³ should be stripped, not left in output
    assert "³ Lothar" not in aside_match.group()
    assert "Lothar explains this." in aside_match.group()


def test_footnote_symbol_marker_fallback(tmp_path):
    """When footnote text starts with a reference symbol like * and there
    is no note_marker attr, the fallback heuristic should strip it."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text"},
                    {"type": "note_ref", "marker": "*", "target_note_id": "note_sym"},
                ],
            },
        },
        {
            "block_id": "b_fn_sym",
            "type": "footnote",
            "text": "* See appendix.",
            "source": {"page": 1},
            "attrs": {"note_id": "note_sym"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    # Symbol * should be stripped via fallback
    assert "<p>* See appendix" not in aside_match.group()
    assert "See appendix." in aside_match.group()


def test_footnote_marker_not_stripped_without_delimiter(tmp_path):
    """Footnote text like "3rd edition note" with note_marker="3" should NOT
    be stripped because there is no delimiter between "3" and "rd" — the
    regex requires at least one delimiter character after the marker."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text"},
                    {"type": "note_ref", "marker": "3", "target_note_id": "note_no_delim"},
                ],
            },
        },
        {
            "block_id": "b_fn_nd",
            "type": "footnote",
            "text": "3rd edition note",
            "source": {"page": 1},
            "attrs": {"note_id": "note_no_delim", "note_marker": "3"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    # "3rd edition note" should NOT be stripped — "3" is part of "3rd", not a marker
    # Check that the <p> starts with "3rd", not "rd"
    assert re.search(r'<p>3rd edition note</p>', aside_match.group()) is not None


def test_chapter_title_page_box_sizing(tmp_path):
    """The chapter-title-page CSS should include box-sizing: border-box
    so that padding + min-height do not exceed the declared min-height."""
    document = sample_document()
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    assert ".chapter-title-page" in css
    assert "box-sizing: border-box" in css


def test_footnote_marker_not_stripped_from_normal_paragraph(tmp_path):
    """The footnote marker stripper should NOT strip leading numbers from
    normal paragraphs or display blocks — only footnote blocks."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "3 is the magic number.",
            "source": {"page": 1},
            "attrs": {},
        },
        {
            "block_id": "b_db1",
            "type": "display_block",
            "text": "3rd edition notice",
            "source": {"page": 1},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    # Paragraph text should retain "3"
    assert "3 is the magic number." in html
    # Display block text should retain "3rd"
    assert "3rd edition notice" in html


def test_display_block_css_has_distinct_cjk_font_stack(tmp_path):
    """The CSS stylesheet should set a concrete CJK font stack on
    .display-block and on .display-block-paragraph, ensuring internal
    text doesn't resolve to the body paragraph font in EPUB readers."""
    document = sample_document()
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    assert ".display-block" in css
    assert "Kaiti SC" in css
    assert "STKaiti" in css
    # The child text wrapper should also explicitly set the distinct CJK stack.
    dp_block = css.split(".display-block-paragraph")[1].split("}")[0]
    assert "font-family:" in dp_block
    assert "Kaiti SC" in dp_block
    assert ".display-block-standalone" in css
    assert ".display-block-signature" in css


def test_chapter_heading_newlines_render_as_br(tmp_path):
    """Chapter-splitting heading text with embedded \\n should render
    line breaks as <br/> in the XHTML output."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "第一章\n楼兰",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "Body text.",
            "source": {"page": 1},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    # Heading newline should become <br/>
    assert "第一章<br/>" in html
    assert "楼兰" in html


def test_chapter_title_page_has_page_break_css(tmp_path):
    """Chapter-splitting headings should be wrapped in a
    chapter-title-page div with break-after/page-break-after CSS.
    The CSS stylesheet must contain the corresponding rules."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "Content.",
            "source": {"page": 1},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    # Chapter heading should be inside chapter-title-page div
    assert 'class="chapter-title-page"' in html
    # CSS: chapter-title-page should have page-break rules
    assert ".chapter-title-page" in css
    assert "break-after: always" in css
    assert "page-break-after: always" in css


def test_footnote_superscript_marker_fallback_without_note_marker(tmp_path):
    """Footnote text like "³ Lothar..." without note_marker attr should
    still be stripped by the fallback regex, which must cover ² (U+00B2)
    and ³ (U+00B3) outside the Latin-1 Supplement range."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text"},
                    {"type": "note_ref", "marker": "3", "target_note_id": "note_3"},
                ],
            },
        },
        {
            "block_id": "b_fn3",
            "type": "footnote",
            "text": "³ Lothar explains this.",
            "source": {"page": 1},
            # No note_marker attr — fallback must handle superscript ³
            "attrs": {"note_id": "note_3"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    # The superscript marker ³ should be stripped, leaving just "Lothar explains this."
    assert "Lothar explains this." in aside_match.group()
    assert "³" not in aside_match.group()


def test_footnote_multi_digit_superscript_marker_with_note_marker(tmp_path):
    """Footnote text like "¹² Combined" with note_marker="12" should
    be stripped.  The superscript-to-digit normalization (¹² → "12")
    must handle multi-digit sequences."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text"},
                    {"type": "note_ref", "marker": "12", "target_note_id": "note_12"},
                ],
            },
        },
        {
            "block_id": "b_fn12",
            "type": "footnote",
            "text": "¹² Combined references.",
            "source": {"page": 1},
            "attrs": {"note_id": "note_12", "note_marker": "12"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    # ¹² should be stripped, leaving "Combined references."
    assert "Combined references." in aside_match.group()
    assert "¹²" not in aside_match.group()


def test_footnote_parenthesized_delimiter_ascii(tmp_path):
    """Footnote text like "1) Note text" should strip the marker "1"
    plus the closing-paren delimiter."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text"},
                    {"type": "note_ref", "marker": "1", "target_note_id": "note_paren"},
                ],
            },
        },
        {
            "block_id": "b_fn_paren",
            "type": "footnote",
            "text": "1) Note text",
            "source": {"page": 1},
            "attrs": {"note_id": "note_paren", "note_marker": "1"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    # "1)" should be stripped, leaving "Note text"
    assert re.search(r'<p>Note text</p>', aside_match.group()) is not None
    assert "1)" not in aside_match.group()


def test_footnote_parenthesized_delimiter_fullwidth(tmp_path):
    """Footnote text like "1）Note text" (fullwidth closing paren) should
    strip the marker "1" plus the fullwidth paren delimiter."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_h1",
            "type": "heading",
            "text": "Chapter 1",
            "source": {"page": 1},
            "attrs": {},
            "level": 1,
        },
        {
            "block_id": "b_p1",
            "type": "paragraph",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "inline_runs": [
                    {"type": "text", "text": "Text"},
                    {"type": "note_ref", "marker": "1", "target_note_id": "note_fparen"},
                ],
            },
        },
        {
            "block_id": "b_fn_fparen",
            "type": "footnote",
            "text": "1）Note text",
            "source": {"page": 1},
            "attrs": {"note_id": "note_fparen", "note_marker": "1"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        chapter_names = sorted(
            n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n
        )
        html = zf.read(chapter_names[0]).decode("utf-8")

    aside_match = re.search(r'<aside[^>]*>.*?</aside>', html, re.DOTALL)
    assert aside_match is not None
    # "1）" should be stripped, leaving "Note text"
    assert re.search(r'<p>Note text</p>', aside_match.group()) is not None
    assert "1）" not in aside_match.group()


def test_display_block_multi_line_splits_into_paragraphs(tmp_path):
    """A display_block with multi-line text should split each non-empty
    line into its own dedicated wrapper inside the <blockquote>."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_db",
            "type": "display_block",
            "text": "第一行\n第二行\n第三行",
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
    assert '<blockquote class="display-block">' in html
    assert '<div class="display-block-paragraph">第一行</div>' in html
    assert '<div class="display-block-paragraph">第二行</div>' in html
    assert '<div class="display-block-paragraph">第三行</div>' in html
    assert "<blockquote class=\"display-block\"><p>" not in html
    # Should NOT contain bare text outside wrappers inside the blockquote.
    assert "第一行<br" not in html


def test_display_block_signature_uses_body_size_and_no_indent(tmp_path):
    """A display-block-signature should use body font-size (1em) and have
    non-indented, right-aligned paragraphs."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_db",
            "type": "display_block",
            "text": "落款行一\n落款行二",
            "source": {"page": 1, "bbox": None},
            "attrs": {"layout_role": "flush_right_terminal_block"},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    # HTML should have signature class + paragraph wrappers
    assert '<blockquote class="display-block display-block-signature">' in html
    assert '<div class="display-block-paragraph">落款行一</div>' in html
    assert '<div class="display-block-paragraph">落款行二</div>' in html
    # CSS: .display-block-signature uses body font-size
    sig_block = re.search(r'\.display-block-signature\s*\{[^}]+\}', css)
    assert sig_block is not None
    assert "font-size: 1em" in sig_block.group()
    # CSS: nested paragraphs are not indented and right-aligned
    nested = css.split(".display-block-signature .display-block-paragraph")[1].split("}")[0]
    assert "text-indent: 0" in nested
    assert "text-align: right" in nested


def test_display_block_css_has_wrapper_indent(tmp_path):
    """CSS should contain .display-block-paragraph rule with text-indent: 2em."""
    document = sample_document()
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    assert ".display-block-paragraph" in css
    p_block = css.split(".display-block-paragraph")[1].split("}")[0]
    assert "text-indent: 2em" in p_block
    assert "text-align: justify" in p_block


def test_display_block_css_no_global_text_indent(tmp_path):
    """CSS .display-block should NOT set text-indent: 0 globally
    (was moved to the p-sub-selector)."""
    document = sample_document()
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    display_block_section = css.split(".display-block")[1]
    # .display-block section should NOT contain text-indent (only the p variant does)
    # Bail out early if the section is empty (regex anchor issue)
    assert "text-indent" not in display_block_section.split(".display-block-standalone")[0]


def test_caption_css_left_align_distinct_cjk_font_stack(tmp_path):
    """figcaption and .caption CSS should have text-align: left and
    a distinct CJK font stack."""
    document = sample_document()
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    # figcaption
    assert "figcaption" in css
    fig_section = css.split("figcaption")[1].split("}")[0]
    assert "text-align: left" in fig_section
    assert "Kaiti SC" in fig_section

    # .caption (standalone class, not .caption-title or .caption-body)
    cap_block = re.search(r'\.caption\s*\{[^}]+\}', css)
    assert cap_block is not None
    cap_section = cap_block.group()
    assert "text-align: left" in cap_section
    assert "Kaiti SC" in cap_section
    assert "text-indent: 0" in cap_section


def test_caption_css_no_center(tmp_path):
    """figcaption and .caption should NOT have text-align: center."""
    document = sample_document()
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    # Extract the figcaption rule block only (up to closing brace)
    fig_block = re.search(r'figcaption\s*\{[^}]+\}', css)
    assert fig_block is not None
    assert "text-align: center" not in fig_block.group()

    cap_block = re.search(r'\.caption\s*\{[^}]+\}', css)
    assert cap_block is not None
    assert "text-align: center" not in cap_block.group()


def test_caption_newline_structured_not_br(tmp_path):
    """Caption text with a newline should produce structured
    <p class="caption-title"> / <p class="caption-body"> paragraphs
    instead of <br/>."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_fig",
            "type": "figure",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "image_id": "img_cap_nl",
                "captions": ["Line one\nLine two"],
            },
        },
    ]
    # Add a matching image asset so the figure renders with <figcaption>
    document["assets"] = {
        "images": [
            {
                "image_id": "img_cap_nl",
                "path": str(tmp_path / "test.png"),
            },
        ],
    }
    # Create the dummy image file
    (tmp_path / "test.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    # The caption should be structured paragraphs, not <br/>
    assert '<p class="caption-title">Line one</p>' in html
    assert '<p class="caption-body">Line two</p>' in html
    # No <br/> inside figcaption
    assert "<br/>" not in html


def test_caption_title_and_body_css(tmp_path):
    """CSS should contain .caption-title with text-indent: 0 and
    .caption-body with text-indent: 2em."""
    document = sample_document()
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    ct_block = re.search(r'\.caption-title\s*\{[^}]+\}', css)
    assert ct_block is not None
    assert "text-indent: 0" in ct_block.group()

    cb_block = re.search(r'\.caption-body\s*\{[^}]+\}', css)
    assert cb_block is not None
    assert "text-indent: 2em" in cb_block.group()


def test_figcaption_p_margin_css(tmp_path):
    """CSS should contain figcaption p with margin."""
    document = sample_document()
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        css = zf.read("EPUB/styles/book.css").decode("utf-8")

    fp_block = re.search(r'figcaption\s+p\s*\{[^}]+\}', css)
    assert fp_block is not None
    assert "margin" in fp_block.group()


def test_figure_caption_single_line_no_body_paragraph(tmp_path):
    """A single-line figure caption should only produce caption-title,
    no caption-body."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_fig",
            "type": "figure",
            "text": "",
            "source": {"page": 1},
            "attrs": {
                "image_id": "img_single",
                "captions": ["Just a title"],
            },
        },
    ]
    document["assets"] = {
        "images": [
            {
                "image_id": "img_single",
                "path": str(tmp_path / "test.png"),
            },
        ],
    }
    (tmp_path / "test.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert '<p class="caption-title">Just a title</p>' in html
    assert "caption-body" not in html


def test_standalone_caption_multi_line_structured(tmp_path):
    """A standalone caption block (not trailing a figure) with multi-line
    text should produce a <div class="caption"> with caption-title and
    caption-body paragraphs."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_cap",
            "type": "caption",
            "text": "图片标题\n说明文字第一段",
            "source": {"page": 1},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert '<div class="caption">' in html
    assert '<p class="caption-title">图片标题</p>' in html
    assert '<p class="caption-body">说明文字第一段</p>' in html


def test_standalone_caption_single_line_is_simple_p(tmp_path):
    """A standalone caption block with single-line text should produce
    <p class="caption">...</p>, not a <div> wrapper."""
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b_cap",
            "type": "caption",
            "text": "Just a caption",
            "source": {"page": 1},
            "attrs": {},
        },
    ]
    output = tmp_path / "book.epub"

    export_epub(document, output)

    with zipfile.ZipFile(output) as zf:
        html = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml")
        )
    assert '<p class="caption">Just a caption</p>' in html
    assert '<div class="caption">' not in html
