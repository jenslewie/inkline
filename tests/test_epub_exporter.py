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
        html = "\n".join(zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml"))
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
        html = "\n".join(zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml"))
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
        html = "\n".join(zf.read(name).decode("utf-8") for name in zf.namelist() if name.endswith(".xhtml"))
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
