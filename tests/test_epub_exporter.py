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
